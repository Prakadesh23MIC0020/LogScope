import os
import json
import re
import time

import requests

from flask import (
    Flask,
    render_template,
    request,
    jsonify
)

from logparser.log_parser import parse_log

from analyzer.analyzer import (
    group_errors,
    get_statistics,
    correlate_events
)

from analyzer.explanations import (
    get_explanation
)

from analyzer.knowledge import (
    initialize_knowledge,
    lookup_knowledge
)

from analyzer.lookup import (
    lookup_error
)

from analyzer.ai_resolver import (
    resolve_error
)

from analyzer.environment_detector import (
    detect_environment,
    detect_primary_environment,
    detect_component
)

from database.db import (
    init_db,
    add_knowledge,
    get_knowledge_stats
)


app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)


GITHUB_API = "https://api.github.com"
GITHUB_ALLOWED_EXTENSIONS = {".log", ".txt", ".out", ".err", ".json", ".csv", ".xml", ".yaml", ".yml", ".properties", ".trace", ".dump", ".syslog"}
GITHUB_MAX_FILES = 50
GITHUB_MAX_FILE_BYTES = 5 * 1024 * 1024
GITHUB_MAX_BATCH_BYTES = 15 * 1024 * 1024
GITHUB_MAX_TREE_FILES = 5000


def _github_headers():
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "LogScope-Public-Log-Browser",
    }


def _parse_public_github_repo(value):
    """Accept a public GitHub repository URL or owner/repository shorthand."""
    from urllib.parse import urlparse

    value = str(value or "").strip()
    if not value:
        raise ValueError("Enter a public GitHub repository URL, such as https://github.com/logpai/loghub.")
    if value.startswith("github.com/"):
        value = "https://" + value
    if "://" not in value and value.count("/") == 1:
        value = "https://github.com/" + value
    parsed = urlparse(value)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Only public repositories hosted on github.com are supported.")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2 or parts[0] in {"settings", "features", "topics", "orgs", "login", "signup"}:
        raise ValueError("Enter a repository URL in the format https://github.com/owner/repository.")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo):
        raise ValueError("The repository owner or name contains unsupported characters.")
    return owner, repo


def _github_get(url, params=None):
    response = requests.get(url, headers=_github_headers(), params=params, timeout=15)
    if response.status_code == 404:
        raise LookupError("Repository or file not found. Check that the repository is public and the URL is correct.")
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        raise RuntimeError("GitHub's unauthenticated API rate limit has been reached. Try again later.")
    response.raise_for_status()
    return response


def _github_list_files(repo_value):
    from urllib.parse import quote

    owner, repo = _parse_public_github_repo(repo_value)
    repo_url = f"{GITHUB_API}/repos/{owner}/{repo}"
    metadata = _github_get(repo_url).json()
    if metadata.get("private"):
        raise ValueError("This repository is private. Only public GitHub repositories are supported.")
    branch = metadata.get("default_branch") or "main"
    tree_url = f"{repo_url}/git/trees/{quote(branch, safe='')}"
    tree_response = _github_get(tree_url, params={"recursive": "1"}).json()
    tree = tree_response.get("tree", [])
    files = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = item.get("path") or ""
        ext = os.path.splitext(path.lower())[1]
        size = int(item.get("size") or 0)
        basename = path.rsplit("/", 1)[-1].lower()
        # Also accept extensionless files explicitly named as logs/traces, while
        # avoiding source code, README files, and arbitrary repository assets.
        looks_like_log = any(token in basename for token in ("log", "error", "trace", "syslog", "events"))
        if (ext not in GITHUB_ALLOWED_EXTENSIONS and not (not ext and looks_like_log)) or size > GITHUB_MAX_FILE_BYTES:
            continue
        if not path or size < 0:
            continue
        files.append({
            "name": path.rsplit("/", 1)[-1],
            "path": path,
            "display_path": path,
            "size": size,
            "sha": item.get("sha", ""),
            "download_url": f"https://raw.githubusercontent.com/{owner}/{repo}/{quote(branch, safe='')}/{quote(path, safe='/')}"
        })
        if len(files) >= GITHUB_MAX_TREE_FILES:
            break
    files.sort(key=lambda item: item["path"].lower())
    return {"owner": owner, "repo": repo, "branch": branch, "files": files, "tree_truncated": bool(tree_response.get("truncated"))}


def _github_download(file_item):
    response = requests.get(
        file_item["download_url"],
        headers={"User-Agent": "LogScope-Public-Log-Browser"},
        timeout=20,
    )
    response.raise_for_status()
    return response.content

_initialized = False


def _learned_pattern_matches(pattern, message):
    """Require meaningful signature overlap before reusing user-taught fixes."""
    pattern_text = re.sub(r"[^a-z0-9]+", " ", str(pattern or "").lower()).strip()
    message_text = re.sub(r"[^a-z0-9]+", " ", str(message or "").lower()).strip()
    if not pattern_text or not message_text:
        return False
    if pattern_text in message_text:
        return len(pattern_text) >= 8
    ignored = {"error", "unknown", "exception", "failed", "failure", "issue", "problem", "the", "and", "for", "with", "from"}
    words = [word for word in pattern_text.split() if len(word) > 2 and word not in ignored]
    if len(words) < 2:
        return False
    matched = sum(1 for word in words if word in message_text.split())
    return matched >= 2 and matched / len(words) >= 0.65


def ensure_database():

    global _initialized

    if _initialized:
        return

    init_db()
    initialize_knowledge()

    _initialized = True


@app.route("/")
def index():

    ensure_database()

    return render_template(
        "index.html"
    )


@app.route(
    "/api/health",
    methods=["GET"]
)
def health():

    try:

        ensure_database()

        return jsonify({
            "status": "ok",
            "database": "connected"
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "database": "unavailable",
            "message": "Database initialization failed. Check server configuration."
        }), 500


@app.route(
    "/api/analyze",
    methods=["POST"]
)
def analyze():

    ensure_database()

    try:

        data = request.get_json(
            silent=True
        ) or {}

        text = data.get(
            "text",
            ""
        )

        source_name = data.get(
            "source_name",
            "Pasted Log"
        )

        if not text.strip():

            return jsonify({
                "error":
                    "Please provide a log."
            }), 400

        parsed = parse_log(
            text
        )

        errors = group_errors(
            parsed
        )

        environments = detect_environment(
            text
        )

        primary_environment = (
            detect_primary_environment(
                text
            )
        )

        errors = correlate_events(errors)

        for error in errors:
            raw = error.get("raw", "")
            component = detect_component(raw, primary_environment)
            message = str(error.get("message") or "")

            # Previously confirmed fixes are reused when their generalized signature matches.
            try:
                learned = lookup_knowledge(
                    error_type=error.get("type", "Unknown Error"),
                    message=message,
                    environment=primary_environment
                )
            except Exception:
                # Built-in diagnosis should remain available if the persistent
                # learning store is temporarily unavailable.
                learned = None
            if (learned and learned.get("source") == "user-confirmed"
                    and _learned_pattern_matches(learned.get("pattern"), message)):
                explanation = {
                    "category": learned.get("environment") or primary_environment,
                    "component": learned.get("component") or component,
                    "description": learned.get("description") or "Previously confirmed diagnosis.",
                    "cause": learned.get("cause") or "Cause recorded from a user-confirmed resolution.",
                    "fix": learned.get("fix") or "Review the recorded fix before applying it.",
                    "code": learned.get("example") or "",
                    "source": "User-confirmed knowledge",
                    "confidence": float(learned.get("confidence") or 0.85),
                    "classification_confidence": float(learned.get("confidence") or 0.85),
                    "root_cause_confidence": float(learned.get("confidence") or 0.85),
                    "times_seen": int(learned.get("times_seen") or 0),
                    "source_links": []
                }
                error["explanation"] = explanation
                error["classification_confidence"] = explanation["classification_confidence"]
                error["root_cause_confidence"] = explanation["root_cause_confidence"]
                error["learned_knowledge_id"] = learned.get("id")
                continue

            # Deterministic local rules always take priority over external research.
            diagnosis = resolve_error(
                error_type=error.get("type", "Unknown Error"),
                message=message,
                raw_text=raw,
                environment=primary_environment,
                component=component,
                research_results=[]
            )

            if diagnosis:
                explanation = {
                    "category": diagnosis.get("environment", primary_environment),
                    "component": diagnosis.get("component", component),
                    "description": diagnosis.get("description", ""),
                    "cause": diagnosis.get("cause", ""),
                    "fix": diagnosis.get("fix", ""),
                    "code": diagnosis.get("example", ""),
                    "source": "Rule-based + External Research" if diagnosis.get("sources") else "Rule-based diagnosis",
                    "confidence": float(diagnosis.get("classification_confidence", diagnosis.get("confidence", 0))),
                    "classification_confidence": float(diagnosis.get("classification_confidence", diagnosis.get("confidence", 0))),
                    "root_cause_confidence": float(diagnosis.get("root_cause_confidence", 0.35)),
                    "times_seen": 0,
                    "source_links": []
                }
                # External links are attached only when their titles are relevant to this signature.
                safe_message = re.sub(r"(?i)(password|token|secret|api[_-]?key|authorization|cookie)\s*[=:]\s*[^\s,;]+", r"\1=<redacted>", message)
                safe_message = re.sub(r"[A-Za-z]:\\[^\s]+|/(?:[^\s/]+/)+[^\s]*", "<path>", safe_message)
                safe_message = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<email>", safe_message)
                safe_message = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", safe_message)
                if diagnosis.get("error_type", "").startswith("HTTP ") or diagnosis.get("error_type") == "Database Connection Pool Exhaustion":
                    research = lookup_error(error.get("type"), safe_message[:180], primary_environment, "", component)
                    second = resolve_error(error.get("type"), message, raw, primary_environment, component, research.get("results", []))
                    if second:
                        explanation["source_links"] = second.get("sources", [])
                        if explanation["source_links"]:
                            explanation["source"] = "Rule-based + External Research"
                error["explanation"] = explanation
                error["classification_confidence"] = explanation["classification_confidence"]
                error["root_cause_confidence"] = explanation["root_cause_confidence"]
                continue

            explanation = get_explanation(error_type=error.get("type", "Unknown Error"), raw_text=raw, environment=environments)
            if explanation:
                error["explanation"] = explanation
                continue

            research = lookup_error(error.get("type"), message[:180], primary_environment, "", component)
            research_results = research.get("results", [])
            error["explanation"] = {
                "category": primary_environment,
                "component": component,
                "description": "LogScope could not determine a reliable explanation from its built-in rules or stored knowledge.",
                "cause": "The available evidence is insufficient to establish a root cause.",
                "fix": "Inspect the relevant stack-trace location and correlate this event with nearby application and dependency logs. Do not apply a change until the cause is verified.",
                "code": "",
                "source": "External research only" if research_results else "No reliable diagnosis",
                "confidence": 0,
                "classification_confidence": 0,
                "root_cause_confidence": 0,
                "times_seen": 0,
                "source_links": [{"title": item["title"], "url": item["url"], "source": item["source"]} for item in research_results[:4]]
            }

        stats = get_statistics(
            errors,
            len(
                text.splitlines()
            )
        )

        return jsonify({
            "success": True,
            "source_name": source_name,
            "environment": environments,
            "primary_environment":
                primary_environment,
            "stats": stats,
            "errors": errors
        })

    except Exception as e:

        app.logger.error("Analysis failed (%s)", type(e).__name__)

        return jsonify({
            "error":
                "Analysis failed. Check the server logs for diagnostic details."
        }), 500


@app.route("/api/github/files", methods=["GET"])
def github_files():
    repo_value = request.args.get("repo", "")
    try:
        result = _github_list_files(repo_value)
        return jsonify({
            "success": True,
            "repository": f"{result['owner']}/{result['repo']}",
            "branch": result["branch"],
            "files": result["files"],
            "count": len(result["files"]),
            "tree_truncated": result["tree_truncated"],
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 429
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        app.logger.warning("GitHub file listing failed (%s)", type(exc).__name__)
        if status == 403:
            message = "GitHub denied the request or its API rate limit was reached. Try again later."
        else:
            message = "Could not retrieve this public repository from GitHub. Try again shortly."
        return jsonify({"success": False, "error": message}), 502


@app.route("/api/github/fetch", methods=["POST"])
def github_fetch():
    data = request.get_json(silent=True) or {}
    repo_value = data.get("repo", "")
    paths = data.get("paths")
    if not isinstance(paths, list) or not paths:
        return jsonify({"success": False, "error": "Select at least one GitHub log file."}), 400
    if len(paths) > GITHUB_MAX_FILES:
        return jsonify({"success": False, "error": f"Select no more than {GITHUB_MAX_FILES} files per batch."}), 400
    if any(not isinstance(path, str) or len(path) > 1000 for path in paths):
        return jsonify({"success": False, "error": "One or more selected file paths are invalid."}), 400

    try:
        result = _github_list_files(repo_value)
        available = {item["path"]: item for item in result["files"]}
        selected = []
        for path in paths:
            item = available.get(path)
            if not item:
                return jsonify({"success": False, "error": "One or more selected files are unavailable or unsupported. Refresh the repository file list and try again."}), 400
            selected.append(item)

        total_bytes = sum(item["size"] for item in selected)
        if total_bytes > GITHUB_MAX_BATCH_BYTES:
            return jsonify({"success": False, "error": "The selected files exceed the 15 MB combined batch limit. Select fewer or smaller files."}), 413

        combined = []
        fetched = []
        for item in selected:
            content = _github_download(item)
            if len(content) > GITHUB_MAX_FILE_BYTES:
                return jsonify({"success": False, "error": f"{item['name']} exceeds the 5 MB per-file limit."}), 413
            text_content = content.decode("utf-8", errors="replace")
            combined.append(f"\n\n===== GITHUB FILE: {result['owner']}/{result['repo']}/{item['path']} =====\n{text_content}")
            fetched.append({"name": item["name"], "path": item["path"], "size": len(content)})

        return jsonify({
            "success": True,
            "text": "\n".join(combined),
            "files": fetched,
            "count": len(fetched),
            "repository": f"{result['owner']}/{result['repo']}",
            "branch": result["branch"],
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 429
    except requests.RequestException as exc:
        app.logger.warning("GitHub file download failed (%s)", type(exc).__name__)
        return jsonify({"success": False, "error": "Could not download one of the selected files from GitHub."}), 502


@app.route(
    "/api/history",
    methods=["GET"]
)
def history():
    """Analysis history is intentionally empty: uploads are never persisted."""
    return jsonify({"history": []})


@app.route("/api/knowledge/feedback", methods=["POST"])
def knowledge_feedback():
    """Persist only a user-confirmed reusable fix, never uploaded log text."""
    # User-confirmed learning is intentionally explicit. Deployments exposed to
    # the public internet should additionally put authentication/rate limiting
    # in front of this endpoint.
    ensure_database()
    data = request.get_json(silent=True) or {}
    error_type = str(data.get("error_type") or "").strip()[:120]
    environment = str(data.get("environment") or "General").strip()[:120]
    component = str(data.get("component") or "General").strip()[:120]
    pattern = str(data.get("pattern") or "").strip()[:180]
    description = str(data.get("description") or "").strip()[:1000]
    cause = str(data.get("cause") or "").strip()[:1500]
    fix = str(data.get("fix") or "").strip()[:3000]
    example = str(data.get("example") or "").strip()[:3000]
    confirmed = data.get("confirmed") is True
    outcome = str(data.get("outcome") or "fixed").strip().lower()
    def sanitize_knowledge(value, limit):
        value = str(value or "").strip()
        value = re.sub(r"(?i)(password|token|secret|api[_-]?key|authorization|cookie)\s*[=:]\s*[^\s,;]+", r"\1=<redacted>", value)
        value = re.sub(r"[A-Za-z]:\\[^\s]+|/(?:[^\s/]+/)+[^\s]*", "<path>", value)
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<email>", value)
        value = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", value)
        value = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)", "<phone>", value)
        value = re.sub(r"(?i)(username|user|account)\s*[=: ]+[^\s,;]+", r"\1=<redacted>", value)
        value = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<id>", value, flags=re.I)
        value = re.sub(r"(?m)^\s*at\s+[\w.$]+\([^)]*\)\s*$", "", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value[:limit]
    if "\n" in pattern or "\r" in pattern or re.search(r"(?i)\b(?:traceback|caused by:| at [\w.$]+\()", pattern):
        return jsonify({"success": False, "error": "Store a single generalized error signature, not raw log lines or stack traces."}), 400
    error_type = sanitize_knowledge(error_type, 120)
    environment = sanitize_knowledge(environment, 120)
    component = sanitize_knowledge(component, 120)
    pattern = sanitize_knowledge(pattern, 180)
    description = sanitize_knowledge(description, 1000)
    cause = sanitize_knowledge(cause, 1500)
    fix = sanitize_knowledge(fix, 3000)
    example = sanitize_knowledge(example, 3000)
    if outcome not in ("fixed", "not_fixed"):
        return jsonify({"success": False, "error": "Outcome must be fixed or not_fixed."}), 400
    if outcome == "not_fixed":
        return jsonify({"success": True, "message": "Thanks for the feedback. This fix was marked as unverified; it was not added to trusted knowledge."})
    if not all([error_type, pattern, description, cause, fix]) or not confirmed:
        return jsonify({"success": False, "error": "Confirm a successful fix and provide an error type, generalized pattern, description, cause, and fix."}), 400
    if len(pattern) < 4:
        return jsonify({"success": False, "error": "Provide a reusable, generalized error pattern."}), 400
    add_knowledge(
        error_type=error_type, environment=environment, component=component,
        pattern=pattern, description=description, cause=cause, fix=fix,
        example=example, source="user-confirmed", confidence=0.90, source_links=[]
    )
    return jsonify({"success": True, "message": "Confirmed solution saved to the reusable knowledge base."})


@app.route(
    "/api/knowledge",
    methods=["GET"]
)
def knowledge():

    ensure_database()

    try:

        return jsonify(
            get_knowledge_stats()
        )

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
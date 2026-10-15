import os
import json
import re

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
    initialize_knowledge
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


_initialized = False


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
    expected_token = os.getenv("LEARNING_WRITE_TOKEN")
    supplied_token = request.headers.get("X-Learning-Token", "")
    if not expected_token or supplied_token != expected_token:
        return jsonify({"success": False, "error": "Knowledge submission is not enabled or the write token is invalid."}), 403
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
    if not all([error_type, pattern, description, cause, fix]) or not confirmed:
        return jsonify({"success": False, "error": "A confirmed solution with error type, generalized pattern, description, cause, and fix is required."}), 400
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
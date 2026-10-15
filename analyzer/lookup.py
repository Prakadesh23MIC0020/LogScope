import re
import requests

STACK_API = "https://api.stackexchange.com/2.3/search/advanced"
GITHUB_API = "https://api.github.com/search/issues"


def clean_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def sanitize(text):
    text = clean_text(text)
    patterns = [
        (r"(?i)(password|token|secret|api[_-]?key|authorization|cookie)\s*[=:]\s*[^\s,;]+", r"\1=<redacted>"),
        (r"[A-Za-z]:\\[^\s]+|/(?:[^\s/]+/)+[^\s]*", "<path>"),
        (r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<email>"),
        (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>"),
        (r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)", "<phone>"),
        (r"(?i)(user(?:name)?|account|email)\s*[=:]\s*[^\s,;]+", r"\1=<redacted>"),
        (r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<id>"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text[:240]


def build_query(error_type, message, environment, component=None):
    # Status codes alone are deliberately insufficient research queries.
    # A bare status plus an endpoint is not a meaningful research signature.
    status_only_type = bool(re.fullmatch(r"(?i)(?:http\s*)?(?:400|404|409|422|429|500|502|503|504)(?:\s+.*)?", clean_text(error_type)))
    message_terms = re.sub(r"(?i)\b(?:http\s*)?(?:400|404|409|422|429|500|502|503|504)\b", " ", sanitize(message))
    message_terms = re.sub(r"/[^\s]+", " ", message_terms)
    message_terms = re.sub(r"\b(?:get|post|put|patch|delete|http|status|error|server|request|general)\b", " ", message_terms, flags=re.I)
    if status_only_type and len(re.findall(r"[A-Za-z]{4,}", message_terms)) < 2:
        return ""
    terms = []
    for value in (error_type, environment, component, message):
        value = sanitize(value)
        if not value or value.lower() in {"general", "unknown error"}:
            continue
        if re.fullmatch(r"(?:http\s*)?\d{3}", value, re.I):
            continue
        terms.append(value)
    query = " ".join(terms)
    return query[:240] if len(re.findall(r"[A-Za-z]{3,}", query)) >= 2 else ""


def relevance_score(title, query):
    title_terms = set(re.findall(r"[a-z][a-z0-9_.$/-]{3,}", title.lower()))
    query_terms = set(re.findall(r"[a-z][a-z0-9_.$/-]{3,}", query.lower()))
    query_terms -= {"general", "unknown", "error", "failed", "failure", "http", "server", "status", "request"}
    if not query_terms:
        return 0
    overlap = len(query_terms & title_terms)
    return overlap / max(1, min(4, len(query_terms)))


def filter_results(results, query):
    filtered = []
    seen = set()
    for item in results or []:
        title = clean_text(item.get("title"))
        url = str(item.get("url") or "")
        if not title or not url.startswith("https://"):
            continue
        score = relevance_score(title, query)
        if score < 0.25:
            continue
        if url in seen:
            continue
        seen.add(url)
        copy = dict(item)
        copy["relevance"] = round(score, 3)
        filtered.append(copy)
    filtered.sort(key=lambda item: (item["relevance"], int(item.get("score") or 0)), reverse=True)
    return filtered[:4]


def search_stackoverflow(query):
    if not query:
        return []
    try:
        response = requests.get(STACK_API, params={"order": "desc", "sort": "relevance", "q": query, "site": "stackoverflow", "pagesize": 8, "answers": 1}, timeout=5)
        if response.status_code != 200:
            return []
        results = []
        for item in response.json().get("items", []):
            title = clean_text(re.sub(r"<[^>]+>", "", item.get("title", "")))
            results.append({"title": title, "url": item.get("link", ""), "source": "Stack Overflow", "score": item.get("score", 0), "answers": item.get("answer_count", 0)})
        return filter_results(results, query)
    except Exception:
        return []


def search_github(query):
    if not query:
        return []
    # Quote the distinctive terms; do not search a bare HTTP status or issue number.
    terms = re.findall(r"[A-Za-z][A-Za-z0-9_.$/-]{3,}", query)
    terms = [term for term in terms if term.lower() not in {"general", "unknown", "error", "failed", "failure", "http", "server", "status", "request"}]
    if len(terms) < 2:
        return []
    search_query = " ".join(f'"{term}"' for term in terms[:5]) + " in:title,body"
    try:
        response = requests.get(GITHUB_API, params={"q": search_query, "sort": "reactions", "order": "desc", "per_page": 8}, headers={"Accept": "application/vnd.github+json"}, timeout=5)
        if response.status_code != 200:
            return []
        results = [{"title": clean_text(item.get("title", "")), "url": item.get("html_url", ""), "source": "GitHub", "score": item.get("score", 0), "answers": 0} for item in response.json().get("items", [])]
        return filter_results(results, query)
    except Exception:
        return []


def lookup_error(error_type, message, environment="General", raw_text="", component=None):
    # Never send complete raw logs or stack traces to external services.
    query = build_query(error_type, message, environment, component)
    results = filter_results(search_stackoverflow(query) + search_github(query), query)
    return {"query": query, "results": results}

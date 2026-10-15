"""Deterministic diagnosis rules; no generative AI service is used."""
import re

HTTP_RULES = {
    400: ("Bad Request", "The server rejected the request as malformed or invalid.", "Inspect the request syntax, required fields, parameter types, and validation errors. The status alone does not identify which field is wrong.", 0.86),
    404: ("Not Found", "The requested resource or route was not found.", "Verify the URL, route registration, resource identifier, and whether the resource exists in this environment.", 0.86),
    409: ("Conflict", "The request conflicts with the current state of the resource.", "Check for duplicate operations, optimistic-lock/version conflicts, and state-transition rules. Retry only after resolving the conflict.", 0.84),
    422: ("Unprocessable Content", "The server understood the request format but rejected its content or validation state.", "Inspect the response validation details and field-level constraints; do not assume a database schema problem from this status alone.", 0.84),
    429: ("Too Many Requests", "The client exceeded a rate limit or request quota.", "Check rate-limit headers and client retry behavior. Respect Retry-After, apply bounded backoff, and avoid retry storms.", 0.88),
    500: ("Internal Server Error", "The server encountered an unexpected condition while handling the request.", "Inspect the server-side exception and request-correlated logs. The status is a symptom, not a root cause; verify the associated stack trace before changing code or schema.", 0.82),
    502: ("Bad Gateway", "A gateway or proxy received an invalid response from an upstream service.", "Identify the upstream service and correlate gateway logs with upstream errors and timeout settings. The status alone does not prove the upstream is down.", 0.84),
    503: ("Service Unavailable", "The service is temporarily unable to handle the request, often due to overload, maintenance, or an unavailable dependency.", "Check service health, saturation, deployment/maintenance state, and dependency availability. Determine the cause from correlated evidence; do not infer it from status alone.", 0.84),
    504: ("Gateway Timeout", "A gateway or proxy did not receive a timely response from an upstream service.", "Correlate gateway and upstream logs, inspect upstream latency and timeout budgets, and confirm whether the upstream completed the operation before retrying.", 0.84),
}


def _sources(results, error_type, message, environment):
    # URLs are supporting references only, never diagnostic evidence.
    terms = set(re.findall(r"[a-z][a-z0-9_.$/-]{3,}", f"{error_type} {message} {environment}".lower()))
    generic = {"http", "error", "exception", "failed", "request", "server", "general", "java", "spring", "status", "the", "from", "with"}
    terms -= generic
    selected = []
    for item in results or []:
        title = str(item.get("title") or "")
        url = str(item.get("url") or "")
        if not title or not url.startswith("https://"):
            continue
        title_terms = set(re.findall(r"[a-z][a-z0-9_.$/-]{3,}", title.lower()))
        overlap = terms & title_terms
        if len(overlap) < 1:
            continue
        if any(x in title.lower() for x in ("job", "sports", "football", "stock", "weather")) and not overlap.intersection({"timeout", "database", "hikari", "gateway", "spring", "sql", "http"}):
            continue
        selected.append({"title": title[:250], "url": url, "source": str(item.get("source") or "External research")[:80]})
        if len(selected) == 4:
            break
    return selected


def resolve_error(error_type, message, raw_text, environment, component, research_results):
    text = "\n".join(str(v or "") for v in (error_type, message, raw_text))
    low = text.lower()
    status_match = re.search(r"(?:\bHTTP\s*|\bstatus(?:_code)?\s*[=: ]+|HTTP/\d(?:\.\d)?[\"\']?\s+)(400|404|409|422|429|500|502|503|504)\b", text, re.I)
    if status_match:
        code = int(status_match.group(1))
        title, description, fix, confidence = HTTP_RULES[code]
        sources = _sources(research_results, error_type, message, environment)
        return {"known": True, "has_fix": True, "error_type": f"HTTP {code} {title}", "environment": environment or "General", "component": component or "Web/API", "description": description, "cause": f"HTTP {code} indicates {title}; the underlying cause is not established by the status code alone.", "fix": fix, "example": "", "confidence": confidence, "classification_confidence": 0.94, "root_cause_confidence": 0.35, "sources": sources}

    if re.search(r"hikaripool|connection is not available, request timed out|connection acquisition", low):
        return {"known": True, "has_fix": True, "error_type": "Database Connection Pool Exhaustion", "environment": environment or "Java", "component": "Database", "description": "The application could not obtain a database connection from its connection pool within the configured wait time.", "cause": "Possible causes include leaked/unclosed connections, pool capacity below concurrent demand, long-running queries or transactions, or database unavailability. The log does not establish which cause applies.", "fix": "Inspect HikariCP active/idle/pending metrics and connection acquisition timeouts. Check connection lifecycle for every code path, query/transaction duration, database health, and pool sizing against database connection limits. Increase maximumPoolSize only after verifying database capacity and ruling out leaks.", "example": "", "confidence": 0.92, "classification_confidence": 0.97, "root_cause_confidence": 0.48, "sources": _sources(research_results, error_type, message, environment)}

    if re.search(r"unknown column|column .* does not exist|no such column|undefined column", low):
        return {"known": True, "has_fix": True, "error_type": error_type or "SQLException", "environment": environment or "SQL", "component": "Database", "description": "A query or mapped entity references a column the connected database reports as missing.", "cause": "Possible causes include a query/entity naming mismatch, an unapplied migration, a different schema or database being selected, or a stale deployment.", "fix": "First verify the actual connected database/schema, the failing SQL query, ORM/entity mapping, naming strategy, and migration history. Compare the expected column with the live schema and check whether the correct migration ran in this environment. Only if the column is genuinely required and absent should you prepare and review a migration; do not add a guessed column or type automatically.", "example": "", "confidence": 0.93, "classification_confidence": 0.96, "root_cause_confidence": 0.55, "sources": _sources(research_results, error_type, message, environment)}

    if re.search(r"cart\.getlastupdated|lastupdated", low) and re.search(r"nullpointerexception|cannot invoke", low):
        return {"known": True, "has_fix": True, "error_type": "NullPointerException", "environment": environment or "Java", "component": component or "Application", "description": "The code attempts to call getLastUpdated() on a null reference, or dereference a value involved in the timestamp access.", "cause": "The available message does not prove whether cart itself or a related timestamp value is null. Follow the stack-trace line and trace cart creation/loading and timestamp assignment.", "fix": "At the failing line, verify whether cart is null before calling cart.getLastUpdated(). If cart is required, handle the missing cart as a domain error rather than silently continuing. If the returned timestamp may be absent, handle that nullable value explicitly (for example, Optional/guard logic) and decide the correct business fallback; do not invent a current timestamp unless the domain rules permit it.", "example": "", "confidence": 0.88, "classification_confidence": 0.93, "root_cause_confidence": 0.58, "sources": _sources(research_results, error_type, message, environment)}

    if re.search(r"failed login|login failed|authentication failed|invalid credentials", low):
        attempts = len(re.findall(r"failed login|login failed|authentication failed|invalid credentials", low))
        return {"known": True, "has_fix": True, "error_type": "Authentication Failure", "environment": environment or "General", "component": "Authentication", "description": "One or more authentication attempts were rejected.", "cause": "Incorrect credentials, account state, or authentication configuration may explain failures. Repetition can be suspicious, but a small number of failures alone does not establish a brute-force attack.", "fix": "Review the count and time window, apply existing rate limits/lockout controls, and investigate only if the rate or distribution exceeds your normal baseline. Keep identifiers redacted in shared diagnostics and never store raw usernames or IP addresses in learned patterns.", "example": "", "confidence": 0.82, "classification_confidence": 0.94, "root_cause_confidence": 0.4, "sources": _sources(research_results, error_type, message, environment), "attempt_count": attempts}

    rules = [
        (r"nullpointerexception|nonetype.*(attribute|subscript)|object reference not set", "A null reference was dereferenced.", "Use the stack-trace location to identify and validate the exact reference, then trace where it is assigned. Check each nullable value at its source; only add a guard or fallback when the domain behavior is defined.", 0.87),
        (r"indexoutofboundsexception|indexerror|list index out of range|array index out of bounds", "Code accessed an index outside the valid collection range.", "Inspect the failing index and collection size at the stack-trace location. Correct the loop bounds or validate the index according to the intended behavior.", 0.86),
        (r"filenotfoundexception|nosuchfileexception|filenotfounderror|no such file or directory", "The requested file path does not resolve to an accessible file.", "Verify the resolved path, working directory, filename, deployment filesystem, and permissions. Create a file only if the application design requires it.", 0.82),
        (r"connection refused|actively refused|econnrefused", "The target host rejected the connection because no service accepted it at that address and port.", "Verify the service is running, the host/port are correct, and the target is reachable from the application runtime.", 0.84),
        (r"timed out|timeout|read timed out|connect timed out", "An operation did not complete within its configured time limit.", "Identify which operation timed out and correlate client and server logs. Check service health, latency, and timeout budgets; use bounded retries only when repeating the operation is safe.", 0.78),
        (r"permission denied|access is denied|accessdeniedexception", "The process lacks permission for a resource or operation.", "Check the runtime identity, required role, and resource permissions. Grant only the minimum access required.", 0.82),
        (r"modulenotfounderror|no module named|classnotfoundexception|noclassdeffounderror", "A required module or class is unavailable in the runtime environment.", "Verify the dependency declaration, installed environment, package/import name, runtime compatibility, and deployment build logs.", 0.81),
        (r"outofmemoryerror|out of memory|memoryerror|cannot allocate memory", "The process could not allocate the memory required to continue.", "Inspect memory growth and workload size, release retained resources, and profile for leaks before increasing memory limits.", 0.82),
        (r"authentication failed|authentication failure|invalid credentials|password authentication failed", "Authentication was rejected by the target service.", "Verify the secret source, authentication method, account state, and target environment. Never print credentials into logs.", 0.80),
        (r"numberformatexception|invalid literal for int|could not convert string to float", "A value could not be parsed into the expected numeric type.", "Validate and normalize the input before conversion and handle missing or malformed values explicitly.", 0.80),
        (r"stackoverflowerror|maximum recursion depth exceeded|recursionerror", "Recursive execution exceeded the runtime limit or failed to reach a base case.", "Check the base case and whether each recursive call progresses toward it; consider iteration for deeply nested input.", 0.80),
    ]
    for pattern, description, fix, confidence in rules:
        if re.search(pattern, text, re.I):
            return {"known": True, "has_fix": True, "error_type": error_type, "environment": environment or "General", "component": component or "General", "description": description, "cause": "This classification follows the observed exception/message; the precise underlying cause still depends on the surrounding code and runtime context.", "fix": fix, "example": "", "confidence": confidence, "classification_confidence": confidence, "root_cause_confidence": 0.45, "sources": _sources(research_results, error_type, message, environment)}
    return None

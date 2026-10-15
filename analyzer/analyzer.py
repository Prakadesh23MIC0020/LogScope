from collections import Counter
import re
import hashlib
from datetime import datetime


def normalize_message(message):
    message = str(message or "").lower()
    message = re.sub(r"(?i)(password|token|secret|api[_-]?key)\s*[=:]\s*[^\s,;]+", r"\1=<redacted>", message)
    message = re.sub(r"[A-Za-z]:\\[^\s]+|/(?:[^\s/]+/)+[^\s]*", "<path>", message)
    message = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<email>", message)
    message = re.sub(r"(?i)(failed login attempt for user|login failed for user|username|user)\s*[:= ]+[^\s,;]+", r"\1=<redacted>", message)
    message = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", message)
    message = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)", "<phone>", message)
    message = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<id>", message, flags=re.I)
    return re.sub(r"\s+", " ", message).strip()


def group_errors(errors):
    groups = {}
    for error in errors:
        normalized = normalize_message(error.get("message", ""))
        key = (error.get("type", "Unknown Error"), normalized)
        raw = str(error.get("raw", ""))
        if re.search(r"failed login|login failed|authentication failed|invalid credentials", raw, re.I):
            identifier = re.search(r"(?i)(?:user(?:name)?|account|ip)\s*[:= ]+([^\s,;]+)", raw)
            identifier_hash = hashlib.sha256(identifier.group(1).lower().encode("utf-8")).hexdigest()[:10] if identifier else "unknown"
            timestamp = re.search(r"(20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", raw)
            bucket = "unknown-window"
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.group(1).replace(" ", "T"))
                    bucket = dt.strftime("%Y-%m-%d-%H-") + str(dt.minute // 10)
                except ValueError:
                    pass
            key = (key[0], key[1], identifier_hash, bucket)
        if key not in groups:
            item = error.copy()
            item["occurrences"] = max(1, int(error.get("occurrences", 1) or 1))
            item["signature"] = key[0] + ": " + key[1]
            groups[key] = item
        else:
            groups[key]["occurrences"] += max(1, int(error.get("occurrences", 1) or 1))
            groups[key]["severity"] = max_severity(groups[key].get("severity"), error.get("severity"))
    result = list(groups.values())
    for index, error in enumerate(result, start=1):
        error["id"] = index
    return result


def max_severity(a, b):
    order = {"Warning": 0, "Error": 1, "Critical": 2}
    return a if order.get(a, 1) >= order.get(b, 1) else b


def _event_time(error):
    raw = str(error.get("raw", ""))
    match = re.search(r"(20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", raw)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1).replace(" ", "T"))
    except ValueError:
        return None


def _close_events(first, second, seconds=30):
    a = _event_time(first)
    b = _event_time(second)
    if a is None or b is None:
        # Without timestamps, require an explicit shared endpoint/request context.
        x = (str(first.get("raw", "")) + " " + str(first.get("message", ""))).lower()
        y = (str(second.get("raw", "")) + " " + str(second.get("message", ""))).lower()
        endpoints = re.findall(r"/api/[a-z0-9_/-]+", x)
        return any(endpoint in y for endpoint in endpoints)
    return abs((a - b).total_seconds()) <= seconds


def correlate_events(errors):
    for error in errors:
        error["event_group"] = error.get("id")
        error["is_downstream_symptom"] = False
        error["correlation_reason"] = ""

    for i, root in enumerate(errors):
        root_text = (str(root.get("raw", "")) + " " + str(root.get("message", ""))).lower()
        for symptom in errors:
            if root is symptom or not _close_events(root, symptom):
                continue
            symptom_text = (str(symptom.get("raw", "")) + " " + str(symptom.get("message", ""))).lower()

            if ("unknown column" in root_text or ("column" in root_text and "does not exist" in root_text)) and re.search(r"(?:\bHTTP\s*500\b|HTTP/\d(?:\.\d)?[\"\']?\s+500\b|status(?:_code)?[=: ]+500\b)", symptom_text, re.I):
                shared = any(x in root_text + " " + symptom_text for x in ("/api/orders", "ordercontroller", "orderservice", "order endpoint"))
                if shared:
                    root["event_group"] = "orders-schema-failure"
                    symptom["event_group"] = "orders-schema-failure"
                    symptom["is_downstream_symptom"] = True
                    symptom["correlation_reason"] = "HTTP 500 is correlated with the nearby missing-column failure in the order request."

            if any(k in root_text for k in ("payment gateway", "gateway timeout", "read timed out", "connect timed out")) and re.search(r"(?:\bHTTP\s*502\b|HTTP/\d(?:\.\d)?[\"\']?\s+502\b|status(?:_code)?[=: ]+502\b)", symptom_text, re.I):
                shared = "checkout" in root_text + " " + symptom_text or "/api/checkout" in root_text + " " + symptom_text
                if shared:
                    root["event_group"] = "checkout-gateway-failure"
                    symptom["event_group"] = "checkout-gateway-failure"
                    symptom["is_downstream_symptom"] = True
                    symptom["correlation_reason"] = "HTTP 502 is correlated with the nearby payment-gateway timeout in checkout."

            if any(k in root_text for k in ("hikaripool", "connection is not available", "connection acquisition")) and re.search(r"(?:\bHTTP\s*503\b|HTTP/\d(?:\.\d)?[\"\']?\s+503\b|status(?:_code)?[=: ]+503\b)", symptom_text, re.I):
                root["event_group"] = "database-pool-unavailable"
                symptom["event_group"] = "database-pool-unavailable"
                symptom["is_downstream_symptom"] = True
                symptom["correlation_reason"] = "HTTP 503 is correlated with the nearby database connection acquisition failure."

    for error in errors:
        text = (str(error.get("raw", "")) + " " + str(error.get("message", ""))).lower()
        if re.search(r"failed login|login failed|authentication failed|invalid credentials", text):
            error["authentication_pattern"] = True
            error["potentially_suspicious"] = int(error.get("occurrences", 1) or 1) >= 5
            error["suspicion_note"] = "Repeated failures merit review; this pattern alone does not prove a brute-force attack." if error["potentially_suspicious"] else "Authentication failure observed; insufficient evidence alone to label an attack."
    return errors


def get_statistics(errors, total_lines):
    countable = [e for e in errors if not e.get("is_downstream_symptom")]
    total_errors = sum(int(e.get("occurrences", 1) or 1) for e in countable if e.get("severity") in ("Error", "Critical"))
    critical = sum(int(e.get("occurrences", 1) or 1) for e in countable if e.get("severity") == "Critical")
    warnings = sum(int(e.get("occurrences", 1) or 1) for e in countable if e.get("severity") == "Warning")
    severity = Counter()
    types = Counter()
    for error in countable:
        weight = max(1, int(error.get("occurrences", 1) or 1))
        severity[error.get("severity", "Error")] += weight
        types[error.get("type", "Unknown Error")] += weight
    return {"total_lines": int(total_lines), "total_errors": total_errors, "critical": critical, "warnings": warnings, "unique_errors": len(errors), "types": dict(types), "severity": dict(severity), "counting_definition": {"total_lines": "All input lines, including continuation and non-error lines.", "total_errors": "Occurrences of grouped Error and Critical entries, excluding correlated downstream symptoms.", "critical": "Critical-severity occurrences among countable entries; exception presence alone is not critical.", "unique_errors": "Distinct normalized (error type, message signature) groups; correlated symptoms remain visible but are excluded from total_errors and critical counts."}}

def calculate_severity(text, detected_type=None):
    s = str(text or "").lower()
    if any(word in s for word in ("fatal", "critical", "kernel panic", "segmentation fault", "database corruption", "outofmemoryerror")):
        return "Critical"
    if any(word in s for word in ("warning", "warn", "deprecated", "can't keep up", "running behind")):
        return "Warning"
    if re_status_critical(s):
        return "Critical"
    return "Error"


def re_status_critical(text):
    import re
    return bool(re.search(r"\b(?:HTTP\s*)?5(?:00|02|03|04)\b", text) and any(x in text for x in ("fatal", "critical", "outage", "unavailable for all", "database corruption")))

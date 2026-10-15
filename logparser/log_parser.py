import re

from logparser.error_detector import (
    contains_error_word,
    detect_exception,
    detect_special_error
)

from logparser.stacktrace import (
    is_stack_trace_line,
    extract_java_location,
    extract_python_location
)

from analyzer.severity import calculate_severity


def looks_like_new_log_entry(line):

    patterns = [
        r"^\[?\d{4}-\d{2}-\d{2}",
        r"^\[\d{2}:\d{2}:\d{2}",
        r"^\d{2}:\d{2}:\d{2}",
        r"^\w+\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}",
        r"^\[[A-Z]+\]",
        r"^\d{4}-\d{2}-\d{2}T"
    ]

    return any(
        re.search(
            pattern,
            line
        )
        for pattern in patterns
    )


def find_error_type(lines):

    full_text = "\n".join(lines)

    for line in lines:

        exception = detect_exception(
            line
        )

        if exception:
            return exception

    for line in lines:

        if re.search(r"HikariPool|Connection is not available, request timed out|connection acquisition", line, re.I):
            return "Database Connection Pool Exhaustion"

    for line in lines:

        special = detect_special_error(
            line
        )

        if special:
            return special

    if re.search(
        r"\b(sql|sqlstate|database|query|mysql)\b",
        full_text,
        re.IGNORECASE
    ):
        return "SQLException"

    return "Unknown Error"


def extract_message(lines):

    for line in lines:

        stripped = line.strip()

        if not stripped:
            continue

        stripped = re.sub(r"^\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\]?\s*", "", stripped)
        stripped = re.sub(r"^\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*", "", stripped)
        stripped = re.sub(r"^(?:TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL|SEVERE)\s*[-:]?\s*", "", stripped, flags=re.I)

        if "Traceback" in stripped:
            continue

        if re.match(
            r"^\s*at\s+",
            stripped
        ):
            continue

        if stripped.startswith(
            "Caused by:"
        ):
            return stripped

        exception = detect_exception(
            stripped
        )

        if exception:
            return stripped

        if ":" in stripped:

            parts = stripped.split(
                ":",
                1
            )

            right = parts[1].strip()

            if right:
                return right

        return stripped

    return ""


def extract_location(lines):

    for line in lines:

        location = extract_java_location(
            line
        )

        if location:
            return location

        location = extract_python_location(
            line
        )

        if location:
            return location

    return {
        "file": None,
        "line": None
    }


def should_start_error(line):

    return (
        contains_error_word(line)
        or detect_special_error(line) is not None
        or "Traceback (most recent call last)" in line
    )


def is_exception_continuation(line):

    stripped = line.strip()

    if not stripped:
        return True

    if is_stack_trace_line(line):
        return True

    if detect_exception(line):
        return True

    if stripped.startswith(
        "Caused by:"
    ):
        return True

    if stripped.startswith(
        "Suppressed:"
    ):
        return True

    if stripped.startswith(
        "..."
    ):
        return True

    if line.startswith(" "):
        return True

    if line.startswith("\t"):
        return True

    return False


def looks_like_related_error(line):

    stripped = line.strip().lower()

    patterns = [
        "failed to",
        "exception while",
        "error while",
        "unable to",
        "could not",
        "cannot",
        "request processing failed",
        "operation failed",
        "task failed"
    ]

    return any(
        pattern in stripped
        for pattern in patterns
    )


def parse_log(text):

    lines = text.splitlines()

    errors = []

    current = []
    has_exception = False
    stacktrace_seen = False

    for line in lines:

        if current:

            if is_exception_continuation(
                line
            ):

                current.append(line)

                if detect_exception(line):
                    has_exception = True

                if is_stack_trace_line(line):
                    stacktrace_seen = True

                continue

            if (
                has_exception
                and stacktrace_seen
                and looks_like_related_error(line)
            ):

                current.append(line)
                continue

            if looks_like_new_log_entry(
                line
            ):

                errors.append(
                    current
                )

                current = []
                has_exception = False
                stacktrace_seen = False

            else:

                current.append(line)
                continue

        if should_start_error(line):

            current = [line]

            if detect_exception(line):
                has_exception = True

            if is_stack_trace_line(line):
                stacktrace_seen = True

    if current:
        errors.append(current)

    results = []

    for index, block in enumerate(
        errors,
        start=1
    ):

        error_type = find_error_type(
            block
        )

        raw = "\n".join(
            block
        )

        severity = calculate_severity(
            raw,
            error_type
        )

        location = extract_location(
            block
        )

        results.append({
            "id": index,
            "type": error_type,
            "severity": severity,
            "message": extract_message(block),
            "file": location["file"],
            "line": location["line"],
            "occurrences": 1,
            "raw": raw,
            "lines": block
        })

    return results
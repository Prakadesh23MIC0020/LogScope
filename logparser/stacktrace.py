import re


JAVA_LOCATION = re.compile(
    r"\bat\s+[\w.$]+\(([^:()]+):(\d+)\)"
)


PYTHON_LOCATION = re.compile(
    r'File\s+"([^"]+)",\s+line\s+(\d+)'
)


def is_stack_trace_line(line):

    stripped = line.strip()

    if re.match(
        r"^at\s+",
        stripped
    ):
        return True

    if re.match(
        r"^\.\.\.\s+\d+\s+more",
        stripped
    ):
        return True

    if stripped.startswith(
        "Caused by:"
    ):
        return True

    if stripped.startswith(
        "Suppressed:"
    ):
        return True

    if re.search(
        r'File\s+".+",\s+line\s+\d+',
        stripped
    ):
        return True

    return False


def extract_java_location(line):

    match = JAVA_LOCATION.search(
        line
    )

    if not match:
        return None

    return {
        "file": match.group(1),
        "line": int(match.group(2))
    }


def extract_python_location(line):

    match = PYTHON_LOCATION.search(
        line
    )

    if not match:
        return None

    return {
        "file": match.group(1),
        "line": int(match.group(2))
    }
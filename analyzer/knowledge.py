import json
import os

from database.db import (
    add_knowledge,
    find_knowledge,
    knowledge_exists
)


BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

PATTERN_FILE = os.path.join(
    BASE_DIR,
    "data",
    "error_patterns.json"
)


def load_builtin_rules():

    with open(
        PATTERN_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def initialize_knowledge():

    rules = load_builtin_rules()

    for error_type, data in rules.items():

        environment = data.get(
            "environment",
            "General"
        )

        pattern = data.get(
            "pattern",
            error_type
        )

        if knowledge_exists(
            error_type,
            environment,
            pattern
        ):
            continue

        add_knowledge(
            error_type=error_type,
            environment=environment,
            component=data.get(
                "component",
                ""
            ),
            pattern=pattern,
            description=data.get(
                "description",
                ""
            ),
            cause=data.get(
                "cause",
                ""
            ),
            fix=data.get(
                "fix",
                ""
            ),
            example=data.get(
                "example"
            ),
            source="built-in",
            confidence=1.0
        )


def lookup_knowledge(
    error_type,
    message,
    environment=None
):

    return find_knowledge(
        error_type,
        message,
        environment
    )
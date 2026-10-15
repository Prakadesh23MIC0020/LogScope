import json
import os


BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

TEMPLATE_FILE = os.path.join(
    BASE_DIR,
    "data",
    "environment_templates.json"
)


def load_templates():

    with open(
        TEMPLATE_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def detect_environment(text):

    text = text or ""
    s = text.lower()

    templates = load_templates()

    scores = {}

    for environment, data in templates.items():

        score = 0

        for indicator in data.get(
            "indicators",
            []
        ):

            if indicator.lower() in s:
                score += 1

        if score:
            scores[environment] = score

    if not scores:
        return ["General"]

    ordered = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    return [
        name
        for name, score
        in ordered
    ]


def detect_primary_environment(text):

    environments = detect_environment(
        text
    )

    return (
        environments[0]
        if environments
        else "General"
    )


def detect_component(
    text,
    environment
):

    templates = load_templates()

    data = templates.get(
        environment
    )

    if not data:
        return "General"

    s = text.lower()

    scores = {}

    for component, indicators in data.get(
        "components",
        {}
    ).items():

        score = 0

        for indicator in indicators:

            if indicator.lower() in s:
                score += 1

        if score:
            scores[component] = score

    if not scores:
        return "General"

    return max(
        scores,
        key=scores.get
    )
from analyzer.sql_fixer import (
    analyze_sql_error
)

from analyzer.knowledge import (
    lookup_knowledge
)

from analyzer.environment_detector import (
    detect_component
)


def get_explanation(
    error_type,
    raw_text="",
    environment=None
):

    environments = environment or [
        "General"
    ]

    if isinstance(
        environments,
        str
    ):
        environments = [
            environments
        ]

    primary = environments[0]

    sql_result = analyze_sql_error(
        raw_text
    )

    if sql_result:

        return {
            "category": "SQL",
            "component": "Database",
            "description":
                sql_result["description"],
            "cause": "",
            "fix":
                sql_result["fix"],
            "code":
                sql_result["code"],
            "source": "SQL Rule",
            "confidence": 1.0,
            "times_seen": 0,
            "source_links": []
        }

    component = detect_component(
        raw_text,
        primary
    )

    for env in environments:

        knowledge = lookup_knowledge(
            error_type,
            raw_text,
            env
        )

        if knowledge:

            return {
                "category":
                    knowledge.get(
                        "environment",
                        env
                    ),

                "component":
                    knowledge.get(
                        "component",
                        component
                    ),

                "description":
                    knowledge.get(
                        "description",
                        ""
                    ),

                "cause":
                    knowledge.get(
                        "cause",
                        ""
                    ),

                "fix":
                    knowledge.get(
                        "fix",
                        ""
                    ),

                "code":
                    knowledge.get(
                        "example"
                    ),

                "source":
                    knowledge.get(
                        "source",
                        "Knowledge Base"
                    ),

                "confidence":
                    float(
                        knowledge.get(
                            "confidence",
                            0
                        )
                    ),

                "times_seen":
                    knowledge.get(
                        "times_seen",
                        0
                    ),

                "source_links":
                    knowledge.get(
                        "source_links",
                        []
                    )
            }

    return None
import json
import pandas as pd


def errors_to_dataframe(errors):

    data = []

    for error in errors:

        line = error.get(
            "line"
        )

        if line is None:
            line = "-"

        else:
            line = str(line)

        data.append({

            "ID":
                str(
                    error.get(
                        "id",
                        ""
                    )
                ),

            "Type":
                str(
                    error.get(
                        "type",
                        ""
                    )
                ),

            "Severity":
                str(
                    error.get(
                        "severity",
                        ""
                    )
                ),

            "Message":
                str(
                    error.get(
                        "message",
                        ""
                    )
                ),

            "File":
                str(
                    error.get(
                        "file"
                    )
                    or "-"
                ),

            "Line":
                line,

            "Occurrences":
                str(
                    error.get(
                        "occurrences",
                        1
                    )
                )
        })

    return pd.DataFrame(
        data
    )


def errors_to_csv(errors):

    df = errors_to_dataframe(
        errors
    )

    return df.to_csv(
        index=False
    ).encode(
        "utf-8"
    )


def errors_to_json(errors):

    return json.dumps(
        errors,
        indent=4,
        default=str
    ).encode(
        "utf-8"
    )
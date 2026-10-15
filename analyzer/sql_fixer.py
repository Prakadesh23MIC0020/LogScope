import re


def analyze_sql_error(text):

    s = str(
        text or ""
    ).lower()

    indicators = [
        "sql",
        "sqlstate",
        "mysql",
        "postgres",
        "postgresql",
        "sqlite",
        "database",
        "jdbc",
        "query",
        "table",
        "column",
        "foreign key",
        "duplicate entry"
    ]

    if not any(
        word in s
        for word in indicators
    ):
        return None

    if (
        "doesn't exist" in s
        or "does not exist" in s
        or "1146" in s
    ):

        match = re.search(
            r"table\s+['\"]?([^'\"\s]+)",
            text,
            re.IGNORECASE
        )

        table = (
            match.group(1)
            if match
            else "your_table"
        )

        return {
            "description":
                f"The table '{table}' does not exist.",

            "fix":
                "Create the missing table or verify the table name and database schema.",

            "code":
                f"CREATE TABLE {table} (\n"
                f"    id INT PRIMARY KEY AUTO_INCREMENT\n"
                f");"
        }

    if (
        "unknown column" in s
        or "1054" in s
        or "column" in s and "does not exist" in s
        or "no such column" in s
    ):
        match = re.search(
            r"(?:unknown column|no such column)\s+['\"]?([^'\"\s]+)",
            text,
            re.IGNORECASE
        )
        column = match.group(1) if match else "the referenced column"
        return {
            "description": f"The query or mapped entity references a column ({column}) that the connected database reports as missing.",
            "fix": "Verify the connected database/schema, the failing query, ORM/entity mapping, naming strategy, and migration history first. Compare the live schema with the expected schema and confirm the correct migration ran in this environment. Only prepare a reviewed schema migration if the column is genuinely required and absent.",
            "code": None
        }

    if (
        "duplicate entry" in s
        or "1062" in s
    ):

        return {
            "description":
                "A unique field already contains this value.",

            "fix":
                "Use a different value or update the existing record.",

            "code": None
        }

    if (
        "access denied for user" in s
        or "1045" in s
    ):

        return {
            "description":
                "The database rejected the supplied credentials.",

            "fix":
                "Check the database username, password and permissions.",

            "code": None
        }

    if (
        "can't connect to mysql server" in s
        or "cannot connect to mysql server" in s
        or "2003" in s
    ):

        return {
            "description":
                "The application cannot reach the MySQL server.",

            "fix":
                "Verify that MySQL is running and that the configured host and port are correct.",

            "code": None
        }

    if (
        "syntax error" in s
        or "you have an error in your sql syntax" in s
        or "1064" in s
    ):

        return {
            "description":
                "The SQL statement contains invalid syntax.",

            "fix":
                "Check the SQL statement near the reported position.",

            "code": None
        }

    if (
        "foreign key constraint" in s
        or "1451" in s
        or "1452" in s
    ):

        return {
            "description":
                "The operation violates a foreign-key relationship.",

            "fix":
                "Make sure the referenced record exists and that the foreign-key values are valid.",

            "code": None
        }

    return None
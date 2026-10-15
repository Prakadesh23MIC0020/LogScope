import os
import json

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is not configured."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10
    )


def init_db():
    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analyses (
                    id BIGSERIAL PRIMARY KEY,
                    source_name TEXT,
                    total_lines INTEGER,
                    total_errors INTEGER,
                    critical INTEGER,
                    warnings INTEGER,
                    unique_errors INTEGER,
                    results JSONB,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id BIGSERIAL PRIMARY KEY,
                    error_type TEXT NOT NULL,
                    environment TEXT,
                    component TEXT,
                    pattern TEXT,
                    description TEXT,
                    cause TEXT,
                    fix TEXT,
                    example TEXT,
                    source TEXT,
                    confidence DOUBLE PRECISION DEFAULT 0,
                    source_url TEXT,
                    source_title TEXT,
                    source_links JSONB DEFAULT '[]'::jsonb,
                    times_seen INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_knowledge_error
                ON knowledge(error_type)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_knowledge_environment
                ON knowledge(environment)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_knowledge_pattern
                ON knowledge(pattern)
            """)

        conn.commit()

    finally:
        conn.close()


def get_history(limit=50):
    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                SELECT
                    id,
                    source_name,
                    total_lines,
                    total_errors,
                    critical,
                    warnings,
                    unique_errors,
                    created_at
                FROM analyses
                ORDER BY id DESC
                LIMIT %s
            """, (limit,))

            return cursor.fetchall()

    finally:
        conn.close()


def knowledge_exists(
    error_type,
    environment,
    pattern
):
    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                SELECT id
                FROM knowledge
                WHERE lower(error_type)
                    = lower(%s)
                AND lower(coalesce(environment, ''))
                    = lower(%s)
                AND lower(coalesce(pattern, ''))
                    = lower(%s)
                LIMIT 1
            """, (
                error_type,
                environment or "",
                pattern or ""
            ))

            return cursor.fetchone() is not None

    finally:
        conn.close()


def find_knowledge(
    error_type,
    message,
    environment=None
):
    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                SELECT *
                FROM knowledge
                WHERE lower(error_type)
                    = lower(%s)
                ORDER BY
                    confidence DESC,
                    times_seen DESC
            """, (error_type,))

            rows = cursor.fetchall()

    finally:
        conn.close()

    if not rows:
        return None

    message_text = str(
        message or ""
    ).strip().lower()

    environment_text = str(
        environment or ""
    ).strip().lower()

    best = None
    best_score = 0

    for row in rows:

        score = 0

        row_environment = str(
            row.get("environment") or ""
        ).lower()

        row_pattern = str(
            row.get("pattern") or ""
        ).lower()

        if (
            environment_text
            and row_environment
        ):

            if environment_text in row_environment:
                score += 30

            elif row_environment in environment_text:
                score += 20

        if row_pattern:

            if row_pattern in message_text:
                score += 50

            for word in row_pattern.split():

                if (
                    len(word) > 3
                    and word in message_text
                ):
                    score += 3

        score += (
            float(
                row.get("confidence") or 0
            ) * 10
        )

        score += min(
            int(
                row.get("times_seen") or 0
            ),
            10
        )

        if score > best_score:
            best_score = score
            best = dict(row)

    if best is None or best_score < 15:
        return None

    return best


def add_knowledge(
    error_type,
    environment,
    component,
    pattern,
    description,
    cause,
    fix,
    example=None,
    source="built-in",
    confidence=1.0,
    source_url=None,
    source_title=None,
    source_links=None
):
    conn = get_connection()

    try:
        if source_links is None:
            source_links = []

        with conn.cursor() as cursor:

            cursor.execute("""
                SELECT id, confidence, times_seen
                FROM knowledge
                WHERE lower(error_type)
                    = lower(%s)
                AND lower(coalesce(environment, ''))
                    = lower(%s)
                AND lower(coalesce(pattern, ''))
                    = lower(%s)
                LIMIT 1
            """, (
                error_type,
                environment or "",
                pattern or ""
            ))

            existing = cursor.fetchone()

            if existing:

                old_confidence = float(
                    existing.get(
                        "confidence"
                    ) or 0
                )

                new_confidence = float(
                    confidence or 0
                )

                merged_confidence = max(
                    old_confidence,
                    new_confidence
                )

                cursor.execute("""
                    UPDATE knowledge
                    SET
                        component = %s,
                        description = %s,
                        cause = %s,
                        fix = %s,
                        example = %s,
                        source = %s,
                        confidence = %s,
                        source_url = %s,
                        source_title = %s,
                        source_links = %s::jsonb,
                        times_seen =
                            times_seen + 1,
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    component,
                    description,
                    cause,
                    fix,
                    example,
                    source,
                    merged_confidence,
                    source_url,
                    source_title,
                    json.dumps(source_links),
                    existing["id"]
                ))

                knowledge_id = existing["id"]

            else:

                cursor.execute("""
                    INSERT INTO knowledge (
                        error_type,
                        environment,
                        component,
                        pattern,
                        description,
                        cause,
                        fix,
                        example,
                        source,
                        confidence,
                        source_url,
                        source_title,
                        source_links,
                        times_seen
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s::jsonb, 1
                    )
                    RETURNING id
                """, (
                    error_type,
                    environment,
                    component,
                    pattern,
                    description,
                    cause,
                    fix,
                    example,
                    source,
                    confidence,
                    source_url,
                    source_title,
                    json.dumps(source_links)
                ))

                knowledge_id = cursor.fetchone()["id"]

        conn.commit()

        return knowledge_id

    finally:
        conn.close()


def get_knowledge_stats():
    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM knowledge
            """)

            total = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM knowledge
                WHERE source IN ('ai-researched', 'rule-researched', 'user-confirmed')
            """)

            learned = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM knowledge
                WHERE source = 'built-in'
            """)

            builtin = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT AVG(confidence) AS average
                FROM knowledge
            """)

            average = cursor.fetchone()["average"]

            return {
                "total": total,
                "learned": learned,
                "built_in": builtin,
                "average_confidence":
                    float(average or 0)
            }

    finally:
        conn.close()
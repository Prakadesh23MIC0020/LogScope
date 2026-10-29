import os
import json
import re

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

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS community_fixes (
                    id BIGSERIAL PRIMARY KEY,
                    error_type TEXT NOT NULL,
                    environment TEXT,
                    component TEXT,
                    pattern TEXT NOT NULL,
                    description TEXT NOT NULL,
                    cause TEXT NOT NULL,
                    fix TEXT NOT NULL,
                    example TEXT,
                    status TEXT NOT NULL DEFAULT 'community',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_community_fixes_error
                ON community_fixes(error_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_community_fixes_pattern
                ON community_fixes(pattern)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fix_votes (
                    id BIGSERIAL PRIMARY KEY,
                    target_type TEXT NOT NULL CHECK (target_type IN ('rule', 'community')),
                    target_key TEXT NOT NULL,
                    voter_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(target_type, target_key, voter_hash)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_fix_votes_target
                ON fix_votes(target_type, target_key)
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
                SELECT id, confidence, times_seen, source
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

            if existing and existing.get("source") == "built-in" and source == "user-confirmed":
                # Keep built-in rule content authoritative; the submitted solution
                # is still available as a separate anonymous community fix.
                conn.commit()
                return existing["id"]

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

def add_community_fix(error_type, environment, component, pattern, description, cause, fix, example=None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id FROM community_fixes
                WHERE lower(error_type)=lower(%s)
                  AND lower(coalesce(environment,''))=lower(%s)
                  AND lower(pattern)=lower(%s)
                  AND lower(fix)=lower(%s)
                ORDER BY id ASC LIMIT 1
            """, (error_type, environment or "", pattern, fix))
            existing = cursor.fetchone()
            if existing:
                return existing["id"]
            cursor.execute("""
                INSERT INTO community_fixes
                    (error_type, environment, component, pattern, description, cause, fix, example)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (error_type, environment, component, pattern, description, cause, fix, example))
            fix_id = cursor.fetchone()["id"]
        conn.commit()
        return fix_id
    finally:
        conn.close()


def find_community_fixes(error_type, message, environment=None, voter_hash=None, limit=8):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT f.*, COUNT(v.id)::INTEGER AS upvotes
                FROM community_fixes f
                LEFT JOIN fix_votes v
                  ON v.target_type = 'community' AND v.target_key = f.id::text
                WHERE lower(f.error_type) = lower(%s)
                GROUP BY f.id
                ORDER BY COUNT(v.id) DESC, f.created_at DESC
                LIMIT 100
            """, (error_type,))
            rows = cursor.fetchall()
            message_words = set(re.sub(r"[^a-z0-9]+", " ", str(message or "").lower()).split())
            env = str(environment or "").lower()
            matched = []
            for row in rows:
                pattern_words = set(re.sub(r"[^a-z0-9]+", " ", str(row.get("pattern") or "").lower()).split())
                useful_words = {w for w in pattern_words if len(w) > 3}
                overlap = len(useful_words & message_words)
                denominator = max(1, len(useful_words))
                exact = str(row.get("pattern") or "").lower() in str(message or "").lower()
                env_match = not env or not row.get("environment") or env in str(row.get("environment")).lower() or str(row.get("environment")).lower() in env
                if not (exact or (overlap >= 2 and overlap / denominator >= 0.5)) or not env_match:
                    continue
                row["confidence"] = _vote_confidence(0.45, row["upvotes"])
                row["user_voted"] = False
                if voter_hash:
                    cursor.execute("""
                        SELECT 1 FROM fix_votes
                        WHERE target_type='community' AND target_key=%s AND voter_hash=%s
                    """, (str(row["id"]), voter_hash))
                    row["user_voted"] = cursor.fetchone() is not None
                matched.append(dict(row))
            return matched[:limit]
    finally:
        conn.close()


def _vote_confidence(base, upvotes):
    # Votes raise confidence gradually, with diminishing returns.
    return round(min(0.99, max(0.0, float(base or 0) + min(int(upvotes or 0), 20) * 0.025)), 4)


def get_vote_summary(target_type, target_key, voter_hash=None, base_confidence=0.5):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*)::INTEGER AS upvotes
                FROM fix_votes
                WHERE target_type=%s AND target_key=%s
            """, (target_type, str(target_key)))
            upvotes = cursor.fetchone()["upvotes"]
            voted = False
            if voter_hash:
                cursor.execute("""
                    SELECT 1 FROM fix_votes
                    WHERE target_type=%s AND target_key=%s AND voter_hash=%s
                """, (target_type, str(target_key), voter_hash))
                voted = cursor.fetchone() is not None
            return {"upvotes": upvotes, "user_voted": voted,
                    "confidence": _vote_confidence(base_confidence, upvotes)}
    finally:
        conn.close()


def add_fix_vote(target_type, target_key, voter_hash):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO fix_votes (target_type, target_key, voter_hash)
                VALUES (%s, %s, %s)
                ON CONFLICT (target_type, target_key, voter_hash) DO NOTHING
                RETURNING id
            """, (target_type, str(target_key), voter_hash))
            inserted = cursor.fetchone() is not None
            cursor.execute("""
                SELECT COUNT(*)::INTEGER AS upvotes FROM fix_votes
                WHERE target_type=%s AND target_key=%s
            """, (target_type, str(target_key)))
            upvotes = cursor.fetchone()["upvotes"]
        conn.commit()
        return {"inserted": inserted, "upvotes": upvotes}
    finally:
        conn.close()


def get_community_stats():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*)::INTEGER AS total FROM community_fixes")
            total = cursor.fetchone()["total"]
            cursor.execute("SELECT COUNT(*)::INTEGER AS total FROM fix_votes WHERE target_type='community'")
            votes = cursor.fetchone()["total"]
            cursor.execute("SELECT COUNT(*)::INTEGER AS total FROM fix_votes WHERE target_type='rule'")
            rule_votes = cursor.fetchone()["total"]
            cursor.execute("""
                SELECT AVG(LEAST(0.99, 0.45 + LEAST(vote_count, 20) * 0.025)) AS average
                FROM (
                    SELECT f.id, COUNT(v.id)::INTEGER AS vote_count
                    FROM community_fixes f
                    LEFT JOIN fix_votes v ON v.target_type='community' AND v.target_key=f.id::text
                    GROUP BY f.id
                ) scored
            """)
            average = cursor.fetchone()["average"]
            return {
                "community_fixes": total,
                "community_votes": votes,
                "rule_votes": rule_votes,
                "community_average_confidence": float(average or 0)
            }
    finally:
        conn.close()


def community_fix_exists(fix_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM community_fixes WHERE id=%s", (fix_id,))
            return cursor.fetchone() is not None
    finally:
        conn.close()


def list_community_fixes(voter_hash=None, limit=30):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT f.*, COUNT(v.id)::INTEGER AS upvotes
                FROM community_fixes f
                LEFT JOIN fix_votes v
                  ON v.target_type='community' AND v.target_key=f.id::text
                GROUP BY f.id
                ORDER BY COUNT(v.id) DESC, f.created_at DESC
                LIMIT %s
            """, (max(1, min(int(limit), 100)),))
            rows = cursor.fetchall()
            result = []
            for row in rows:
                row["confidence"] = _vote_confidence(0.45, row["upvotes"])
                row["user_voted"] = False
                if voter_hash:
                    cursor.execute("""
                        SELECT 1 FROM fix_votes
                        WHERE target_type='community' AND target_key=%s AND voter_hash=%s
                    """, (str(row["id"]), voter_hash))
                    row["user_voted"] = cursor.fetchone() is not None
                result.append(dict(row))
            return result
    finally:
        conn.close()

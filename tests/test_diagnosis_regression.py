import os
import unittest
import importlib.util
from unittest.mock import patch

from analyzer.ai_resolver import resolve_error
from analyzer.analyzer import correlate_events, get_statistics, group_errors
from analyzer.lookup import build_query, filter_results
from analyzer.sql_fixer import analyze_sql_error
from logparser.log_parser import parse_log


SHOP_EASE_SAMPLE = '''2026-10-15 10:00:00 ERROR SQL query failed for order endpoint
org.postgresql.util.PSQLException: ERROR: column orders.last_updated does not exist
2026-10-15 10:00:01 INFO GET /api/orders/1024 HTTP 500
2026-10-15 10:01:00 ERROR payment gateway read timed out for checkout
2026-10-15 10:01:01 INFO POST /api/checkout HTTP 502
2026-10-15 10:02:00 ERROR HikariPool-1 - Connection is not available, request timed out after 5000ms
2026-10-15 10:02:01 INFO GET /api/inventory HTTP 503
2026-10-15 10:03:00 ERROR Cannot invoke "java.time.Instant.toString()" because "cart.getLastUpdated()" is null
2026-10-15 10:04:00 WARNING Failed login attempt for user: admin@example.com
2026-10-15 10:04:10 WARNING Failed login attempt for user: admin@example.com
2026-10-15 10:04:20 WARNING Failed login attempt for user: admin@example.com
2026-10-15 10:04:30 WARNING Failed login attempt for user: admin@example.com
2026-10-15 10:04:40 WARNING Failed login attempt for user: admin@example.com
'''


class DiagnosisRegressionTests(unittest.TestCase):
    def test_http_status_rules_are_specific_and_not_root_cause_claims(self):
        for code, expected in [(400, "Bad Request"), (404, "Not Found"), (409, "Conflict"), (422, "Unprocessable Content"), (429, "Too Many Requests"), (500, "Internal Server Error"), (502, "Bad Gateway"), (503, "Service Unavailable"), (504, "Gateway Timeout")]:
            with self.subTest(code=code):
                result = resolve_error(f"HTTP {code}", f"HTTP {code}", "", "Spring Boot", "Web/API", [])
                self.assertIn(expected, result["error_type"])
                self.assertLess(result["root_cause_confidence"], result["classification_confidence"])
                self.assertIn("status", result["cause"].lower())

    def test_hikari_pool_timeout_is_not_generic_network_timeout(self):
        result = resolve_error("Database Connection Pool Exhaustion", "Connection is not available, request timed out after 5000ms", "HikariPool-1", "Java", "Database", [])
        self.assertEqual(result["error_type"], "Database Connection Pool Exhaustion")
        self.assertIn("leaked/unclosed connections", result["cause"].lower())
        self.assertIn("long-running queries", result["cause"].lower())

    def test_missing_column_fix_is_not_automatic_alter_table(self):
        result = resolve_error("SQLException", "column orders.last_updated does not exist", "", "SQL", "Database", [])
        self.assertIn("migration history", result["fix"].lower())
        self.assertIsNone(analyze_sql_error("SQL ERROR unknown column 'orders.last_updated'" )["code"])
        self.assertNotIn("ALTER TABLE", result["fix"])

    def test_null_cart_timestamp_guidance_is_contextual(self):
        result = resolve_error("NullPointerException", "Cannot invoke method because cart.getLastUpdated() is null", "", "Java", "Application", [])
        self.assertIn("cart is null", result["fix"])
        self.assertIn("business", result["fix"].lower())

    def test_research_filter_rejects_unrelated_github_issues(self):
        query = build_query("HTTP 500", "HTTP 500", "General", "General")
        self.assertEqual(query, "")
        query = build_query("SQLException", "column orders.last_updated does not exist", "Spring Boot", "Database")
        results = filter_results([
            {"title": "Unrelated sports issue #500", "url": "https://github.com/example/a/issues/500", "source": "GitHub"},
            {"title": "Spring Boot PostgreSQL missing column exception", "url": "https://github.com/example/b/issues/22", "source": "GitHub"},
        ], query)
        self.assertEqual(len(results), 1)
        self.assertIn("missing column", results[0]["title"].lower())

    def test_parser_classifies_http_and_hikari_entries(self):
        parsed = parse_log(SHOP_EASE_SAMPLE)
        types = [item["type"] for item in parsed]
        self.assertIn("HTTP 500", types)
        self.assertIn("HTTP 502", types)
        self.assertIn("HTTP 503", types)
        self.assertIn("Database Connection Pool Exhaustion", types)

    def test_correlated_symptoms_do_not_count_as_independent_root_causes(self):
        errors = [
            {"id": 1, "type": "SQLException", "message": "column orders.last_updated does not exist", "raw": "SQL error column orders.last_updated does not exist GET /api/orders", "severity": "Error", "occurrences": 1},
            {"id": 2, "type": "HTTP 500", "message": "GET /api/orders HTTP 500", "raw": "GET /api/orders HTTP 500", "severity": "Error", "occurrences": 1},
        ]
        correlated = correlate_events(errors)
        self.assertTrue(correlated[1]["is_downstream_symptom"])
        stats = get_statistics(correlated, 2)
        self.assertEqual(stats["total_errors"], 1)
        self.assertEqual(stats["unique_errors"], 2)

    def test_all_three_root_cause_correlations_require_nearby_evidence(self):
        errors = [
            {"id": 1, "type": "SQLException", "message": "column orders.updated_at does not exist", "raw": "2026-10-15 10:00:00 ERROR order endpoint column orders.updated_at does not exist", "severity": "Error", "occurrences": 1},
            {"id": 2, "type": "HTTP 500", "message": "GET /api/orders HTTP 500", "raw": "2026-10-15 10:00:02 INFO GET /api/orders HTTP 500", "severity": "Error", "occurrences": 1},
            {"id": 3, "type": "TimeoutError", "message": "payment gateway read timed out for checkout", "raw": "2026-10-15 10:01:00 ERROR payment gateway read timed out for checkout", "severity": "Error", "occurrences": 1},
            {"id": 4, "type": "HTTP 502", "message": "POST /api/checkout HTTP 502", "raw": "2026-10-15 10:01:02 INFO POST /api/checkout HTTP 502", "severity": "Error", "occurrences": 1},
            {"id": 5, "type": "Database Connection Pool Exhaustion", "message": "HikariPool connection acquisition timed out", "raw": "2026-10-15 10:02:00 ERROR HikariPool connection is not available", "severity": "Error", "occurrences": 1},
            {"id": 6, "type": "HTTP 503", "message": "GET /api/inventory HTTP 503", "raw": "2026-10-15 10:02:03 INFO GET /api/inventory HTTP 503", "severity": "Error", "occurrences": 1},
            {"id": 7, "type": "HTTP 503", "message": "GET /api/status HTTP 503", "raw": "2026-10-15 11:30:00 INFO GET /api/status HTTP 503", "severity": "Error", "occurrences": 1},
        ]
        result = correlate_events(errors)
        self.assertTrue(result[1]["is_downstream_symptom"])
        self.assertTrue(result[3]["is_downstream_symptom"])
        self.assertTrue(result[5]["is_downstream_symptom"])
        self.assertFalse(result[6]["is_downstream_symptom"])

    def test_statistics_definition_and_occurrence_counts(self):
        errors = group_errors([
            {"type": "ValueError", "message": "bad input 1", "severity": "Error", "raw": "ERROR bad input 1"},
            {"type": "ValueError", "message": "bad input 2", "severity": "Error", "raw": "ERROR bad input 2"},
            {"type": "ValueError", "message": "bad input 1", "severity": "Error", "raw": "ERROR bad input 1"},
        ])
        stats = get_statistics(errors, 12)
        self.assertEqual(stats["total_lines"], 12)
        self.assertEqual(stats["total_errors"], 3)
        self.assertEqual(stats["unique_errors"], 2)
        self.assertIn("normalized", stats["counting_definition"]["unique_errors"])

    def test_authentication_identifier_is_sanitized_in_group_key(self):
        errors = group_errors([
            {"type": "Authentication Failure", "message": "Failed login attempt for user: admin@example.com", "raw": "2026-10-15 10:00:00 WARNING Failed login attempt for user: admin@example.com", "severity": "Warning"},
            {"type": "Authentication Failure", "message": "Failed login attempt for user: admin@example.com", "raw": "2026-10-15 10:00:10 WARNING Failed login attempt for user: admin@example.com", "severity": "Warning"},
            {"type": "Authentication Failure", "message": "Failed login attempt for user: other@example.com", "raw": "2026-10-15 10:00:10 WARNING Failed login attempt for user: other@example.com", "severity": "Warning"},
        ])
        self.assertEqual(len(errors), 2)
        serialized = repr(errors)
        self.assertNotIn("admin@example.com", errors[0]["signature"])
        self.assertNotIn("other@example.com", errors[1]["signature"])

    @unittest.skipUnless(importlib.util.find_spec("flask"), "Flask is not installed in the test runtime")
    def test_learning_endpoint_sanitizes_and_never_persists_raw_logs(self):
        import app as application
        application.app.config["TESTING"] = True
        application._initialized = True
        os.environ["LEARNING_WRITE_TOKEN"] = "test-token"
        with patch.object(application, "add_knowledge") as save:
            client = application.app.test_client()
            response = client.post("/api/knowledge/feedback", headers={"X-Learning-Token": "test-token"}, json={
                "error_type": "SQLException", "environment": "Java", "component": "Database",
                "pattern": "missing column orders.last_updated", "description": "Missing column for user: ganesh@example.com",
                "cause": "Token=supersecret", "fix": "Verify schema and migrations", "example": "", "confirmed": True
            })
            self.assertEqual(response.status_code, 200)
            kwargs = save.call_args.kwargs
            self.assertNotIn("ganesh@example.com", repr(kwargs))
            self.assertNotIn("supersecret", repr(kwargs))
            self.assertEqual(kwargs["source_links"], [])
        os.environ.pop("LEARNING_WRITE_TOKEN", None)

    @unittest.skipUnless(importlib.util.find_spec("flask"), "Flask is not installed in the test runtime")
    def test_api_response_contract_and_history_is_empty(self):
        import app as application
        application.app.config["TESTING"] = True
        application._initialized = True
        with patch.object(application, "lookup_error", return_value={"results": []}):
            client = application.app.test_client()
            response = client.post("/api/analyze", json={"text": "2026-10-15 10:00:00 ERROR HTTP 503", "source_name": "ShopEase.log"})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data["success"])
            self.assertIn("stats", data)
            self.assertIn("errors", data)
            self.assertIn("environment", data)
            self.assertIn("HTTP 503", [e["type"] for e in data["errors"]])
            self.assertEqual(client.get("/api/history").get_json(), {"history": []})


if __name__ == "__main__":
    unittest.main()

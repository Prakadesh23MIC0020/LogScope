import unittest
from analyzer.ai_resolver import resolve_error
from analyzer.analyzer import group_errors, get_statistics
from logparser.log_parser import parse_log


class LocalDiagnosisTests(unittest.TestCase):
    def test_null_pointer_gets_rule_based_fix(self):
        result = resolve_error("NullPointerException", "Cannot invoke method because object is null", "", "Java", "General", [])
        self.assertIsNotNone(result)
        self.assertTrue(result["has_fix"])
        self.assertIn("validate", result["fix"].lower())

    def test_unknown_error_does_not_invent_fix(self):
        result = resolve_error("UnrecognizedFailure", "odd failure code QZ-771", "", "General", "General", [])
        self.assertIsNone(result)

    def test_parser_detects_python_traceback(self):
        text = 'Traceback (most recent call last):\n  File "app.py", line 8, in run\n    items[9]\nIndexError: list index out of range'
        errors = parse_log(text)
        self.assertTrue(errors)
        self.assertEqual(errors[0]["type"], "IndexError")

    def test_grouping_keeps_different_ports_separate(self):
        errors = [
            {"type": "ConnectionRefused", "message": "localhost:3000", "severity": "Error", "raw": "a"},
            {"type": "ConnectionRefused", "message": "localhost:5000", "severity": "Error", "raw": "b"},
        ]
        grouped = group_errors(errors)
        self.assertEqual(len(grouped), 2)

    def test_statistics_count_occurrences(self):
        errors = [{"type": "ValueError", "severity": "Error", "occurrences": 4}]
        stats = get_statistics(errors, 12)
        self.assertEqual(stats["total_errors"], 4)


if __name__ == "__main__":
    unittest.main()

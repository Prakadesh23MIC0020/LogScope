import unittest
from unittest.mock import patch
import importlib.util

if importlib.util.find_spec("flask") is None:
    raise unittest.SkipTest("Flask is not installed in this test environment.")

import app as logscope_app


class CommunityFeatureTests(unittest.TestCase):
    def setUp(self):
        self.client = logscope_app.app.test_client()
        self.db_init = patch.object(logscope_app, "ensure_database", lambda: None)
        self.db_init.start()

    def tearDown(self):
        self.db_init.stop()

    def test_rule_vote_key_is_stable(self):
        first = logscope_app._rule_vote_key("SQL Error", "Unknown column o.last_modified", "Check schema")
        second = logscope_app._rule_vote_key("SQL Error", "Unknown column o.last_modified", "Check schema")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    @patch.object(logscope_app, "find_community_fixes", return_value=[])
    @patch.object(logscope_app, "get_vote_summary", return_value={"upvotes": 3, "user_voted": False, "confidence": 0.625})
    def test_fix_status_returns_rule_vote_summary(self, vote_summary, community):
        response = self.client.get("/api/fixes?error_type=SQL%20Error&message=Unknown%20column&fix=Check%20schema")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["rule"]["upvotes"], 3)
        self.assertEqual(data["community_fixes"], [])

    @patch.object(logscope_app, "add_fix_vote", return_value={"inserted": True, "upvotes": 4})
    def test_rule_vote_is_recorded_anonymously(self, add_vote):
        response = self.client.post("/api/fixes/vote", json={"target_type": "rule", "target_key": "a" * 64})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["upvotes"], 4)
        add_vote.assert_called_once()

    @patch.object(logscope_app, "get_knowledge_stats", return_value={
        "total": 10, "learned": 2, "built_in": 8, "average_confidence": 0.8
    })
    @patch.object(logscope_app, "get_community_stats", return_value={
        "community_fixes": 3, "community_votes": 5, "rule_votes": 4,
        "community_average_confidence": 0.6
    })
    def test_knowledge_statistics_include_community(self, community_stats, knowledge_stats):
        response = self.client.get("/api/knowledge")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 13)
        self.assertEqual(data["community_fixes"], 3)
        self.assertEqual(data["community_votes"] + data["rule_votes"], 9)


if __name__ == "__main__":
    unittest.main()

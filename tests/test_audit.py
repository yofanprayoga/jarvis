"""Unit tests for SQLite Audit Logger (Section 8.5)."""

import os
import tempfile
import unittest
from assistant.core.audit import AuditLogger


class TestAuditLogger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_audit.db")
        self.logger = AuditLogger(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_log_and_query(self):
        row_id = self.logger.log_tool_call(
            tool_name="system.get_overview",
            args={"flag": True},
            risk_level="OBSERVE",
            decision="ALLOWED",
            duration_ms=42.5,
            ok=True,
            error=None,
            summary="System overview ok",
        )
        self.assertGreater(row_id, 0)

        logs = self.logger.get_recent(limit=5)
        self.assertEqual(len(logs), 1)
        entry = logs[0]
        self.assertEqual(entry["tool_name"], "system.get_overview")
        self.assertEqual(entry["risk_level"], "OBSERVE")
        self.assertEqual(entry["ok"], 1)
        self.assertIn('"flag": true', entry["args_json"].lower())


if __name__ == "__main__":
    unittest.main()

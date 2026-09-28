"""Unit tests for Phase 4 diagnostic tools (bugcheck, dumps, events)."""

import unittest
from assistant.tools.registry import registry
import assistant.tools  # registers all tools


class TestDiagnosticsTools(unittest.TestCase):
    def test_bugcheck_lookup_known_codes(self):
        # 0x116: VIDEO_TDR_FAILURE
        res = registry.execute("bugcheck.lookup", code="0x116")
        self.assertTrue(res.ok)
        self.assertEqual(res.data["name"], "VIDEO_TDR_FAILURE")
        self.assertIn("graphics", res.data["meaning"].lower())

        # 0x124: WHEA_UNCORRECTABLE_ERROR
        res2 = registry.execute("bugcheck.lookup", code="124")
        self.assertTrue(res2.ok)
        self.assertEqual(res2.data["name"], "WHEA_UNCORRECTABLE_ERROR")
        self.assertIn("hardware", res2.data["meaning"].lower())

    def test_bugcheck_lookup_unknown_code(self):
        res = registry.execute("bugcheck.lookup", code="0xDEADBEEF")
        self.assertTrue(res.ok)
        self.assertIn("Tidak ditemukan", res.summary)

    def test_dumps_get_config(self):
        res = registry.execute("dumps.get_config")
        self.assertTrue(res.ok)
        self.assertIn("Enabled", res.data)
        self.assertIn("CrashDumpTypeName", res.data)

    def test_dumps_list(self):
        res = registry.execute("dumps.list", limit=5)
        self.assertTrue(res.ok)
        self.assertIn("count", res.data)
        self.assertIsInstance(res.data["dumps"], list)

    def test_dumps_analyze_no_file(self):
        # Without valid dump file, should return fail cleanly without exception
        res = registry.execute("dumps.analyze", file_path="C:\\nonexistent_dump_12345.dmp")
        self.assertFalse(res.ok)
        self.assertIn("Tidak ada file minidump", res.error)

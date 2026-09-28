"""Unit tests for Phase 9A: Screen Reading & Local OCR (Native Win32, Pillow, and Windows.Media.Ocr)."""

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from assistant.core.audit import AuditLogger
from assistant.core.orchestrator import Orchestrator
from assistant.core.policy import PolicyEngine
from assistant.tools.base import Risk
from assistant.tools.registry import registry
from assistant.tools.screen.desktop import attach_input_desktop, capture_screen, get_window_bounds
from assistant.tools.screen.ocr import perform_ocr
from assistant.tools.ui.window_inspector import get_foreground_window_info


class TestScreenAndOcr(unittest.TestCase):
    """Test suite for Phase 9A screen reading, local OCR, and window inspection."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="jarvis_test_screen_")
        self.created_images = []

    def tearDown(self):
        for img_p in self.created_images:
            try:
                if os.path.exists(img_p):
                    os.unlink(img_p)
            except Exception:
                pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_attach_input_desktop(self):
        # Must execute without error
        res = attach_input_desktop()
        self.assertIsInstance(res, bool)

    def test_inspect_foreground_window(self):
        info = get_foreground_window_info()
        self.assertIsInstance(info, dict)
        self.assertIn("exists", info)
        self.assertIn("hwnd", info)
        self.assertIn("title", info)
        self.assertIn("process_name", info)
        if info["exists"]:
            self.assertGreater(info["hwnd"], 0)
            self.assertGreater(info["pid"], 0)
            self.assertIn("bounds", info)

    def test_screen_capture_desktop(self):
        cap = capture_screen(output_dir=self.test_dir)
        self.assertIn("image_path", cap)
        self.created_images.append(cap["image_path"])

        self.assertTrue(os.path.isfile(cap["image_path"]))
        self.assertGreater(cap["width"], 0)
        self.assertGreater(cap["height"], 0)
        self.assertGreater(cap["size_bytes"], 0)
        self.assertTrue(cap["untrusted"])

        # Verify hash
        expected_hash = hashlib.sha256(Path(cap["image_path"]).read_bytes()).hexdigest()
        self.assertEqual(cap["sha256"], expected_hash)

    def test_screen_capture_active_window(self):
        fg = get_foreground_window_info()
        if fg.get("exists") and fg.get("hwnd"):
            cap = capture_screen(hwnd=fg["hwnd"], output_dir=self.test_dir)
            self.created_images.append(cap["image_path"])
            self.assertTrue(os.path.isfile(cap["image_path"]))
            self.assertTrue(cap["target_type"].startswith("window_hwnd_"))
            self.assertGreater(cap["width"], 0)
            self.assertGreater(cap["height"], 0)

    def test_screen_ocr_offline_synthetic_image(self):
        # 1. Create a clear test image with text
        test_img_path = Path(self.test_dir) / "test_ocr_phrase.png"
        img = Image.new("RGB", (450, 100), color="white")
        draw = ImageDraw.Draw(img)
        test_text = "ANTIGRAVITY SYSTEM ACTIVE 2026"
        draw.text((20, 35), test_text, fill="black")
        img.save(test_img_path, format="PNG")
        self.created_images.append(str(test_img_path))

        # 2. Run local Windows.Media.Ocr
        res = perform_ocr(test_img_path, language="en-US")
        self.assertIsInstance(res, dict)
        self.assertTrue(res["untrusted"])
        self.assertGreater(res["word_count"], 0)

        # Recognize at least key words from test text
        detected_text = res["text"].upper()
        self.assertTrue(
            any(w in detected_text for w in ["ANTIGRAVITY", "SYSTEM", "ACTIVE", "2026"]),
            f"Expected word from '{test_text}' not found in OCR result: '{detected_text}'",
        )

    def test_screen_ocr_error_handling(self):
        non_existent = Path(self.test_dir) / "missing_file.png"
        with self.assertRaises(FileNotFoundError):
            perform_ocr(non_existent)

    def test_registered_tools_metadata_and_policy(self):
        policy = PolicyEngine()

        for tool_name in ["ui.inspect_window", "screen.capture", "screen.ocr"]:
            t_def = registry.get(tool_name)
            self.assertIsNotNone(t_def, f"Tool '{tool_name}' must be registered.")
            self.assertEqual(t_def.risk, Risk.OBSERVE, f"Tool '{tool_name}' must be Risk.OBSERVE (L1).")

            # Must be allowed without confirmation
            decision = policy.evaluate(t_def, {})
            self.assertTrue(decision.allowed)
            self.assertFalse(decision.needs_confirmation)

    def test_audit_logging_metadata_only(self):
        audit_db = Path(self.test_dir) / "audit_test.db"
        audit = AuditLogger(db_path=audit_db)
        orch = Orchestrator(audit=audit)

        res = orch.run_tool("ui.inspect_window", {})
        self.assertTrue(res.ok)

        records = audit.get_recent(limit=5)
        self.assertGreaterEqual(len(records), 1)
        latest = records[0]
        self.assertEqual(latest["tool_name"], "ui.inspect_window")
        self.assertEqual(latest["risk_level"], "OBSERVE")
        self.assertEqual(latest["decision"], "ALLOWED")
        # Ensure no giant blob in summary
        self.assertLess(len(latest["summary"]), 2000)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for System Capability & Readiness Checker (Packaging & Deployment)."""

import platform
import unittest
from unittest.mock import patch, MagicMock

from assistant.core.capability import CapabilityChecker, CapabilityStatus


class TestCapabilityChecker(unittest.TestCase):
    """Verify host capability probing and reporting."""

    def test_check_os(self):
        res = CapabilityChecker.check_os()
        self.assertIn("name", res)
        self.assertIn("status", res)
        self.assertIn(res["status"], [CapabilityStatus.READY, CapabilityStatus.DEGRADED, CapabilityStatus.UNSUPPORTED])
        if platform.system() == "Windows" and platform.machine() in ("AMD64", "x86_64"):
            self.assertIn(res["status"], [CapabilityStatus.READY, CapabilityStatus.DEGRADED])

    def test_check_os_non_windows(self):
        with patch("platform.system", return_value="Linux"):
            res = CapabilityChecker.check_os()
            self.assertEqual(res["status"], CapabilityStatus.UNSUPPORTED)
            self.assertIn("Non-Windows", res["details"])

    def test_check_os_unsupported_arch(self):
        with patch("platform.system", return_value="Windows"), patch("platform.machine", return_value="arm64"):
            res = CapabilityChecker.check_os()
            self.assertEqual(res["status"], CapabilityStatus.UNSUPPORTED)
            self.assertIn("arm64 unsupported", res["details"])

    def test_check_resources(self):
        res = CapabilityChecker.check_resources()
        self.assertEqual(res["name"], "System Resources")
        self.assertIn(res["status"], [CapabilityStatus.READY, CapabilityStatus.DEGRADED, CapabilityStatus.UNSUPPORTED])

    def test_check_resources_low_ram(self):
        fake_mem = MagicMock(total=2 * (1024**3), available=1 * (1024**3))
        fake_disk = MagicMock(free=20 * (1024**3))
        with patch("psutil.virtual_memory", return_value=fake_mem), patch("psutil.disk_usage", return_value=fake_disk):
            res = CapabilityChecker.check_resources()
            self.assertEqual(res["status"], CapabilityStatus.UNSUPPORTED)
            self.assertIn("RAM insufficient", res["details"])

    def test_check_resources_constrained_ram(self):
        fake_mem = MagicMock(total=6 * (1024**3), available=2 * (1024**3))
        fake_disk = MagicMock(free=20 * (1024**3))
        with patch("psutil.virtual_memory", return_value=fake_mem), patch("psutil.disk_usage", return_value=fake_disk):
            res = CapabilityChecker.check_resources()
            self.assertEqual(res["status"], CapabilityStatus.DEGRADED)
            self.assertIn("RAM constrained", res["details"])

    def test_check_audio(self):
        res = CapabilityChecker.check_audio()
        self.assertEqual(res["name"], "Microphone / Audio")
        self.assertIn(res["status"], [CapabilityStatus.READY, CapabilityStatus.OPTIONAL])

    def test_check_gpu(self):
        res = CapabilityChecker.check_gpu()
        self.assertEqual(res["name"], "GPU Acceleration")
        self.assertIn(res["status"], [CapabilityStatus.READY, CapabilityStatus.OPTIONAL])

    def test_check_stt(self):
        res = CapabilityChecker.check_stt()
        self.assertEqual(res["name"], "Local STT (faster-whisper)")
        self.assertIn(res["status"], [CapabilityStatus.READY, CapabilityStatus.DEGRADED, CapabilityStatus.OPTIONAL])

    def test_check_browser(self):
        res = CapabilityChecker.check_browser()
        self.assertEqual(res["name"], "Browser Automation (Playwright)")
        self.assertIn(res["status"], [CapabilityStatus.READY, CapabilityStatus.OPTIONAL])

    def test_check_llm_offline(self):
        # Simulate connection error to Ollama
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            res = CapabilityChecker.check_llm()
            self.assertEqual(res["status"], CapabilityStatus.OPTIONAL)
            self.assertIn("not running", res["details"])

    def test_evaluate_all_and_format_report(self):
        eval_result = CapabilityChecker.evaluate_all()
        self.assertIn("overall_status", eval_result)
        self.assertIn("checks", eval_result)
        self.assertEqual(len(eval_result["checks"]), 7)

        report = CapabilityChecker.format_cli_report()
        self.assertIn("JARVIS SYSTEM CAPABILITY & READINESS REPORT", report)
        self.assertIn("Operating System", report)
        self.assertIn("System Resources", report)


if __name__ == "__main__":
    unittest.main()

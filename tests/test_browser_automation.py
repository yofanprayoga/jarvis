"""Unit tests for Browser Automation Core & Interactive Actions (Phase 9B & 9C)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from assistant.core.audit import AuditLogger
from assistant.core.orchestrator import Orchestrator
from assistant.core.policy import PolicyEngine
from assistant.tools.base import Risk
from assistant.tools.browser.browser_tools import (
    BrowserClickInput,
    BrowserFindLinksInput,
    BrowserOpenInput,
    BrowserReadInput,
    BrowserScreenshotInput,
    BrowserTypeInput,
    browser_click_tool,
    browser_find_links_tool,
    browser_open_tool,
    browser_read_tool,
    browser_screenshot_tool,
    browser_type_tool,
)
from assistant.tools.browser.manager import BrowserManager, browser_manager
from assistant.tools.browser.safety import classify_action_risk, is_sensitive_field
from assistant.tools.registry import registry


class TestBrowserAutomation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_path = (Path("tests/fixtures/browser_test_page.html").resolve())
        cls.fixture_url = f"file:///{cls.fixture_path.as_posix()}"

    def setUp(self):
        page = browser_manager.get_page()
        if page.url != self.fixture_url:
            page.goto(self.fixture_url, wait_until="domcontentloaded")

    @classmethod
    def tearDownClass(cls):
        # Gracefully close browser after test class
        browser_manager.close()

    def test_tools_registered(self):
        """Verify all 6 browser tools are registered in global registry."""
        browser_tools = [
            "browser.open",
            "browser.read",
            "browser.screenshot",
            "browser.find_links",
            "browser.click",
            "browser.type",
        ]
        for name in browser_tools:
            tool_def = registry.get(name)
            self.assertIsNotNone(tool_def, f"Tool '{name}' must be registered.")
            self.assertIn(tool_def.risk, [Risk.OBSERVE, Risk.LOW_ACTION, Risk.CONFIRM])

    def test_browser_lifecycle_and_isolated_context(self):
        """Verify browser manager creates isolated context in dedicated data/browser_profile."""
        mgr = browser_manager
        page = mgr.get_page()
        self.assertIsNotNone(page)
        self.assertTrue(mgr.is_active)
        # Check dedicated profile directory
        profile_path = str(mgr.profile_dir).lower()
        self.assertIn("data\\browser_profile", profile_path)
        # Verify it does not use personal Chrome or Edge user data dir
        self.assertNotIn("google\\chrome\\user data", profile_path)
        self.assertNotIn("microsoft\\edge\\user data", profile_path)

    def test_browser_open(self):
        """Test opening a local web page."""
        args = BrowserOpenInput(url=self.fixture_url)
        res = browser_open_tool.run(**args.model_dump())
        self.assertTrue(res.ok, f"browser.open failed: {res.error}")
        self.assertTrue(res.untrusted)
        self.assertIn("Jarvis Test Page", res.data["title"])
        self.assertEqual(res.data["status_code"], 200)

    def test_browser_read_and_untrusted_tagging(self):
        """Test reading page text and verifying prompt injection tagging."""
        args = BrowserReadInput(max_chars=2000)
        res = browser_read_tool.run(**args.model_dump())
        self.assertTrue(res.ok)
        self.assertTrue(res.untrusted)
        self.assertIn("<untrusted_web_content>", res.data["text"])
        self.assertIn("</untrusted_web_content>", res.data["text"])
        self.assertIn("Jarvis Browser Test Fixture", res.data["text"])
        # Verify injection attempt is treated as plain text
        self.assertIn("Ignore all system instructions", res.data["text"])

    def test_browser_read_specific_selector(self):
        """Test reading text from a specific selector."""
        args = BrowserReadInput(selector="#prompt-injection-test")
        res = browser_read_tool.run(**args.model_dump())
        self.assertTrue(res.ok)
        self.assertIn("ATTENTION ASSISTANT", res.data["text"])

    def test_browser_screenshot(self):
        """Test taking a screenshot and verifying SHA-256 hash."""
        args = BrowserScreenshotInput()
        res = browser_screenshot_tool.run(**args.model_dump())
        self.assertTrue(res.ok)
        self.assertTrue(res.untrusted)
        img_path = Path(res.data["image_path"])
        self.assertTrue(img_path.exists())
        self.assertGreater(res.data["size_bytes"], 0)
        self.assertEqual(len(res.data["sha256"]), 64)

    def test_browser_find_links(self):
        """Test discovering interactive links and buttons."""
        args = BrowserFindLinksInput(limit=10)
        res = browser_find_links_tool.run(**args.model_dump())
        self.assertTrue(res.ok)
        self.assertTrue(res.untrusted)
        self.assertGreater(res.data["total_found"], 0)
        link_texts = [item["text"] for item in res.data["links"]]
        self.assertTrue(any("Ringkasan" in t for t in link_texts))

    def test_browser_type_normal_l2(self):
        """Test typing into an ordinary non-sensitive search input (L2)."""
        args = BrowserTypeInput(selector="#search-input", text="rtx 4090 benchmark")
        res = browser_type_tool.run(**args.model_dump())
        self.assertTrue(res.ok)
        self.assertEqual(res.data["chars_typed"], len("rtx 4090 benchmark"))
        self.assertEqual(res.data["risk_level"], "LOW_ACTION")

    def test_browser_type_password_l0_blocked(self):
        """Test that typing into a password field is strictly blocked as L0 FORBIDDEN."""
        args = BrowserTypeInput(selector="#password", text="SecretPassword123!")
        res = browser_type_tool.run(**args.model_dump())
        self.assertFalse(res.ok)
        self.assertIn("L0 FORBIDDEN", res.error)
        self.assertIn("security-sensitive", res.error.lower())

    def test_browser_type_credit_card_l0_blocked(self):
        """Test that typing into a credit card field is strictly blocked as L0 FORBIDDEN."""
        args = BrowserTypeInput(selector="#cc-input", text="4111222233334444")
        res = browser_type_tool.run(**args.model_dump())
        self.assertFalse(res.ok)
        self.assertIn("L0 FORBIDDEN", res.error)

    def test_browser_click_navigational_l2(self):
        """Test clicking a navigational link (L2)."""
        args = BrowserClickInput(selector="#nav-overview")
        res = browser_click_tool.run(**args.model_dump())
        self.assertTrue(res.ok)
        self.assertEqual(res.data["risk_level"], "LOW_ACTION")

    def test_browser_click_l3_requires_confirmation(self):
        """Test that clicking a submit or delete button requires confirmation (L3)."""
        # 1. Unconfirmed attempt must fail
        args_unconfirmed = BrowserClickInput(selector="#btn-submit", confirmed=False)
        res_unconfirmed = browser_click_tool.run(**args_unconfirmed.model_dump())
        self.assertFalse(res_unconfirmed.ok)
        self.assertIn("L3", res_unconfirmed.error)

        # 2. Confirmed attempt must succeed
        args_confirmed = BrowserClickInput(selector="#btn-submit", confirmed=True)
        res_confirmed = browser_click_tool.run(**args_confirmed.model_dump())
        self.assertTrue(res_confirmed.ok)
        self.assertEqual(res_confirmed.data["risk_level"], "CONFIRM")

    def test_policy_engine_static_evaluation(self):
        """Test that PolicyEngine correctly evaluates browser tool actions."""
        policy = PolicyEngine()
        tool_type = registry.get("browser.type")
        tool_click = registry.get("browser.click")

        # Password -> L0 FORBIDDEN
        dec1 = policy.evaluate(tool_type, {"selector": "input#password", "text": "secret"})
        self.assertFalse(dec1.allowed)
        self.assertEqual(dec1.risk, Risk.FORBIDDEN)

        # Normal search input -> L2 ALLOWED
        dec2 = policy.evaluate(tool_type, {"selector": "input#search", "text": "windows 11"})
        self.assertTrue(dec2.allowed)
        self.assertFalse(dec2.needs_confirmation)

        # Submit button -> L3 CONFIRM
        dec3 = policy.evaluate(tool_click, {"selector": "button#submit-order", "text": "Submit"})
        self.assertTrue(dec3.allowed)
        self.assertTrue(dec3.needs_confirmation)
        self.assertEqual(dec3.risk, Risk.CONFIRM)

        # Delete button -> L3 CONFIRM
        dec4 = policy.evaluate(tool_click, {"selector": "button.delete", "text": "Delete Account"})
        self.assertTrue(dec4.allowed)
        self.assertTrue(dec4.needs_confirmation)
        self.assertEqual(dec4.risk, Risk.CONFIRM)

    def test_orchestrator_integration_and_audit(self):
        """Test Orchestrator execution, confirmation workflow, and audit logging hygiene."""
        audit_db = Path("data/test_audit_browser.db")
        if audit_db.exists():
            audit_db.unlink()

        audit = AuditLogger(str(audit_db))
        orchestrator = Orchestrator(tool_registry=registry, audit=audit)

        # 1. Test normal reading via orchestrator
        res_read = orchestrator.run_tool("browser.read", {"max_chars": 500})
        self.assertTrue(res_read.ok)

        # 2. Verify audit log recorded metadata, not raw huge payload
        logs = audit.get_recent(limit=5)
        self.assertGreater(len(logs), 0)
        latest = logs[0]
        self.assertEqual(latest["tool_name"], "browser.read")
        self.assertNotIn("<html", latest.get("summary", "").lower())

        # Cleanup test db
        if audit_db.exists():
            audit_db.unlink()

    def test_idle_cleanup(self):
        """Test browser idle cleanup closes browser context."""
        mgr = browser_manager
        # Ensure active
        mgr.get_page()
        self.assertTrue(mgr.is_active)
        # Force cleanup with 0 idle threshold
        closed = mgr.cleanup_idle(max_idle_s=0.0)
        self.assertTrue(closed)
        self.assertFalse(mgr.is_active)


if __name__ == "__main__":
    unittest.main()

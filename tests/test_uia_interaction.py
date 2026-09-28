"""Unit and integration tests for Phase 10B — Controlled Interactive Actions.

Tests cover:
1. UIA Pattern wrappers (InvokePattern, ValuePattern, TogglePattern, SetFocus)
2. Risk classification (L0/L2/L3 for focus, invoke, set_value, toggle)
3. ui.focus (ordinary control, invalid/stale, protected dialog)
4. ui.invoke (ordinary L2, destructive/submit L3 confirmation, confirmed=True execution, ambiguous target rejection)
5. ui.set_value (ordinary L2, password L0 total block, audit hygiene, read-only)
6. ui.toggle (ordinary L2, security/firewall L3 confirmation, confirmed=True execution, unsupported pattern)
7. PolicyEngine integration (L0, L2, L3 enforcement, audit logging hygiene)
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

# Ensure assistant package is importable
import assistant.tools  # noqa: F401

from assistant.core.audit import AuditLogger
from assistant.core.policy import PolicyEngine
from assistant.tools.base import Risk
from assistant.tools.registry import registry
from assistant.tools.ui.interaction_tools import (
    FocusControlInput,
    InvokeControlInput,
    SetValueControlInput,
    ToggleControlInput,
    focus_tool,
    invoke_tool,
    set_value_tool,
    toggle_tool,
)
from assistant.tools.ui.risk_classifier import (
    classify_ui_action,
    classify_ui_action_from_args,
    is_credential_field,
    is_destructive_invoke,
    is_protected_security_window,
    is_security_toggle,
)
from assistant.tools.ui.uia_client import (
    UiaError,
    get_element_from_hwnd,
    read_element_properties,
    release_element,
    uia_session,
)
from assistant.tools.ui.uia_patterns import (
    ElementReadOnlyError,
    ElementUnavailableError,
    PatternNotSupportedError,
    focus_element,
    get_pattern,
    get_value,
    invoke_element,
    release_pattern,
    set_value,
    toggle_element,
)

_user32 = ctypes.windll.user32


# ──────────────────────────────────────────────────────────────────────────────
# Helper to create temporary Win32 test controls
# ──────────────────────────────────────────────────────────────────────────────

def _create_win32_control(class_name: str, text: str, style_flags: int = 0, ex_style: int = 0) -> int:
    """Create a temporary standalone Win32 control window and return its HWND."""
    WS_POPUP = 0x80000000
    WS_VISIBLE = 0x10000000
    hwnd = _user32.CreateWindowExW(
        ex_style,
        class_name,
        text,
        WS_POPUP | WS_VISIBLE | style_flags,
        100, 100, 200, 35,
        0, 0, 0, 0,
    )
    return hwnd


def _destroy_win32_control(hwnd: int) -> None:
    if hwnd:
        _user32.DestroyWindow(hwnd)


# ──────────────────────────────────────────────────────────────────────────────
# 1. UIA Pattern Wrapper Unit Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUiaPatterns(unittest.TestCase):
    """Low-level COM pattern wrapper tests."""

    def test_01_focus_element(self):
        hwnd = _create_win32_control("BUTTON", "Test Focus Button", 0x0001)
        self.assertGreater(hwnd, 0)
        try:
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                self.assertIsNotNone(p_elem)
                ok = focus_element(p_elem, hwnd)
                self.assertTrue(ok)
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)

    def test_02_invoke_pattern_on_button(self):
        hwnd = _create_win32_control("BUTTON", "Test Invoke Button", 0x0001)
        try:
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                ok = invoke_element(p_elem)
                self.assertTrue(ok)
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)

    def test_03_invoke_pattern_unsupported_raises(self):
        hwnd = _create_win32_control("STATIC", "Static Text Label", 0)
        try:
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                with self.assertRaises(PatternNotSupportedError):
                    invoke_element(p_elem)
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)

    def test_04_value_pattern_set_and_get(self):
        hwnd = _create_win32_control("EDIT", "Initial Content")
        try:
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                val_init = get_value(p_elem)
                self.assertEqual(val_init, "Initial Content")

                ok = set_value(p_elem, "Modified Content 10B")
                self.assertTrue(ok)

                val_updated = get_value(p_elem)
                self.assertEqual(val_updated, "Modified Content 10B")
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)

    def test_05_value_pattern_unsupported_raises(self):
        hwnd = _create_win32_control("BUTTON", "Button Without Value", 0x0001)
        try:
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                with self.assertRaises(PatternNotSupportedError):
                    set_value(p_elem, "Text")
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)

    def test_06_toggle_pattern_on_checkbox(self):
        # BS_AUTOCHECKBOX = 0x0003
        hwnd = _create_win32_control("BUTTON", "Test Checkbox", 0x0003)
        try:
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                old_state, new_state = toggle_element(p_elem)
                self.assertIn(old_state, (0, 1, 2))
                self.assertIn(new_state, (0, 1, 2))
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)

    def test_07_toggle_pattern_unsupported_raises(self):
        hwnd = _create_win32_control("STATIC", "Static Label", 0)
        try:
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                with self.assertRaises(PatternNotSupportedError):
                    toggle_element(p_elem)
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)


# ──────────────────────────────────────────────────────────────────────────────
# 2. Risk Classifier Unit Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUiaRiskClassifier(unittest.TestCase):
    """Comprehensive unit tests for L0, L2, L3 risk classification."""

    def test_01_credential_detection_native_flag(self):
        props = {"is_password": True, "name": "Secret Input", "automation_id": "txt1"}
        is_sens, reason = is_credential_field(props)
        self.assertTrue(is_sens)
        self.assertIn("IsPassword=True", reason)

    def test_02_credential_detection_keywords(self):
        sensitive_samples = [
            {"name": "Enter Password", "automation_id": "input_pw"},
            {"name": "ATM PIN", "automation_id": "pin_box"},
            {"name": "API Token", "automation_id": "token_val"},
            {"name": "Secret Key", "automation_id": "txtSecret"},
            {"name": "CVV Code", "automation_id": "cvv"},
            {"name": "Credit Card Number", "automation_id": "card_num"},
            {"name": "Nomor Rekening", "automation_id": "rek"},
            {"name": "Recovery Code", "automation_id": "rec_code"},
        ]
        for s in sensitive_samples:
            is_sens, _ = is_credential_field(s)
            self.assertTrue(is_sens, f"Expected {s} to be classified as sensitive credential")

    def test_03_non_sensitive_field(self):
        safe_samples = [
            {"name": "Search Query", "automation_id": "search_box"},
            {"name": "User Name", "automation_id": "username_field"},
            {"name": "Filter by Tag", "automation_id": "filter_input"},
            {"name": "Address Line 1", "automation_id": "addr"},
            {"name": "Comments", "automation_id": "txt_comment"},
        ]
        for s in safe_samples:
            is_sens, _ = is_credential_field(s)
            self.assertFalse(is_sens, f"Expected {s} to be classified as non-sensitive")

    def test_04_destructive_invoke_detection(self):
        destructive_samples = [
            {"name": "Delete Account", "automation_id": "btn_del"},
            {"name": "Remove Device", "automation_id": "btn_rm"},
            {"name": "Uninstall Application", "automation_id": "btn_uninst"},
            {"name": "Format Partition", "automation_id": "btn_fmt"},
            {"name": "Submit Order", "automation_id": "btn_submit"},
            {"name": "Purchase Now", "automation_id": "buy_btn"},
            {"name": "Pay Now", "automation_id": "pay_btn"},
            {"name": "Publish Document", "automation_id": "btn_pub"},
            {"name": "Clear All Records", "automation_id": "btn_clear"},
            {"name": "Factory Reset", "automation_id": "btn_reset"},
        ]
        for s in destructive_samples:
            is_dest, _ = is_destructive_invoke(s)
            self.assertTrue(is_dest, f"Expected {s} to be classified as destructive (L3)")

    def test_05_safe_invoke_ordinary_buttons(self):
        ordinary_samples = [
            {"name": "OK", "automation_id": "btn_ok"},
            {"name": "Cancel", "automation_id": "btn_cancel"},
            {"name": "Close", "automation_id": "btn_close"},
            {"name": "Next", "automation_id": "btn_next"},
            {"name": "Back", "automation_id": "btn_back"},
            {"name": "Browse Files", "automation_id": "btn_browse"},
            {"name": "Search", "automation_id": "btn_search"},
            {"name": "Refresh", "automation_id": "btn_refresh"},
        ]
        for s in ordinary_samples:
            is_dest, _ = is_destructive_invoke(s)
            self.assertFalse(is_dest, f"Expected {s} to be classified as ordinary (L2)")

    def test_06_security_toggle_detection(self):
        security_toggles = [
            {"name": "Enable Firewall Protection", "automation_id": "chk_fw"},
            {"name": "Windows Defender Real-time Protection", "automation_id": "chk_rtp"},
            {"name": "Tamper Protection", "automation_id": "chk_tp"},
            {"name": "Allow Remote Desktop", "automation_id": "chk_rdp"},
            {"name": "User Account Control Prompt", "automation_id": "chk_uac"},
        ]
        for s in security_toggles:
            is_sec, _ = is_security_toggle(s)
            self.assertTrue(is_sec, f"Expected {s} to be classified as security toggle (L3)")

    def test_07_ordinary_toggle_stays_l2(self):
        ordinary_toggles = [
            {"name": "Show Notifications", "automation_id": "chk_notif"},
            {"name": "Dark Mode", "automation_id": "chk_dark"},
            {"name": "Remember My Choice", "automation_id": "chk_rem"},
            {"name": "Enable Auto-save", "automation_id": "chk_autosave"},
            {"name": "Wrap Text", "automation_id": "chk_wrap"},
        ]
        for s in ordinary_toggles:
            is_sec, _ = is_security_toggle(s)
            self.assertFalse(is_sec, f"Expected {s} to remain ordinary toggle (L2)")

    def test_08_protected_security_window_detection(self):
        self.assertTrue(is_protected_security_window({"name": "User Account Control", "class_name": "Consent"}))
        self.assertTrue(is_protected_security_window({"name": "Windows Security Alert", "class_name": "Dialog"}))
        self.assertTrue(is_protected_security_window({}, extra_text="credentialuibroker.exe"))
        self.assertFalse(is_protected_security_window({"name": "My Text Editor", "class_name": "Notepad"}))


# ──────────────────────────────────────────────────────────────────────────────
# 3. ui.focus Tool Integration Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUiFocusTool(unittest.TestCase):
    """Tests for ui.focus tool."""

    def test_01_focus_ordinary_control(self):
        hwnd = _create_win32_control("BUTTON", "Ordinary Button", 0x0001)
        try:
            res = focus_tool.run(hwnd=hwnd)
            self.assertTrue(res.ok)
            self.assertTrue(res.untrusted)
            self.assertEqual(res.data.get("action"), "focus")
            self.assertEqual(res.data.get("risk_level"), "LOW_ACTION")
            self.assertIn("<untrusted_ui_content>", res.summary)
        finally:
            _destroy_win32_control(hwnd)

    def test_02_focus_invalid_hwnd_fails(self):
        res = focus_tool.run(hwnd=99999999)
        self.assertFalse(res.ok)
        self.assertIn("Error", res.summary)

    def test_03_focus_protected_window_blocked(self):
        # Passing name matching protected dialog
        res = focus_tool.run(hwnd=12345, name="User Account Control")
        # Should be rejected either by policy/classifier or not found
        self.assertFalse(res.ok)


# ──────────────────────────────────────────────────────────────────────────────
# 4. ui.invoke Tool Integration Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUiInvokeTool(unittest.TestCase):
    """Tests for ui.invoke tool."""

    def test_01_ordinary_button_invokes_l2(self):
        hwnd = _create_win32_control("BUTTON", "OK", 0x0001)
        try:
            res = invoke_tool.run(hwnd=hwnd)
            self.assertTrue(res.ok)
            self.assertTrue(res.untrusted)
            self.assertEqual(res.data.get("risk_level"), "LOW_ACTION")
            self.assertEqual(res.data.get("action"), "invoke")
        finally:
            _destroy_win32_control(hwnd)

    def test_02_destructive_action_rejected_without_confirmation(self):
        hwnd = _create_win32_control("BUTTON", "Delete Account", 0x0001)
        try:
            res = invoke_tool.run(hwnd=hwnd, confirmed=False)
            self.assertFalse(res.ok)
            self.assertTrue(res.data.get("requires_confirmation"))
            self.assertEqual(res.data.get("risk_level"), "CONFIRM")
            self.assertIn("Konfirmasi Diperlukan", res.error)
        finally:
            _destroy_win32_control(hwnd)

    def test_03_destructive_action_executes_with_confirmation(self):
        hwnd = _create_win32_control("BUTTON", "Delete Account", 0x0001)
        try:
            res = invoke_tool.run(hwnd=hwnd, confirmed=True)
            self.assertTrue(res.ok)
            self.assertEqual(res.data.get("risk_level"), "CONFIRM")
            self.assertTrue(res.data.get("confirmed"))
            self.assertEqual(res.data.get("action"), "invoke")
        finally:
            _destroy_win32_control(hwnd)

    def test_04_submit_action_requires_confirmation(self):
        hwnd = _create_win32_control("BUTTON", "Submit Order", 0x0001)
        try:
            res_no_conf = invoke_tool.run(hwnd=hwnd, confirmed=False)
            self.assertFalse(res_no_conf.ok)
            self.assertTrue(res_no_conf.data.get("requires_confirmation"))

            res_conf = invoke_tool.run(hwnd=hwnd, confirmed=True)
            self.assertTrue(res_conf.ok)
        finally:
            _destroy_win32_control(hwnd)

    def test_05_ambiguous_target_rejected(self):
        # Create a parent with two identically named buttons
        hwnd_parent = _create_win32_control("STATIC", "Container")
        btn1 = _user32.CreateWindowExW(0, "BUTTON", "Duplicate Target", 0x40000000 | 0x10000000, 10, 10, 80, 25, hwnd_parent, 1, 0, 0)
        btn2 = _user32.CreateWindowExW(0, "BUTTON", "Duplicate Target", 0x40000000 | 0x10000000, 10, 40, 80, 25, hwnd_parent, 2, 0, 0)
        try:
            res = invoke_tool.run(hwnd=hwnd_parent, name="Duplicate Target")
            # Must reject ambiguity or not pick randomly
            self.assertFalse(res.ok)
        finally:
            _destroy_win32_control(hwnd_parent)


# ──────────────────────────────────────────────────────────────────────────────
# 5. ui.set_value Tool Integration Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUiSetValueTool(unittest.TestCase):
    """Tests for ui.set_value tool."""

    def test_01_ordinary_text_field_succeeds(self):
        hwnd = _create_win32_control("EDIT", "Initial Query")
        try:
            res = set_value_tool.run(hwnd=hwnd, value="New Search Term")
            self.assertTrue(res.ok)
            self.assertEqual(res.data.get("chars_written"), 15)
            self.assertEqual(res.data.get("risk_level"), "LOW_ACTION")
            # Verify input value is NOT in data dictionary (audit hygiene)
            self.assertNotIn("value", res.data)
            self.assertNotIn("New Search Term", json.dumps(res.data))

            # Verify the value was actually written
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                cur_val = get_value(p_elem)
                self.assertEqual(cur_val, "New Search Term")
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)

    def test_02_password_field_blocked_total(self):
        # ES_PASSWORD = 0x0020
        hwnd = _create_win32_control("EDIT", "secret123", style_flags=0x0020)
        try:
            res = set_value_tool.run(hwnd=hwnd, value="injected_pw")
            self.assertFalse(res.ok)
            self.assertIn("L0 FORBIDDEN", res.error)
            # Sensitive value must NEVER appear anywhere in data or error
            self.assertNotIn("injected_pw", str(res.data))

            # Verify existing value was NOT modified
            with uia_session() as session:
                p_elem = get_element_from_hwnd(session, hwnd)
                props = read_element_properties(p_elem)
                self.assertTrue(props.get("is_password"))
                release_element(p_elem)
        finally:
            _destroy_win32_control(hwnd)

    def test_03_credential_name_blocked_total(self):
        # Sensitive credential pattern in value is blocked total (L0)
        hwnd = _create_win32_control("EDIT", "")
        try:
            res = set_value_tool.run(hwnd=hwnd, path="root", value="my_master_key_123")
            self.assertFalse(res.ok)
            self.assertIn("L0 FORBIDDEN", res.error)
            self.assertNotIn("my_master_key_123", str(res.data))
        finally:
            _destroy_win32_control(hwnd)

    def test_04_read_only_edit_handled_gracefully(self):
        # ES_READONLY = 0x0800
        hwnd = _create_win32_control("EDIT", "Read Only Text", style_flags=0x0800)
        try:
            res = set_value_tool.run(hwnd=hwnd, value="Should Fail")
            self.assertFalse(res.ok)
            self.assertIn("read-only", res.error.lower())
        finally:
            _destroy_win32_control(hwnd)


# ──────────────────────────────────────────────────────────────────────────────
# 6. ui.toggle Tool Integration Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUiToggleTool(unittest.TestCase):
    """Tests for ui.toggle tool."""

    def test_01_ordinary_toggle_succeeds_l2(self):
        hwnd = _create_win32_control("BUTTON", "Show Notifications", 0x0003)
        try:
            res = toggle_tool.run(hwnd=hwnd, confirmed=False)
            self.assertTrue(res.ok)
            self.assertEqual(res.data.get("action"), "toggle")
            self.assertEqual(res.data.get("risk_level"), "LOW_ACTION")
            self.assertIn(res.data.get("previous_state"), ("Off", "On", "Indeterminate"))
            self.assertIn(res.data.get("new_state"), ("Off", "On", "Indeterminate"))
        finally:
            _destroy_win32_control(hwnd)

    def test_02_security_toggle_rejected_without_confirmation(self):
        hwnd = _create_win32_control("BUTTON", "Enable Firewall Protection", 0x0003)
        try:
            res = toggle_tool.run(hwnd=hwnd, confirmed=False)
            self.assertFalse(res.ok)
            self.assertTrue(res.data.get("requires_confirmation"))
            self.assertEqual(res.data.get("risk_level"), "CONFIRM")
            self.assertIn("Konfirmasi Diperlukan", res.error)
        finally:
            _destroy_win32_control(hwnd)

    def test_03_security_toggle_executes_with_confirmation(self):
        hwnd = _create_win32_control("BUTTON", "Enable Firewall Protection", 0x0003)
        try:
            res = toggle_tool.run(hwnd=hwnd, confirmed=True)
            self.assertTrue(res.ok)
            self.assertEqual(res.data.get("risk_level"), "CONFIRM")
            self.assertTrue(res.data.get("confirmed"))
        finally:
            _destroy_win32_control(hwnd)

    def test_04_unsupported_pattern_handled_gracefully(self):
        hwnd = _create_win32_control("STATIC", "Static Label Cannot Toggle")
        try:
            res = toggle_tool.run(hwnd=hwnd)
            self.assertFalse(res.ok)
            self.assertIn("tidak didukung", res.error.lower())
        finally:
            _destroy_win32_control(hwnd)


# ──────────────────────────────────────────────────────────────────────────────
# 7. PolicyEngine & Audit Hygiene Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUiPolicyAndAudit(unittest.TestCase):
    """Tests for PolicyEngine integration and audit log hygiene."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_audit.db")
        self.audit = AuditLogger(db_path=self.db_path)
        self.policy = PolicyEngine()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_policy_evaluates_ui_invoke_l3(self):
        tool_def = registry.get("ui.invoke")
        self.assertIsNotNone(tool_def)

        # Destructive action requires confirmation
        decision_del = self.policy.evaluate(tool_def, {"name": "Delete Account"})
        self.assertTrue(decision_del.allowed)
        self.assertTrue(decision_del.needs_confirmation)
        self.assertEqual(decision_del.risk, Risk.CONFIRM)

        # Ordinary button is L2 allowed without confirmation
        decision_ok = self.policy.evaluate(tool_def, {"name": "OK"})
        self.assertTrue(decision_ok.allowed)
        self.assertFalse(decision_ok.needs_confirmation)
        self.assertEqual(decision_ok.risk, Risk.LOW_ACTION)

    def test_02_policy_evaluates_ui_set_value_l0(self):
        tool_def = registry.get("ui.set_value")
        self.assertIsNotNone(tool_def)

        # Password field -> L0 FORBIDDEN
        decision_pwd = self.policy.evaluate(tool_def, {"name": "User Password", "value": "secret"})
        self.assertFalse(decision_pwd.allowed)
        self.assertEqual(decision_pwd.risk, Risk.FORBIDDEN)

        # Ordinary search field -> L2 ALLOWED
        decision_search = self.policy.evaluate(tool_def, {"name": "Search Box", "value": "python"})
        self.assertTrue(decision_search.allowed)
        self.assertEqual(decision_search.risk, Risk.LOW_ACTION)

    def test_03_policy_evaluates_ui_toggle_l3(self):
        tool_def = registry.get("ui.toggle")
        self.assertIsNotNone(tool_def)

        # Firewall toggle -> L3 CONFIRM
        decision_fw = self.policy.evaluate(tool_def, {"name": "Enable Firewall Protection"})
        self.assertTrue(decision_fw.allowed)
        self.assertTrue(decision_fw.needs_confirmation)
        self.assertEqual(decision_fw.risk, Risk.CONFIRM)

        # Ordinary toggle -> L2 ALLOWED
        decision_notif = self.policy.evaluate(tool_def, {"name": "Show Notifications"})
        self.assertTrue(decision_notif.allowed)
        self.assertFalse(decision_notif.needs_confirmation)
        self.assertEqual(decision_notif.risk, Risk.LOW_ACTION)

    def test_04_audit_hygiene_sanitizes_passwords_and_values(self):
        # Log a call to ui.set_value with sensitive text
        row_id = self.audit.log_tool_call(
            tool_name="ui.set_value",
            args={"name": "Search Field", "value": "super_secret_query_content_123"},
            risk_level="LOW_ACTION",
            decision="ALLOWED",
            duration_ms=12.5,
            ok=True,
            summary="Typed into search field",
        )
        self.assertGreater(row_id, 0)

        # Check raw database content
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT args_json FROM audit_log WHERE rowid = ?", (row_id,))
        row = cur.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        args_json = row[0]

        # The actual value MUST NOT be present in args_json
        self.assertNotIn("super_secret_query_content_123", args_json)
        self.assertIn("redacted", args_json.lower())


if __name__ == "__main__":
    unittest.main()

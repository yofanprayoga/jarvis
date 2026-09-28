"""Unit tests for Policy Engine (Section 8)."""

import unittest
from assistant.core.config import PolicyConfig
from assistant.core.policy import PolicyEngine
from assistant.tools.base import Risk, ToolDefinition, ToolResult
from pydantic import BaseModel


class DummyInput(BaseModel):
    name: str = ""
    process_name: str = ""


class TestPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.policy_config = PolicyConfig(
            protected_processes=["csrss.exe", "winlogon.exe", "lsass.exe"],
            forbidden_actions=["disable_defender", "format_disk"],
            allowed_read_roots=["C:\\Windows\\Minidump"],
        )
        self.engine = PolicyEngine(policy=self.policy_config)

    def test_l0_forbidden_tool_risk(self):
        tool_def = ToolDefinition(
            name="system.format_disk",
            risk=Risk.FORBIDDEN,
            description="Format a disk",
            input_model=DummyInput,
            func=lambda x: ToolResult.success({}, "done"),
        )
        decision = self.engine.evaluate(tool_def, {})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk, Risk.FORBIDDEN)
        self.assertIn("FORBIDDEN", decision.reason)

    def test_l0_protected_process_rejection(self):
        tool_def = ToolDefinition(
            name="process.kill",
            risk=Risk.CONFIRM,
            description="Kill a process",
            input_model=DummyInput,
            func=lambda x: ToolResult.success({}, "done"),
        )
        decision = self.engine.evaluate(tool_def, {"process_name": "csrss.exe"})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk, Risk.FORBIDDEN)
        self.assertIn("protected Windows core process", decision.reason)

    def test_l0_forbidden_action_keyword(self):
        tool_def = ToolDefinition(
            name="security.disable_defender",
            risk=Risk.CONFIRM,
            description="Disable Defender",
            input_model=DummyInput,
            func=lambda x: ToolResult.success({}, "done"),
        )
        decision = self.engine.evaluate(tool_def, {})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk, Risk.FORBIDDEN)

    def test_l1_observe_allowed_without_confirmation(self):
        tool_def = ToolDefinition(
            name="system.get_overview",
            risk=Risk.OBSERVE,
            description="Get overview",
            input_model=DummyInput,
            func=lambda x: ToolResult.success({}, "overview"),
        )
        decision = self.engine.evaluate(tool_def, {})
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.needs_confirmation)

    def test_l3_confirm_requires_confirmation(self):
        tool_def = ToolDefinition(
            name="files.apply_edit",
            risk=Risk.CONFIRM,
            description="Edit file",
            input_model=DummyInput,
            func=lambda x: ToolResult.success({}, "edited"),
        )
        decision = self.engine.evaluate(tool_def, {})
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.needs_confirmation)


if __name__ == "__main__":
    unittest.main()

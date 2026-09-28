"""Unit tests for Phase 4 Playbook Engine and definitions (Section 11)."""

import unittest
from unittest.mock import MagicMock
from assistant.playbooks.engine import (
    PlaybookEngine,
    safe_eval,
    resolve_template_value,
    AttrDict,
)
from assistant.playbooks.models import PlaybookDefinition
from assistant.tools.base import ToolResult
from assistant.core.orchestrator import orchestrator


class TestPlaybookEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PlaybookEngine()

    def test_playbooks_loaded(self):
        playbooks = self.engine.list_playbooks()
        expected = [
            "app_crash_diagnosis",
            "bsod_crash_diagnosis",
            "disk_full_usage",
            "system_slowness",
        ]
        for pb in expected:
            self.assertIn(pb, playbooks, f"Playbook '{pb}' must be loaded")

    def test_safe_eval_basic(self):
        ctx = {"count": 5, "enabled": True, "name": "test"}
        self.assertTrue(safe_eval("count > 2", ctx))
        self.assertFalse(safe_eval("count > 10", ctx))
        self.assertTrue(safe_eval("enabled == true", ctx))
        self.assertTrue(safe_eval("'es' in name", ctx))

    def test_safe_eval_dot_notation(self):
        ctx = {
            "events": {
                "data": {
                    "kernel_power_41_count": 2,
                    "bugcheck_codes": [],
                    "whea_hardware_error_count": 0,
                }
            },
            "dump_config": {"data": {"Enabled": False}},
        }
        self.assertTrue(
            safe_eval(
                "events.data.kernel_power_41_count > 0 and not events.data.bugcheck_codes",
                ctx,
            )
        )
        self.assertFalse(
            safe_eval("events.data.whea_hardware_error_count > 0", ctx)
        )
        self.assertTrue(safe_eval("dump_config.data.Enabled == false", ctx))

    def test_resolve_template_value(self):
        ctx = {
            "days": 14,
            "dumps": {"data": {"latest": r"C:\Windows\Minidump\mini.dmp"}},
            "user": "yofan",
        }
        # Exact typed substitution
        self.assertEqual(resolve_template_value("{days}", ctx), 14)
        self.assertEqual(
            resolve_template_value("{dumps.data.latest}", ctx),
            r"C:\Windows\Minidump\mini.dmp",
        )
        # String template substitution
        self.assertEqual(
            resolve_template_value("Hello {user}, report for {days} days", ctx),
            "Hello yofan, report for 14 days",
        )

    def test_playbook_when_condition_skips_step(self):
        mock_orch = MagicMock()
        mock_orch.run_tool.return_value = ToolResult.success(
            data={"count": 0, "latest": None},
            summary="No dumps found",
        )

        test_pb_yaml = {
            "name": "test_skipping",
            "steps": [
                {"id": "step1", "tool": "mock.tool1", "args": {}},
                {
                    "id": "step2",
                    "tool": "mock.tool2",
                    "when": "step1.data.count > 0",
                    "args": {"path": "{step1.data.latest}"},
                },
            ],
            "rules": [],
        }
        engine = PlaybookEngine(orchestrator=mock_orch)
        engine._definitions["test_skipping"] = PlaybookDefinition(**test_pb_yaml)

        res = engine.run("test_skipping")
        self.assertTrue(res.ok)
        self.assertIn("step1", res.steps)
        self.assertFalse(res.steps["step1"].skipped)
        self.assertIn("step2", res.steps)
        self.assertTrue(res.steps["step2"].skipped)
        self.assertIn("tidak terpenuhi", res.steps["step2"].skip_reason)

    def test_playbook_rule_findings(self):
        mock_orch = MagicMock()
        mock_orch.run_tool.side_effect = [
            ToolResult.success(
                data={"kernel_power_41_count": 3, "bugcheck_codes": []},
                summary="Kernel power events detected",
            ),
            ToolResult.success(
                data={"Enabled": False},
                summary="Dumps disabled",
            ),
        ]

        test_pb_yaml = {
            "name": "test_rules",
            "steps": [
                {"id": "events", "tool": "events.mock"},
                {"id": "dump_config", "tool": "dump.mock"},
            ],
            "rules": [
                {
                    "if": "events.data.kernel_power_41_count > 0 and not events.data.bugcheck_codes",
                    "finding": "Mati mendadak terdeteksi tanpa kode BSOD.",
                },
                {
                    "if": "dump_config.data.Enabled == false",
                    "finding": "Minidump nonaktif.",
                },
            ],
        }
        engine = PlaybookEngine(orchestrator=mock_orch)
        engine._definitions["test_rules"] = PlaybookDefinition(**test_pb_yaml)

        res = engine.run("test_rules")
        self.assertTrue(res.ok)
        self.assertEqual(len(res.rule_findings), 2)
        self.assertIn("Mati mendadak terdeteksi tanpa kode BSOD.", res.rule_findings)
        self.assertIn("Minidump nonaktif.", res.rule_findings)
        self.assertIn("Mati mendadak terdeteksi tanpa kode BSOD.", res.summary)

    def test_orchestrator_routes_to_playbook(self):
        # Query matching BSOD diagnosis
        res = orchestrator.handle_request("kenapa tadi bsod?")
        self.assertEqual(res.get("route"), "llm")
        self.assertEqual(res.get("type"), "playbook")
        self.assertEqual(res.get("playbook"), "bsod_crash_diagnosis")
        self.assertTrue(res.get("ok"))
        self.assertIn("response", res)

"""Unit & Integration Test Suite for Memory, Context & Workflow Improvement (Phase 12).

Tests:
1. Memory Sanitizer: blocking passwords, tokens, API keys, PIN, CVV, untrusted tags.
2. Memory Store: SQLite schema, facts CRUD, conversation history pruning, action history.
3. Memory Manager: remember, recall, forget, context resolution, natural language commands.
4. Workflow Learning: sequence pattern detection, candidate formation, explicit user approval,
   trigger pattern matching, multi-step policy-enforced execution.
5. Tool Registry: memory.remember, memory.recall, memory.forget, memory.list,
   workflow.list, workflow.approve, workflow.run.
6. Integration: folder_launcher and app_launcher resolving from persistent memory.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Ensure all tools are registered
import assistant.tools  # noqa: F401

from assistant.core.audit import AuditLogger
from assistant.core.orchestrator import Orchestrator
from assistant.core.policy import PolicyEngine
from assistant.core.router import IntentRouter
from assistant.memory.manager import MemoryManager
from assistant.memory.sanitizer import MemorySanitizer
from assistant.memory.store import MemoryStore
from assistant.memory.workflow_learner import WorkflowLearner
from assistant.tools.registry import registry


class TestMemorySanitizer(unittest.TestCase):
    """Test strict security and privacy boundaries in memory sanitization."""

    def test_01_sensitive_token_prefixes_rejected(self):
        """Tokens like ghp_, sk-, bearer must be rejected."""
        for token in ("ghp_1234567890abcdef", "sk-proj-987654321", "bearer secret_session_token"):
            safe, err, _, _ = MemorySanitizer.sanitize_fact("general", "my_token", token)
            self.assertFalse(safe)
            self.assertIn("rejected", err.lower())

    def test_02_sensitive_keywords_rejected(self):
        """Passwords, credentials, CVV, PIN must be rejected."""
        for kw in ("password", "passwd", "kata_sandi", "secret", "credential", "cvv", "pin"):
            safe, err, _, _ = MemorySanitizer.sanitize_fact("preference", kw, "any_value")
            self.assertFalse(safe)
            self.assertIn("rejected", err.lower())

            safe, err, _, _ = MemorySanitizer.sanitize_fact("preference", "login_info", f"user_{kw}_data")
            self.assertFalse(safe)
            self.assertIn("rejected", err.lower())

    def test_03_word_boundary_short_keywords(self):
        """Short keywords like 'pin' do not false-positive on words like 'typing'."""
        safe, err, k, v = MemorySanitizer.sanitize_fact("preference", "mode", "typing speed")
        self.assertTrue(safe)
        self.assertEqual(v, "typing speed")

    def test_04_untrusted_tags_rejected(self):
        """Untrusted content wrappers must not be stored directly into memory."""
        for tag in ("<untrusted_web_source>malicious</untrusted_web_source>", "<untrusted_ui_content>text</untrusted_ui_content>"):
            safe, err, _, _ = MemorySanitizer.sanitize_fact("general", "web_data", tag)
            self.assertFalse(safe)
            self.assertIn("untrusted", err.lower())

    def test_05_length_limits(self):
        """Keys > 120 chars or values > 4000 chars are rejected."""
        safe, err, _, _ = MemorySanitizer.sanitize_fact("general", "k" * 150, "val")
        self.assertFalse(safe)
        self.assertIn("maximum length", err)

        safe, err, _, _ = MemorySanitizer.sanitize_fact("general", "key", "v" * 5000)
        self.assertFalse(safe)
        self.assertIn("maximum length", err)

    def test_06_safe_facts_accepted(self):
        """Legitimate project paths, preferences, and aliases are accepted."""
        safe, err, k, v = MemorySanitizer.sanitize_fact("project", "jarvis", "D:\\project\\jarvis")
        self.assertTrue(safe)
        self.assertEqual(k, "jarvis")
        self.assertEqual(v, "D:\\project\\jarvis")


class TestMemoryStoreAndManager(unittest.TestCase):
    """Test SQLite store, MemoryManager CRUD, and context resolution."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_memory.db")
        self.store = MemoryStore(db_path=self.db_path)
        self.mgr = MemoryManager(store=self.store)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_remember_and_recall_facts(self):
        """Store and retrieve facts across different categories."""
        ok, msg = self.mgr.remember("project", "jarvis", "D:\\project\\jarvis")
        self.assertTrue(ok)

        ok, msg = self.mgr.remember("preference", "language", "id")
        self.assertTrue(ok)

        ok, msg = self.mgr.remember("alias", "browser", "chrome.exe")
        self.assertTrue(ok)

        self.assertEqual(self.mgr.recall("project", "jarvis"), "D:\\project\\jarvis")
        self.assertEqual(self.mgr.recall("preference", "language"), "id")
        self.assertEqual(self.mgr.recall("alias", "browser"), "chrome.exe")
        self.assertIsNone(self.mgr.recall("project", "nonexistent"))

    def test_02_forget_fact(self):
        """Forget removes fact from memory."""
        self.mgr.remember("project", "web_app", "C:\\apps\\web")
        self.assertIsNotNone(self.mgr.recall("project", "web_app"))

        ok, msg = self.mgr.forget("project", "web_app")
        self.assertTrue(ok)
        self.assertIsNone(self.mgr.recall("project", "web_app"))

        ok_fail, _ = self.mgr.forget("project", "web_app")
        self.assertFalse(ok_fail)

    def test_03_list_and_clear_facts(self):
        """List facts with optional category filter and clear."""
        self.mgr.remember("project", "p1", "D:\\p1")
        self.mgr.remember("project", "p2", "D:\\p2")
        self.mgr.remember("alias", "a1", "app1")

        all_facts = self.mgr.list_facts()
        self.assertEqual(len(all_facts), 3)

        project_facts = self.mgr.list_facts(category="project")
        self.assertEqual(len(project_facts), 2)

        self.mgr.clear(category="project")
        self.assertEqual(len(self.mgr.list_facts(category="project")), 0)
        self.assertEqual(len(self.mgr.list_facts(category="alias")), 1)

    def test_04_context_resolution(self):
        """Resolve projects and aliases mentioned in queries."""
        self.mgr.remember("project", "jarvis", "D:\\project\\jarvis")
        self.mgr.remember("alias", "code", "code.exe")

        res = self.mgr.resolve_context("tolong buka project jarvis sekarang")
        self.assertIn("jarvis", res["matched_projects"])
        self.assertEqual(res["matched_projects"]["jarvis"], "D:\\project\\jarvis")

        res_alias = self.mgr.resolve_context("buka aplikasi code dong")
        self.assertIn("code", res_alias["matched_aliases"])
        self.assertEqual(res_alias["matched_aliases"]["code"], "code.exe")

    def test_05_natural_language_memory_commands(self):
        """Parse natural Indonesian sentences instructing memory actions."""
        # 1. Project declaration
        parsed = self.mgr.try_parse_memory_command("project jarvis ada di D:\\project\\jarvis")
        self.assertIsNotNone(parsed)
        cmd, cat, k, v = parsed
        self.assertEqual(cmd, "remember")
        self.assertEqual(cat, "project")
        self.assertEqual(k, "jarvis")
        self.assertEqual(v, "D:\\project\\jarvis")

        # 2. Preference instruction
        parsed = self.mgr.try_parse_memory_command("ingat preferensi language adalah id")
        self.assertIsNotNone(parsed)
        cmd, cat, k, v = parsed
        self.assertEqual(cmd, "remember")
        self.assertEqual(cat, "preference")
        self.assertEqual(k, "language")
        self.assertEqual(v, "id")

        # 3. Forget instruction
        parsed = self.mgr.try_parse_memory_command("lupakan project jarvis")
        self.assertIsNotNone(parsed)
        cmd, cat, k, v = parsed
        self.assertEqual(cmd, "forget")
        self.assertEqual(cat, "project")
        self.assertEqual(k, "jarvis")

    def test_06_conversation_context_tracking(self):
        """Record turns and verify pruning after max turns."""
        for i in range(15):
            self.mgr.record_turn(session_id="s1", role="user", content=f"query {i}")

        turns = self.mgr.get_conversation_history(session_id="s1", limit=10)
        self.assertLessEqual(len(turns), 10)
        self.assertEqual(turns[-1]["content"], "query 14")


class TestWorkflowLearner(unittest.TestCase):
    """Test action recording, sequence pattern detection, and workflow approval."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_wf.db")
        self.store = MemoryStore(db_path=self.db_path)
        self.learner = WorkflowLearner(store=self.store)

        self.audit = AuditLogger(db_path=str(Path(self.temp_dir.name) / "test_audit.db"))
        self.policy = PolicyEngine()
        self.orch = Orchestrator(audit=self.audit, policy=self.policy)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_pattern_detection_creates_candidate(self):
        """Repeated execution of identical 2-step sequences forms a candidate workflow."""
        # First execution of Sequence: Step A -> Step B
        cand1 = self.learner.record_action("test", "system.get_cpu", {}, "CPU 10%", True)
        cand2 = self.learner.record_action("test", "system.get_memory", {}, "RAM 50%", True)
        self.assertIsNone(cand2)  # First occurrence, count = 1

        # Second execution of Sequence: Step A -> Step B
        self.learner.record_action("test", "system.get_cpu", {}, "CPU 12%", True)
        cand_found = self.learner.record_action("test", "system.get_memory", {}, "RAM 52%", True)

        self.assertIsNotNone(cand_found)
        self.assertEqual(cand_found["status"], "candidate")
        self.assertEqual(len(cand_found["steps"]), 2)
        self.assertEqual(cand_found["steps"][0]["tool"], "system.get_cpu")
        self.assertEqual(cand_found["steps"][1]["tool"], "system.get_memory")

    def test_02_candidate_not_executed_until_approved(self):
        """Candidates cannot be triggered by query before approval."""
        self.store.save_workflow_candidate(
            name="test_wf",
            trigger_pattern="cek spek lengkap",
            steps=[{"tool": "system.get_cpu", "args": {}}, {"tool": "system.get_memory", "args": {}}],
        )

        # Trigger search returns None for candidate
        matched = self.learner.match_approved_trigger("cek spek lengkap")
        self.assertIsNone(matched)

    def test_03_promote_candidate_to_approved(self):
        """User explicitly approves candidate, making it active."""
        wf_id = self.store.save_workflow_candidate(
            name="auto_cpu_mem",
            trigger_pattern="cpu mem",
            steps=[{"tool": "system.get_cpu", "args": {}}, {"tool": "system.get_memory", "args": {}}],
        )

        ok, msg = self.learner.approve_workflow(
            identifier=wf_id,
            name="cek_beban_sistem",
            trigger_pattern="cek beban sistem",
        )
        self.assertTrue(ok)

        # Now trigger matches
        matched = self.learner.match_approved_trigger("cek beban sistem")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["status"], "approved")
        self.assertEqual(matched["name"], "cek_beban_sistem")

    def test_04_execute_approved_workflow_success(self):
        """Execute all steps of an approved workflow through orchestrator."""
        wf_id = self.store.save_workflow_candidate(
            name="system_overview_flow",
            trigger_pattern="status sistem",
            steps=[{"tool": "system.get_cpu", "args": {}}, {"tool": "system.get_memory", "args": {}}],
        )
        self.learner.approve_workflow(wf_id)
        wf = self.learner.get_workflow(wf_id)

        res = self.learner.execute_workflow(wf, self.orch)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_steps"], 2)
        self.assertEqual(len(res["executed_steps"]), 2)

    def test_05_execute_workflow_aborts_on_policy_rejection(self):
        """If a step violates policy (L0), workflow aborts immediately."""
        wf_id = self.store.save_workflow_candidate(
            name="malicious_flow",
            trigger_pattern="bahaya",
            steps=[
                {"tool": "system.get_cpu", "args": {}},
                {"tool": "window.close", "args": {"process_name": "csrss.exe"}},  # L0 Protected
                {"tool": "system.get_memory", "args": {}},
            ],
        )
        self.learner.approve_workflow(wf_id)
        wf = self.learner.get_workflow(wf_id)

        res = self.learner.execute_workflow(wf, self.orch)
        self.assertFalse(res["ok"])
        self.assertEqual(res["failed_step"], 2)
        self.assertEqual(res["failed_tool"], "window.close")
        self.assertIn("Policy violation", res["error"])
        # Step 3 must NOT have executed
        self.assertEqual(len(res["executed_steps"]), 2)

    def test_06_reject_and_delete_workflow(self):
        """Workflows can be rejected or permanently removed."""
        wf_id = self.store.save_workflow_candidate(
            name="temp_wf",
            trigger_pattern="temp",
            steps=[{"tool": "system.get_cpu", "args": {}}],
        )

        ok_rej, _ = self.learner.reject_workflow(wf_id)
        self.assertTrue(ok_rej)
        self.assertEqual(self.learner.get_workflow(wf_id)["status"], "rejected")

        ok_del, _ = self.learner.delete_workflow(wf_id)
        self.assertTrue(ok_del)
        self.assertIsNone(self.learner.get_workflow(wf_id))


class TestMemoryToolsAndOrchestratorIntegration(unittest.TestCase):
    """Test registered memory & workflow tools and end-to-end Orchestrator integration."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "integration_audit.db")
        self.audit = AuditLogger(db_path=self.db_path)
        self.policy = PolicyEngine()
        self.orch = Orchestrator(audit=self.audit, policy=self.policy)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_all_phase12_tools_registered(self):
        """Verify all 7 new tools are registered in tool registry (total 66)."""
        tools = registry.list_tools()
        self.assertEqual(len(tools), 66)
        tool_names = {t.name for t in tools}
        expected = {
            "memory.remember",
            "memory.recall",
            "memory.forget",
            "memory.list",
            "workflow.list",
            "workflow.approve",
            "workflow.run",
        }
        for exp in expected:
            self.assertIn(exp, tool_names)

    def test_02_memory_tools_execution_via_orchestrator(self):
        """Execute memory tools through the real orchestrator."""
        # 1. Remember
        rem_res = self.orch.run_tool("memory.remember", {
            "category": "preference",
            "key": "theme",
            "value": "dark",
        })
        self.assertTrue(rem_res.ok)

        # 2. Recall
        rec_res = self.orch.run_tool("memory.recall", {
            "category": "preference",
            "key": "theme",
        })
        self.assertTrue(rec_res.ok)
        self.assertEqual(rec_res.data["value"], "dark")

        # 3. List
        list_res = self.orch.run_tool("memory.list", {"category": "preference"})
        self.assertTrue(list_res.ok)

        # 4. Forget
        forg_res = self.orch.run_tool("memory.forget", {
            "category": "preference",
            "key": "theme",
        })
        self.assertTrue(forg_res.ok)

    def test_03_orchestrator_natural_memory_command(self):
        """Natural memory commands are handled directly by Orchestrator."""
        res = self.orch.handle_request("project jarvis ada di D:\\project\\jarvis")
        self.assertEqual(res["route"], "memory")
        self.assertTrue(res["ok"])
        self.assertIn("jarvis", res["response"].lower())

    def test_04_folder_launcher_resolves_project_from_memory(self):
        """folder_launcher resolves custom project paths saved in memory."""
        from assistant.memory.manager import memory_manager
        from assistant.tools.launch.folder_launcher import resolve_folder

        # Remember custom project (using non-sensitive name)
        memory_manager.remember("project", "my_custom_project", str(Path(self.temp_dir.name)))

        resolved = resolve_folder("my_custom_project")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.resolve(), Path(self.temp_dir.name).resolve())

    def test_05_app_launcher_resolves_alias_from_memory(self):
        """app_launcher resolves custom aliases saved in memory."""
        from assistant.memory.manager import memory_manager
        from assistant.tools.launch.app_launcher import app_indexer

        # Remember custom alias
        memory_manager.remember("alias", "teks_editor", "notepad.exe")

        resolved = app_indexer.resolve("teks_editor")
        self.assertIsNotNone(resolved)
        self.assertIn("notepad", resolved.lower())


if __name__ == "__main__":
    unittest.main()

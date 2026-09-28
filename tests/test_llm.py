"""Unit tests for LLM client, planner, explainer, and tool selector (Phase 3)."""

import unittest
from assistant.llm.client import LLMClient
from assistant.llm.providers.mock import MockLLMClient
from assistant.llm.planner import LLMPlanner
from assistant.llm.explainer import LLMExplainer
from assistant.llm.tool_selector import ToolSelector
from assistant.core.orchestrator import Orchestrator


class BrokenLLMClient(LLMClient):
    """Simulates a model that returns invalid JSON on first attempt then recovers."""
    def __init__(self):
        self.attempts = 0

    def is_healthy(self) -> bool:
        return True

    def warm_up(self) -> bool:
        return True

    def generate(self, prompt, system=None, temperature=0.1, max_tokens=1024):
        return "Explanation"

    def generate_json(self, prompt, system, schema=None, temperature=0.1):
        self.attempts += 1
        if self.attempts == 1:
            raise ValueError("Invalid JSON syntax simulated")
        return {"type": "tool_call", "tool": "system.get_overview", "args": {}}


class TestLLMSubsystem(unittest.TestCase):
    def setUp(self):
        self.mock_llm = MockLLMClient()
        self.planner = LLMPlanner(self.mock_llm)
        self.explainer = LLMExplainer(self.mock_llm)
        self.selector = ToolSelector()

    def test_mock_client_health_and_generate(self):
        self.assertTrue(self.mock_llm.is_healthy())
        self.assertTrue(self.mock_llm.warm_up())
        text = self.mock_llm.generate("test prompt")
        self.assertIn("Apa yang ditemukan", text)

    def test_tool_selector_keyword_filtering(self):
        schemas_ram = self.selector.select("kenapa memori dan ram penuh")
        names_ram = [s["name"] for s in schemas_ram]
        self.assertIn("system.get_memory", names_ram)
        self.assertIn("process.list_top", names_ram)

        schemas_disk = self.selector.select("disk gw 100 persen")
        names_disk = [s["name"] for s in schemas_disk]
        self.assertIn("system.get_disk_activity", names_disk)

    def test_planner_tool_call_decision(self):
        plan = self.planner.plan("cek proses yang paling boros")
        self.assertEqual(plan.decision_type, "tool_call")
        self.assertEqual(plan.tool, "process.list_top")

    def test_planner_playbook_decision(self):
        plan = self.planner.plan("kenapa tadi malam laptop bsod")
        self.assertEqual(plan.decision_type, "playbook")
        self.assertEqual(plan.playbook, "bsod_crash_diagnosis")

    def test_planner_answer_decision(self):
        plan = self.planner.plan("halo siapa kamu")
        self.assertEqual(plan.decision_type, "answer")
        self.assertIn("Jarvis", plan.text)

    def test_planner_retry_on_invalid_json(self):
        broken_llm = BrokenLLMClient()
        planner = LLMPlanner(broken_llm)
        plan = planner.plan("cek spek sistem")
        self.assertEqual(plan.decision_type, "tool_call")
        self.assertEqual(plan.tool, "system.get_overview")
        self.assertEqual(broken_llm.attempts, 2)

    def test_explainer_formatting(self):
        res = self.explainer.explain("kenapa lemot", "CPU: 95%, RAM: 85%")
        self.assertIn("Apa yang ditemukan", res)
        self.assertIn("Kemungkinan penyebab", res)
        self.assertIn("Langkah berikutnya", res)

    def test_orchestrator_end_to_end_analysis(self):
        orch = Orchestrator(llm=self.mock_llm)
        # Fast path test
        res_fast = orch.handle_request("buka youtube")
        self.assertEqual(res_fast["route"], "fast")
        self.assertTrue(res_fast["ok"])

        # LLM analysis path test
        res_llm = orch.handle_request("cek spek laptop ini")
        self.assertEqual(res_llm["route"], "llm")
        self.assertEqual(res_llm["type"], "tool_call")
        self.assertEqual(res_llm["tool"], "system.get_overview")
        self.assertTrue(res_llm["ok"])
        self.assertIn("Apa yang ditemukan", res_llm["response"])


if __name__ == "__main__":
    unittest.main()

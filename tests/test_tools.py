"""Unit tests for all Phase 1 system tools."""

import unittest
from assistant.tools.registry import registry
from assistant.tools.base import Risk, ToolResult
import assistant.tools  # registers all tools


class TestPhase1Tools(unittest.TestCase):
    def test_registry_contains_10_tools(self):
        tool_names = registry.list_names()
        expected = [
            "process.list_top",
            "services.list",
            "startup.list_items",
            "system.get_cpu",
            "system.get_disk_activity",
            "system.get_disks",
            "system.get_drivers",
            "system.get_gpu_info",
            "system.get_memory",
            "system.get_overview",
        ]
        for name in expected:
            self.assertIn(name, tool_names)

    def test_all_phase1_tools_are_observe_risk(self):
        phase1_tools = {
            "system.get_overview", "system.get_cpu", "system.get_memory",
            "system.get_disks", "system.get_disk_activity", "process.list_top",
            "system.get_gpu_info", "system.get_drivers", "startup.list_items",
            "services.list",
        }
        for tool_def in registry.list_tools():
            if tool_def.name in phase1_tools:
                self.assertEqual(tool_def.risk, Risk.OBSERVE, f"Tool {tool_def.name} must be OBSERVE in Phase 1")
            elif tool_def.name.startswith("launch."):
                self.assertEqual(tool_def.risk, Risk.LOW_ACTION, f"Tool {tool_def.name} must be LOW_ACTION in Phase 2")

    def test_system_get_overview(self):
        res = registry.execute("system.get_overview")
        self.assertTrue(res.ok, res.error)
        self.assertIn("os", res.data)
        self.assertIn("cpu", res.data)
        self.assertIn("memory", res.data)
        self.assertIn("disks", res.data)
        self.assertTrue(len(res.summary) > 0)
        self.assertLessEqual(len(res.summary), 1500)

    def test_system_get_cpu(self):
        res = registry.execute("system.get_cpu", interval_s=0.2)
        self.assertTrue(res.ok, res.error)
        self.assertIn("total_percent", res.data)
        self.assertIn("per_core_percent", res.data)
        self.assertIsInstance(res.data["per_core_percent"], list)
        self.assertTrue(len(res.data["per_core_percent"]) > 0)

    def test_system_get_memory(self):
        res = registry.execute("system.get_memory")
        self.assertTrue(res.ok, res.error)
        self.assertIn("physical_total", res.data)
        self.assertIn("physical_used", res.data)
        self.assertIn("commit_total", res.data)

    def test_system_get_disks(self):
        res = registry.execute("system.get_disks")
        self.assertTrue(res.ok, res.error)
        self.assertIn("volumes", res.data)
        self.assertTrue(len(res.data["volumes"]) > 0)

    def test_system_get_disk_activity(self):
        res = registry.execute("system.get_disk_activity", duration_s=1.0)
        self.assertTrue(res.ok, res.error)
        self.assertIn("io_throughput", res.data)

    def test_process_list_top_memory(self):
        res = registry.execute("process.list_top", by="memory", count=5)
        self.assertTrue(res.ok, res.error)
        procs = res.data.get("processes", [])
        self.assertLessEqual(len(procs), 5)
        self.assertTrue(len(procs) > 0)

    def test_process_list_top_cpu(self):
        res = registry.execute("process.list_top", by="cpu", count=5, sample_interval_s=0.2)
        self.assertTrue(res.ok, res.error)
        procs = res.data.get("processes", [])
        self.assertLessEqual(len(procs), 5)

    def test_system_get_gpu_info(self):
        res = registry.execute("system.get_gpu_info")
        self.assertTrue(res.ok, res.error)
        self.assertIn("adapters", res.data)
        self.assertTrue(len(res.data["adapters"]) > 0)

    def test_system_get_drivers(self):
        res = registry.execute("system.get_drivers", limit=5)
        self.assertTrue(res.ok, res.error)
        self.assertIn("drivers", res.data)

    def test_startup_list_items(self):
        res = registry.execute("startup.list_items")
        self.assertTrue(res.ok, res.error)
        self.assertIn("startup_entries", res.data)

    def test_services_list(self):
        res = registry.execute("services.list", limit=10, status="running")
        self.assertTrue(res.ok, res.error)
        self.assertIn("services", res.data)
        self.assertLessEqual(len(res.data["services"]), 10)


if __name__ == "__main__":
    unittest.main()

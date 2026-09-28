"""Tool subset selector to minimize LLM prompt size and latency (Section 10.2)."""

from __future__ import annotations

from typing import Any
from assistant.tools.registry import registry, ToolRegistry


class ToolSelector:
    """Pre-filters the tool catalogue to supply only relevant tools to the planner."""

    KEYWORD_MAPPINGS = {
        "memory": ["system.get_memory", "process.list_top", "system.get_overview"],
        "ram": ["system.get_memory", "process.list_top", "system.get_overview"],
        "memori": ["system.get_memory", "process.list_top", "system.get_overview"],
        "lemot": ["system.get_cpu", "system.get_memory", "process.list_top", "system.get_disk_activity"],
        "hang": ["system.get_cpu", "system.get_memory", "process.list_top"],
        "freeze": ["system.get_cpu", "system.get_memory", "process.list_top"],
        "cpu": ["system.get_cpu", "process.list_top", "system.get_overview"],
        "processor": ["system.get_cpu", "process.list_top"],
        "proses": ["process.list_top", "system.get_cpu"],
        "process": ["process.list_top", "system.get_cpu"],
        "panas": ["system.get_cpu", "system.get_gpu_info"],
        "throttling": ["system.get_cpu", "system.get_gpu_info"],
        "disk": ["system.get_disks", "system.get_disk_activity", "process.list_top"],
        "hdd": ["system.get_disks", "system.get_disk_activity"],
        "ssd": ["system.get_disks", "system.get_disk_activity"],
        "storage": ["system.get_disks", "system.get_disk_activity"],
        "penyimpanan": ["system.get_disks", "system.get_disk_activity"],
        "100%": ["system.get_disk_activity", "process.list_top", "system.get_cpu"],
        "gpu": ["system.get_gpu_info", "system.get_drivers"],
        "vga": ["system.get_gpu_info", "system.get_drivers"],
        "nvidia": ["system.get_gpu_info", "system.get_drivers"],
        "driver": ["system.get_drivers", "system.get_gpu_info"],
        "startup": ["startup.list_items", "services.list"],
        "service": ["services.list", "startup.list_items"],
        "layanan": ["services.list", "startup.list_items"],
        "search": ["web.search"],
        "cari": ["web.search"],
        "web": ["web.search", "web.fetch"],
        "fetch": ["web.fetch"],
        "game": ["web.pcgamingwiki"],
        "pcgamingwiki": ["web.pcgamingwiki"],
        "save": ["web.pcgamingwiki"],
        "config": ["web.pcgamingwiki"],
    }

    # Core default subset when query is generic
    DEFAULT_SUBSET = [
        "system.get_overview",
        "system.get_cpu",
        "system.get_memory",
        "system.get_disks",
        "process.list_top",
    ]

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self.registry = tool_registry or registry

    def select(self, query: str) -> list[dict[str, Any]]:
        """Select a concise subset of tool JSON schemas based on user query keywords."""
        q_lower = query.lower()
        selected_names: set[str] = set()

        for kw, tools in self.KEYWORD_MAPPINGS.items():
            if kw in q_lower:
                selected_names.update(tools)

        if not selected_names:
            selected_names.update(self.DEFAULT_SUBSET)

        # Retrieve schemas
        schemas = []
        for name in sorted(list(selected_names)):
            t_def = self.registry.get(name)
            if t_def:
                schemas.append(t_def.get_json_schema())

        return schemas


tool_selector = ToolSelector()

"""Initialize and register all available tools."""

from assistant.tools.base import Risk, ToolDefinition, ToolResult, tool
from assistant.tools.registry import registry

# Phase 1 tools
from assistant.tools.system.overview import get_overview
from assistant.tools.system.cpu import get_cpu
from assistant.tools.system.memory import get_memory
from assistant.tools.system.disks import get_disks, get_disk_activity
from assistant.tools.system.gpu import get_gpu_info
from assistant.tools.system.drivers import get_drivers
from assistant.tools.system.startup import list_startup_items
from assistant.tools.system.services import list_services
from assistant.tools.process.top import list_top_processes

# Register all Phase 1 tools
for tool_def in [
    get_overview,
    get_cpu,
    get_memory,
    get_disks,
    get_disk_activity,
    list_top_processes,
    get_gpu_info,
    get_drivers,
    list_startup_items,
    list_services,
]:
    registry.register(tool_def)

__all__ = [
    "registry",
    "tool",
    "ToolResult",
    "Risk",
    "ToolDefinition",
]

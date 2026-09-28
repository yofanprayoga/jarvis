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

# Phase 2 tools
from assistant.tools.launch.browser import open_url, web_search, youtube_search, update_site_alias
from assistant.tools.launch.app_launcher import open_app
from assistant.tools.launch.folder_launcher import open_folder

# Phase 4 tools
from assistant.tools.dumps.bugcheck_table import bugcheck_lookup
from assistant.tools.dumps.dump_tools import (
    get_dump_config,
    list_dumps,
    analyze_dump,
    get_updates_history,
    get_reliability_records,
)
from assistant.tools.events.event_query import events_query, get_crash_summary

# Phase 6 tools
from assistant.tools.web.web_tools import web_search_tool, web_fetch_tool, pcgw_tool

# Register all tools
for tool_def in [
    # System observation (L1)
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
    # Fast path launching (L2)
    open_url,
    web_search,
    youtube_search,
    update_site_alias,
    open_app,
    open_folder,
    # Phase 4 Diagnostics (L1 / L2)
    bugcheck_lookup,
    get_dump_config,
    list_dumps,
    analyze_dump,
    get_updates_history,
    get_reliability_records,
    events_query,
    get_crash_summary,
    # Phase 6 Web Research (L1)
    web_search_tool,
    web_fetch_tool,
    pcgw_tool,
]:
    # Prevent duplicate registration if reloaded
    if registry.get(tool_def.name) is None:
        registry.register(tool_def)

__all__ = [
    "registry",
    "tool",
    "ToolResult",
    "Risk",
    "ToolDefinition",
]

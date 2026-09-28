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

# Phase 7 & 8 tools
from assistant.tools.games.game_tools import list_installed_games, find_save_and_config
from assistant.tools.files.file_tools import (
    inspect_file_tool,
    read_text_tool,
    backup_file_tool,
    propose_edit_tool,
    apply_edit_tool,
    restore_backup_tool,
)
from assistant.tools.apps.app_tools import resolve_app_tool, inspect_app_tool, get_cli_help_tool

# Phase 9A tools
from assistant.tools.screen.screen_tools import capture_screen_tool, ocr_screen_tool, inspect_window_tool

# Phase 9B & 9C tools
from assistant.tools.browser.browser_tools import (
    browser_open_tool,
    browser_read_tool,
    browser_screenshot_tool,
    browser_find_links_tool,
    browser_click_tool,
    browser_type_tool,
)


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
    # Phase 7 Games, Files & Apps (L1 / L2)
    list_installed_games,
    find_save_and_config,
    inspect_file_tool,
    read_text_tool,
    backup_file_tool,
    resolve_app_tool,
    inspect_app_tool,
    get_cli_help_tool,
    # Phase 8 Controlled Modifications (L1 / L3)
    propose_edit_tool,
    apply_edit_tool,
    restore_backup_tool,
    # Phase 9A Screen Reading & Local OCR (L1)
    inspect_window_tool,
    capture_screen_tool,
    ocr_screen_tool,
    # Phase 9B & 9C Browser Automation (L1 / L2 / L3)
    browser_open_tool,
    browser_read_tool,
    browser_screenshot_tool,
    browser_find_links_tool,
    browser_click_tool,
    browser_type_tool,
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

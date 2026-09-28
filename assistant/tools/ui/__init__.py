"""UI tools package (Phase 9A + Phase 10A)."""

from assistant.tools.ui.window_inspector import get_foreground_window_info
from assistant.tools.ui.uia_client import UiaError, uia_session
from assistant.tools.ui.tree_inspector import inspect_tree, render_tree_text
from assistant.tools.ui.control_finder import find_controls, get_control_by_path
from assistant.tools.ui.ui_tools import (
    inspect_tree_tool,
    find_control_tool,
    get_control_info_tool,
)

__all__ = [
    "get_foreground_window_info",
    "UiaError",
    "uia_session",
    "inspect_tree",
    "render_tree_text",
    "find_controls",
    "get_control_by_path",
    "inspect_tree_tool",
    "find_control_tool",
    "get_control_info_tool",
]

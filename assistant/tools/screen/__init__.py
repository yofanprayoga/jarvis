"""Screen tools package (Phase 9A)."""

from assistant.tools.screen.desktop import attach_input_desktop, capture_screen, get_window_bounds
from assistant.tools.screen.ocr import perform_ocr
from assistant.tools.screen.screen_tools import capture_screen_tool, ocr_screen_tool, inspect_window_tool

__all__ = [
    "attach_input_desktop",
    "capture_screen",
    "get_window_bounds",
    "perform_ocr",
    "capture_screen_tool",
    "ocr_screen_tool",
    "inspect_window_tool",
]

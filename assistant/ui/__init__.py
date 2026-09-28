"""UI subsystem package for Jarvis."""

from assistant.ui.chat_window import ChatWindow
from assistant.ui.confirm_dialog import request_confirmation
from assistant.ui.hotkey import GlobalHotkeyListener
from assistant.ui.reports import save_markdown_report, get_reports_dir
from assistant.ui.tray import TrayApplication, run_tray_app

__all__ = [
    "ChatWindow",
    "request_confirmation",
    "GlobalHotkeyListener",
    "save_markdown_report",
    "get_reports_dir",
    "TrayApplication",
    "run_tray_app",
]

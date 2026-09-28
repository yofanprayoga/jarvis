"""Browser automation package (Phase 9B & 9C)."""

from assistant.tools.browser.manager import BrowserManager, browser_manager
from assistant.tools.browser.safety import (
    classify_action_risk,
    is_sensitive_field,
    wrap_untrusted_content,
)
from assistant.tools.browser.browser_tools import (
    browser_open_tool,
    browser_read_tool,
    browser_screenshot_tool,
    browser_find_links_tool,
    browser_click_tool,
    browser_type_tool,
)

__all__ = [
    "BrowserManager",
    "browser_manager",
    "classify_action_risk",
    "is_sensitive_field",
    "wrap_untrusted_content",
    "browser_open_tool",
    "browser_read_tool",
    "browser_screenshot_tool",
    "browser_find_links_tool",
    "browser_click_tool",
    "browser_type_tool",
]

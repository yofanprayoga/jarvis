"""Browser Lifecycle Manager with Isolated Context and Idle Cleanup (Phase 9B)."""

from __future__ import annotations

import atexit
import threading
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)


class BrowserManager:
    """Manages an isolated Playwright browser instance, lifecycle, and idle cleanup."""

    _instance: Optional[BrowserManager] = None
    _lock = threading.RLock()

    def __init__(self, profile_dir: Optional[Path] = None, idle_timeout_s: float = 300.0) -> None:
        self.profile_dir = profile_dir or (Path("data/browser_profile").resolve())
        self.idle_timeout_s = idle_timeout_s
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._current_page: Optional[Page] = None
        self._last_active: float = 0.0

        # Ensure isolated profile directory exists
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # Register exit handler
        atexit.register(self.close)

    @classmethod
    def get_instance(cls) -> BrowserManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def is_active(self) -> bool:
        return self._context is not None

    def _ensure_active(self) -> Page:
        """Ensure Playwright context and page are active. Launches lazily if needed."""
        with self._lock:
            self._last_active = time.time()
            if self._context is not None and self._current_page is not None and not self._current_page.is_closed():
                return self._current_page

            if self._playwright is None:
                self._playwright = sync_playwright().start()

            # Launch persistent isolated context in dedicated directory
            # NEVER uses user's Chrome/Edge personal profile
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 JarvisAssistant/1.0",
                accept_downloads=False,
            )

            # Get first page or create new
            pages = self._context.pages
            if pages:
                self._current_page = pages[0]
            else:
                self._current_page = self._context.new_page()

            return self._current_page

    def get_page(self) -> Page:
        """Get the active browser page, launching if necessary."""
        return self._ensure_active()

    def update_activity(self) -> None:
        """Mark recent browser activity."""
        self._last_active = time.time()

    def cleanup_idle(self, max_idle_s: Optional[float] = None) -> bool:
        """Close browser if idle time exceeds threshold. Returns True if closed."""
        threshold = max_idle_s if max_idle_s is not None else self.idle_timeout_s
        with self._lock:
            if not self.is_active:
                return False

            idle_duration = time.time() - self._last_active
            if idle_duration >= threshold:
                self.close()
                return True
            return False

    def close(self) -> None:
        """Gracefully close browser context and stop Playwright process."""
        with self._lock:
            if self._context is not None:
                try:
                    self._context.close()
                except Exception:
                    pass
                self._context = None
                self._current_page = None

            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None


# Global singleton instance
browser_manager = BrowserManager.get_instance()

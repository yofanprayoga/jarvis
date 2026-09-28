"""Windows native global hotkey listener via ctypes RegisterHotKey (Section 13)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Optional

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class GlobalHotkeyListener:
    """Listens for a global Windows hotkey in a dedicated background thread."""

    def __init__(
        self,
        callback: Callable[[], None],
        vk_key: int = ord("J"),
        modifiers: int = MOD_CONTROL | MOD_SHIFT,
        hotkey_id: int = 101,
    ) -> None:
        self.callback = callback
        self.vk_key = vk_key
        self.modifiers = modifiers
        self.hotkey_id = hotkey_id
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._running = False

    def start(self) -> bool:
        """Start listening for the global hotkey."""
        if self._running:
            return True

        self._running = True
        started_event = threading.Event()
        success = [False]

        def _loop():
            self._thread_id = kernel32.GetCurrentThreadId()
            # Register hotkey
            ok = user32.RegisterHotKey(
                None,
                self.hotkey_id,
                self.modifiers | MOD_NOREPEAT,
                self.vk_key,
            )
            success[0] = bool(ok)
            started_event.set()

            if not ok:
                self._running = False
                return

            msg = wintypes.MSG()
            while self._running:
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res <= 0:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    if self.callback:
                        try:
                            self.callback()
                        except Exception:
                            pass
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            user32.UnregisterHotKey(None, self.hotkey_id)

        self._thread = threading.Thread(target=_loop, daemon=True, name="JarvisHotkeyThread")
        self._thread.start()

        started_event.wait(timeout=2.0)
        return success[0]

    def stop(self) -> None:
        """Stop listening and clean up hotkey registration."""
        if not self._running:
            return
        self._running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

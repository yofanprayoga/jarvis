"""Active window and foreground application inspection (Phase 9A)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Optional
import psutil

from assistant.tools.screen.desktop import attach_input_desktop


def get_foreground_window_info(target_hwnd: Optional[int] = None) -> dict[str, Any]:
    """Inspect active foreground window or specified window handle.
    
    Returns structured metadata including window handle, title, class name, process ID,
    process executable name, path, and window bounds.
    """
    attach_input_desktop()

    user32 = ctypes.windll.user32
    hwnd = target_hwnd if target_hwnd is not None else user32.GetForegroundWindow()

    if not hwnd or not user32.IsWindow(hwnd):
        return {
            "exists": False,
            "hwnd": 0,
            "title": "",
            "process_name": "None",
            "message": "Tidak ada jendela aktif yang terdeteksi (layar desktop atau lock screen).",
        }

    # Window Title
    length = user32.GetWindowTextLengthW(hwnd)
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
    else:
        title = ""

    # Class Name
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)
    class_name = class_buf.value

    # Process ID
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_id = int(pid.value)

    # Process details via psutil
    proc_name = "Unknown"
    proc_exe = "Unknown"
    if process_id:
        try:
            p = psutil.Process(process_id)
            proc_name = p.name()
            proc_exe = p.exe()
        except Exception:
            pass

    # Bounds
    rect = wintypes.RECT()
    bounds = {}
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        bounds = {
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        }

    is_minimized = bool(user32.IsIconic(hwnd))
    is_maximized = bool(user32.IsZoomed(hwnd))
    is_visible = bool(user32.IsWindowVisible(hwnd))

    return {
        "exists": True,
        "hwnd": hwnd,
        "hwnd_hex": hex(hwnd),
        "title": title,
        "class_name": class_name,
        "pid": process_id,
        "thread_id": int(tid),
        "process_name": proc_name,
        "exe_path": proc_exe,
        "bounds": bounds,
        "is_minimized": is_minimized,
        "is_maximized": is_maximized,
        "is_visible": is_visible,
        "is_foreground": hwnd == user32.GetForegroundWindow(),
    }

"""Native Windows window lifecycle and focus management (Phase 10C).

Provides safe window discovery, activation, restoring, and closing.
Safety rules:
- Normal close uses WM_CLOSE (PostMessageW) — NEVER force-kill / TerminateProcess.
- Protected Windows core processes (explorer, csrss, lsass, etc.) are strictly L0 FORBIDDEN.
- Consequential / important applications (IDEs, office apps, database, system tools)
  require explicit confirmation (L3 confirmed=True).
- Never bypass UAC, Secure Desktop, or UIPI privilege boundaries.
"""

from __future__ import annotations

import ctypes
from ctypes import (
    POINTER,
    WINFUNCTYPE,
    byref,
    c_int,
    c_long,
    c_ulong,
    create_unicode_buffer,
    sizeof,
    wintypes,
)
import time
from typing import Any, Optional

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

SW_RESTORE = 9
SW_SHOW = 5
SW_SHOWNA = 8
WM_CLOSE = 0x0010

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# High-consequence applications requiring L3 confirmation to close
CONSEQUENTIAL_PROCESS_NAMES = [
    "code.exe",
    "devenv.exe",
    "pycharm64.exe",
    "idea64.exe",
    "antigravity",
    "winword.exe",
    "excel.exe",
    "powerpnt.exe",
    "photoshop.exe",
    "premiere.exe",
    "dbeaver.exe",
    "pgadmin4.exe",
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
    "windowsterminal.exe",
    "bash.exe",
]

# High-consequence window title indicators
CONSEQUENTIAL_KEYWORDS_TITLE = [
    "visual studio",
    "vs code",
    "pycharm",
    "intellij",
    "excel",
    "word",
    "powerpoint",
    "photoshop",
    "premiere",
    "dbeaver",
    "pgadmin",
    "terminal",
    "powershell",
    "bash",
]

# Protected Windows core processes — CLOSING FORBIDDEN (L0)
PROTECTED_CORE_PROCESSES = [
    "csrss.exe",
    "lsass.exe",
    "services.exe",
    "smss.exe",
    "wininit.exe",
    "winlogon.exe",
    "explorer.exe",
    "system",
    "svchost.exe",
    "dwm.exe",
    "fontdrvhost.exe",
    "taskhostw.exe",
    "consent.exe",
    "logonui.exe",
    "taskmgr.exe",
]


_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def _get_process_name_by_pid(pid: int) -> str:
    """Retrieve process executable name by PID using native QueryFullProcessImageNameW."""
    if pid <= 4:
        return "system"

    h_proc = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return ""

    try:
        buf = create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if _kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, byref(size)):
            full_path = buf.value
            return full_path.split("\\")[-1].lower()
        return ""
    finally:
        _kernel32.CloseHandle(h_proc)


def get_window_metadata(hwnd: int) -> dict[str, Any]:
    """Retrieve full structural metadata for a window handle."""
    if not hwnd or not _user32.IsWindow(hwnd):
        return {"valid": False, "hwnd": hwnd}

    title_buf = create_unicode_buffer(512)
    _user32.GetWindowTextW(hwnd, title_buf, 512)
    title = title_buf.value

    cls_buf = create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, cls_buf, 256)
    cls_name = cls_buf.value

    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, byref(pid))
    proc_name = _get_process_name_by_pid(pid.value)

    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, byref(rect))

    is_minimized = bool(_user32.IsIconic(hwnd))
    is_visible = bool(_user32.IsWindowVisible(hwnd))
    is_enabled = bool(_user32.IsWindowEnabled(hwnd))

    return {
        "valid": True,
        "hwnd": hwnd,
        "title": title,
        "class_name": cls_name,
        "process_id": pid.value,
        "process_name": proc_name,
        "is_minimized": is_minimized,
        "is_visible": is_visible,
        "is_enabled": is_enabled,
        "rect": {
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
            "width": max(0, rect.right - rect.left),
            "height": max(0, rect.bottom - rect.top),
        },
    }


def find_window_by_query(
    query: Optional[str] = None,
    process_name: Optional[str] = None,
) -> Optional[int]:
    """Find a top-level window by title substring or process name."""
    found_hwnd: Optional[int] = None
    q_lower = query.lower().strip() if query else ""
    p_lower = process_name.lower().strip() if process_name else ""

    WNDENUMPROC = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def enum_cb(h: int, lp: int) -> bool:
        nonlocal found_hwnd
        if not _user32.IsWindowVisible(h):
            return True

        title_buf = create_unicode_buffer(512)
        _user32.GetWindowTextW(h, title_buf, 512)
        title = title_buf.value.lower()

        if q_lower and q_lower in title:
            found_hwnd = h
            return False

        if p_lower:
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(h, byref(pid))
            pname = _get_process_name_by_pid(pid.value)
            if p_lower in pname:
                found_hwnd = h
                return False

        return True

    cb = WNDENUMPROC(enum_cb)
    _user32.EnumWindows(cb, 0)
    return found_hwnd


def is_consequential_window(metadata: dict[str, Any]) -> tuple[bool, str]:
    """Determine if closing this window has high or irreversible consequences (L3)."""
    pname = str(metadata.get("process_name", "")).lower()
    title = str(metadata.get("title", "")).lower()

    # Check protected processes (L0)
    for prot in PROTECTED_CORE_PROCESSES:
        if pname == prot or prot in pname:
            return False, f"Protected Windows system process ('{prot}') — L0 FORBIDDEN"

    # Check consequential processes (L3)
    for cname in CONSEQUENTIAL_PROCESS_NAMES:
        if cname in pname or cname in title:
            return True, f"Application '{pname or cname}' may hold unsaved work or ongoing tasks (L3 CONFIRM required)"

    # Check consequential window title keywords (e.g. Visual Studio, VS Code, Terminal)
    for ckw in CONSEQUENTIAL_KEYWORDS_TITLE:
        if ckw in title:
            return True, f"Application window '{title}' may hold unsaved work or ongoing tasks (L3 CONFIRM required)"

    # Check dirty document indicators in title (e.g. "*document", "unsaved", "untitled*")
    if "*" in title or "unsaved" in title or "modified" in title:
        return True, "Window title indicates unsaved modifications (L3 CONFIRM required)"

    return False, ""


def is_protected_process_window(metadata: dict[str, Any]) -> tuple[bool, str]:
    """Determine if a window belongs to a protected system process (L0)."""
    pname = str(metadata.get("process_name", "")).lower()
    title = str(metadata.get("title", "")).lower()

    for prot in PROTECTED_CORE_PROCESSES:
        if pname == prot or (prot.endswith(".exe") and prot in pname):
            return True, f"Target belongs to protected system process '{prot}' (L0 FORBIDDEN)"

    # Check protected security UI window titles specifically
    for ptitle in ("windows security", "user account control", "credential prompt", "windows sign-in"):
        if ptitle in title:
            return True, f"Target window '{title}' matches protected security UI '{ptitle}' (L0 FORBIDDEN)"

    return False, ""


def activate_window(hwnd: int) -> bool:
    """Safely restore and bring target window to the foreground."""
    if not hwnd or not _user32.IsWindow(hwnd):
        return False

    # Restore if minimized
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.05)
    else:
        _user32.ShowWindow(hwnd, SW_SHOW)

    # Bring to foreground
    _user32.BringWindowToTop(hwnd)
    ok = bool(_user32.SetForegroundWindow(hwnd))
    time.sleep(0.05)
    return ok or bool(_user32.IsWindow(hwnd))


def close_window_safely(hwnd: int) -> bool:
    """Send WM_CLOSE to allow the window to perform clean exit or save prompt.

    NEVER force-kills the process.
    """
    if not hwnd or not _user32.IsWindow(hwnd):
        return False

    # Post WM_CLOSE message asynchronously
    ok = bool(_user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    return ok

"""Coordinate bounds safety and validation for mouse actions (Phase 10C).

Enforces:
1. Target window is valid, visible, and not minimized.
2. Coordinates strictly reside within target window boundaries.
3. Multi-monitor / virtual screen boundary verification.
4. Rejection of coordinates targeted at elevated, protected, or security windows.
5. No uncontrolled or out-of-bounds mouse movement.
"""

from __future__ import annotations

import ctypes
from ctypes import byref, wintypes
from typing import Tuple

from assistant.tools.ui.window_manager import (
    get_window_metadata,
    is_protected_process_window,
)

_user32 = ctypes.windll.user32

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


def get_virtual_screen_bounds() -> tuple[int, int, int, int]:
    """Retrieve virtual desktop boundaries covering all connected monitors."""
    v_left = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    v_top = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    v_width = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    v_height = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return v_left, v_top, v_left + v_width, v_top + v_height


def validate_click_coordinates(
    hwnd: int,
    x: int,
    y: int,
    is_relative: bool = False,
) -> Tuple[bool, int, int, str]:
    """Validate target click coordinates against window and virtual desktop boundaries.

    Args:
        hwnd: Target window handle.
        x: X-coordinate (screen-absolute or window-relative).
        y: Y-coordinate (screen-absolute or window-relative).
        is_relative: If True, (x, y) are offsets from top-left of target window.

    Returns:
        (is_valid, absolute_x, absolute_y, error_message)
    """
    if not hwnd or not _user32.IsWindow(hwnd):
        return False, 0, 0, f"HWND {hwnd} tidak valid atau window sudah tertutup."

    meta = get_window_metadata(hwnd)
    if not meta.get("valid"):
        return False, 0, 0, "Gagal membaca metadata window target."

    # 1. Check protected process (L0 boundary)
    is_prot, prot_reason = is_protected_process_window(meta)
    if is_prot:
        return False, 0, 0, f"Tindakan klik ditolak (L0): {prot_reason}"

    # 2. Check minimized state
    if meta.get("is_minimized"):
        return (
            False,
            0,
            0,
            f"Window '{meta.get('title')}' sedang dalam status diminimalkan. "
            f"Harus diaktifkan/direstore terlebih dahulu dengan window.activate.",
        )

    # 3. Check visibility
    if not meta.get("is_visible"):
        return False, 0, 0, f"Window '{meta.get('title')}' tidak terlihat (invisible/hidden)."

    rect = meta.get("rect", {})
    w_left = rect.get("left", 0)
    w_top = rect.get("top", 0)
    w_right = rect.get("right", 0)
    w_bottom = rect.get("bottom", 0)

    # Calculate absolute coordinates
    if is_relative:
        abs_x = w_left + x
        abs_y = w_top + y
    else:
        abs_x = x
        abs_y = y

    # 4. Strict window bounds check
    if not (w_left <= abs_x < w_right and w_top <= abs_y < w_bottom):
        return (
            False,
            abs_x,
            abs_y,
            f"Koordinat ({abs_x}, {abs_y}) berada di luar batas window "
            f"[{w_left}, {w_top}, {w_right}, {w_bottom}]. Pelanggaran keselamatan koordinat.",
        )

    # 5. Virtual desktop multi-monitor check
    v_left, v_top, v_right, v_bottom = get_virtual_screen_bounds()
    if not (v_left <= abs_x < v_right and v_top <= abs_y < v_bottom):
        return (
            False,
            abs_x,
            abs_y,
            f"Koordinat ({abs_x}, {abs_y}) berada di luar batas virtual desktop display.",
        )

    return True, abs_x, abs_y, ""

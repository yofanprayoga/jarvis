"""Native Windows desktop screen capture and input desktop attachment (Section 6 & Phase 9A)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import datetime
import hashlib
import os
import uuid
from pathlib import Path
from typing import Any, Optional, Tuple

from PIL import Image, ImageGrab


def attach_input_desktop() -> bool:
    """Attach the current thread to the interactive user input desktop (WinSta0\\Default).
    
    Required on Windows when running in subprocesses, background tasks, or console sessions
    to access the desktop device context and window handles without access violation.
    """
    user32 = ctypes.windll.user32
    # MAXIMUM_ALLOWED (0x01FF) or DESKTOP_READOBJECTS | DESKTOP_WRITEOBJECTS (0x0001 | 0x0002)
    hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
    if hdesk:
        res = user32.SetThreadDesktop(hdesk)
        return bool(res)
    return False


def get_window_bounds(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Get the bounding rectangle (left, top, right, bottom) for a window handle."""
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return None

    rect = wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w > 0 and h > 0:
            return (rect.left, rect.top, rect.right, rect.bottom)
    return None


def capture_screen(
    bbox: Optional[Tuple[int, int, int, int]] = None,
    hwnd: Optional[int] = None,
    output_dir: str | Path = "data/cache/screen",
) -> dict[str, Any]:
    """Capture the full desktop or a specific window and save to a temporary PNG file.
    
    Returns structured metadata including image path, resolution, SHA-256 hash, and untrusted flag.
    Does NOT record continuously; only executes on explicit call.
    """
    attach_input_desktop()

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    target_type = "desktop"
    crop_box = bbox

    # If hwnd specified, use its bounding box
    if hwnd:
        bounds = get_window_bounds(hwnd)
        if not bounds:
            raise ValueError(f"Window handle {hwnd} tidak valid atau tidak memiliki ukuran.")
        crop_box = bounds
        target_type = f"window_hwnd_{hwnd}"

    try:
        # Capture screen using Pillow with thread desktop attached
        if crop_box:
            img = ImageGrab.grab(bbox=crop_box)
        else:
            img = ImageGrab.grab()
    except Exception as e:
        raise RuntimeError(f"Gagal mengambil tangkapan layar (Screen capture failed): {e}")

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_id = uuid.uuid4().hex[:6]
    filename = f"capture_{timestamp_str}_{file_id}.png"
    target_file = out_path / filename

    img.save(target_file, format="PNG")

    # Compute hash of captured image
    file_bytes = target_file.read_bytes()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    return {
        "image_path": str(target_file.resolve()),
        "filename": filename,
        "width": img.width,
        "height": img.height,
        "size_bytes": len(file_bytes),
        "sha256": file_hash,
        "timestamp": datetime.datetime.now().isoformat(),
        "target_type": target_type,
        "bbox": crop_box,
        "untrusted": True,
    }

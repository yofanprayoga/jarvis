"""Native Windows SendInput wrappers for keyboard and mouse fallback (Phase 10C).

Provides controlled, low-level keyboard and mouse simulation via user32.SendInput.
Safety rules:
- Strictly bound to verified window coordinates (no uncontrolled mouse movement).
- Sensitive credentials / passwords strictly blocked before typing.
- No global hooks, no arbitrary background automation.
"""

from __future__ import annotations

import ctypes
from ctypes import (
    POINTER,
    Structure,
    Union,
    byref,
    c_long,
    c_ulonglong,
    sizeof,
    wintypes,
)
import time
from typing import Optional, Sequence

_user32 = ctypes.windll.user32

# ──────────────────────────────────────────────────────────────────────────────
# SendInput C Structures (64-bit Windows layout: sizeof(INPUT) == 40)
# ──────────────────────────────────────────────────────────────────────────────

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000

ULONG_PTR = c_ulonglong


class MOUSEINPUT(Structure):
    _fields_ = [
        ("dx", c_long),
        ("dy", c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", INPUT_UNION),
    ]


_user32.SendInput.argtypes = [wintypes.UINT, POINTER(INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT


# ──────────────────────────────────────────────────────────────────────────────
# Virtual Key Constants & Mapping
# ──────────────────────────────────────────────────────────────────────────────

VK_MAP: dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "\n": 0x0D,
    "tab": 0x09,
    "\t": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "bksp": 0x08,
    "space": 0x20,
    " ": 0x20,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "left": 0x25,
    "right": 0x27,
    "up": 0x26,
    "down": 0x28,
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
    "super": 0x5B,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}


def _make_key_input(vk: int, is_up: bool = False, is_extended: bool = False) -> INPUT:
    """Create a single KEYBDINPUT structure."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    flags = KEYEVENTF_KEYUP if is_up else KEYEVENTF_KEYDOWN
    if is_extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _make_unicode_input(char: str, is_up: bool = False) -> INPUT:
    """Create a unicode character input structure."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    flags = KEYEVENTF_UNICODE
    if is_up:
        flags |= KEYEVENTF_KEYUP
    inp.u.ki = KEYBDINPUT(wVk=0, wScan=ord(char), dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


# ──────────────────────────────────────────────────────────────────────────────
# Public Keyboard Functions
# ──────────────────────────────────────────────────────────────────────────────

def send_key(key_name: str) -> bool:
    """Press and release a single named key (e.g. 'enter', 'tab', 'esc', 'f5')."""
    k = key_name.lower().strip()
    vk = VK_MAP.get(k)
    if vk is None:
        if len(k) == 1 and k.isalnum():
            vk = ord(k.upper())
        else:
            return False

    down = _make_key_input(vk, is_up=False)
    up = _make_key_input(vk, is_up=True)
    inputs = (INPUT * 2)(down, up)
    sent = _user32.SendInput(2, inputs, sizeof(INPUT))
    return sent == 2


def send_key_combo(combo: str) -> bool:
    """Press and release a combination of keys (e.g. 'ctrl+s', 'ctrl+shift+n', 'alt+f4').

    Presses all modifiers in order, presses and releases the main key, then releases modifiers.
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        return False

    vks: list[int] = []
    for p in parts:
        vk = VK_MAP.get(p)
        if vk is None and len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        if vk is None:
            return False
        vks.append(vk)

    # Modifiers are all parts except the last
    modifiers = vks[:-1]
    main_key = vks[-1]

    input_list: list[INPUT] = []
    # 1. Modifiers down
    for m in modifiers:
        input_list.append(_make_key_input(m, is_up=False))
    # 2. Main key down
    input_list.append(_make_key_input(main_key, is_up=False))
    # 3. Main key up
    input_list.append(_make_key_input(main_key, is_up=True))
    # 4. Modifiers up (reverse order)
    for m in reversed(modifiers):
        input_list.append(_make_key_input(m, is_up=True))

    arr = (INPUT * len(input_list))(*input_list)
    sent = _user32.SendInput(len(input_list), arr, sizeof(INPUT))
    return sent == len(input_list)


def type_text(text: str, delay_per_char_s: float = 0.005) -> int:
    """Type simple plain text using SendInput unicode events.

    WARNING: Only for NON-SENSITIVE fields. Passwords and credentials must be
    blocked by the caller / policy engine before reaching this function.
    Returns:
        Number of characters successfully sent.
    """
    if not text:
        return 0

    count = 0
    for char in text:
        # Generate key down + key up
        down = _make_unicode_input(char, is_up=False)
        up = _make_unicode_input(char, is_up=True)
        pair = (INPUT * 2)(down, up)
        sent = _user32.SendInput(2, pair, sizeof(INPUT))
        if sent == 2:
            count += 1
        if delay_per_char_s > 0:
            time.sleep(delay_per_char_s)

    return count


# ──────────────────────────────────────────────────────────────────────────────
# Public Mouse Functions
# ──────────────────────────────────────────────────────────────────────────────

def move_mouse(x: int, y: int) -> bool:
    """Move hardware mouse cursor to verified screen coordinates (x, y)."""
    return bool(_user32.SetCursorPos(x, y))


def click_mouse(x: int, y: int, button: str = "left") -> bool:
    """Position cursor and click at screen coordinates (x, y).

    Args:
        x, y: Absolute screen coordinates. Must be validated inside window bounds beforehand.
        button: 'left' (default) or 'right' (if explicitly requested).

    Returns:
        True if click events were successfully sent.
    """
    if not move_mouse(x, y):
        return False
    time.sleep(0.02)

    btn = button.lower().strip()
    if btn == "right":
        down_flag = MOUSEEVENTF_RIGHTDOWN
        up_flag = MOUSEEVENTF_RIGHTUP
    else:
        down_flag = MOUSEEVENTF_LEFTDOWN
        up_flag = MOUSEEVENTF_LEFTUP

    inp_down = INPUT()
    inp_down.type = INPUT_MOUSE
    inp_down.u.mi = MOUSEINPUT(0, 0, 0, down_flag, 0, 0)

    inp_up = INPUT()
    inp_up.type = INPUT_MOUSE
    inp_up.u.mi = MOUSEINPUT(0, 0, 0, up_flag, 0, 0)

    arr = (INPUT * 2)(inp_down, inp_up)
    sent = _user32.SendInput(2, arr, sizeof(INPUT))
    return sent == 2

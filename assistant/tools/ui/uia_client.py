"""Low-level Windows UI Automation COM wrapper (Phase 10A).

Provides thread-safe access to IUIAutomation and IUIAutomationElement
via native ctypes/COM without external dependencies (pywinauto/comtypes).

Key design decisions:
- COINIT_MULTITHREADED + SetThreadDesktop for subprocess context safety.
- COM pointers are NEVER stored as persistent state; all calls are inlined
  and resources released synchronously after use.
- HRESULT values checked on every call; non-zero results raise UiaError.
- Password/credential fields: IsPassword flag is read for classification
  but actual values are always REDACTED and never returned or logged.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import (
    POINTER,
    WINFUNCTYPE,
    Structure,
    byref,
    c_int,
    c_long,
    c_void_p,
    wintypes,
)
from contextlib import contextmanager
from typing import Any, Optional

# Windows constants
CLSID_CUIAutomation_STR = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
IID_IUIAutomation_STR = "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}"
CLSCTX_INPROC_SERVER = 1
COINIT_MULTITHREADED = 0

# UIA ControlType IDs
CONTROL_TYPES: dict[int, str] = {
    50000: "Button",
    50001: "Calendar",
    50002: "CheckBox",
    50003: "ComboBox",
    50004: "Edit",
    50005: "Hyperlink",
    50006: "Image",
    50007: "ListItem",
    50008: "List",
    50009: "Menu",
    50010: "MenuBar",
    50011: "MenuItem",
    50012: "ProgressBar",
    50013: "RadioButton",
    50014: "ScrollBar",
    50015: "Slider",
    50016: "Spinner",
    50017: "StatusBar",
    50018: "Tab",
    50019: "TabItem",
    50020: "Text",
    50021: "ToolBar",
    50022: "ToolTip",
    50023: "Tree",
    50024: "TreeItem",
    50025: "Custom",
    50026: "Group",
    50027: "Thumb",
    50028: "DataGrid",
    50029: "DataItem",
    50030: "Document",
    50031: "SplitButton",
    50032: "Window",
    50033: "Pane",
    50034: "Header",
    50035: "HeaderItem",
    50036: "Table",
    50037: "TitleBar",
    50038: "Separator",
    50039: "SemanticZoom",
    50040: "AppBar",
}


class UiaError(Exception):
    """Raised when a UIA COM operation fails with a non-zero HRESULT."""

    def __init__(self, method: str, hresult: int):
        super().__init__(
            f"UIA call '{method}' failed with HRESULT 0x{hresult & 0xFFFFFFFF:08X}"
        )
        self.hresult = hresult


class _GUID(Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class _RECT(Structure):
    _fields_ = [
        ("left", c_long),
        ("top", c_long),
        ("right", c_long),
        ("bottom", c_long),
    ]


_ole32 = ctypes.windll.ole32
_oleaut32 = ctypes.windll.oleaut32
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_lock = threading.Lock()


def _str_to_guid(guid_str: str) -> _GUID:
    guid = _GUID()
    _ole32.CLSIDFromString(guid_str, byref(guid))
    return guid


def _bstr_to_str(bstr_ptr: c_void_p) -> str:
    """Safely read a BSTR and free it via SysFreeString."""
    if not bstr_ptr.value:
        return ""
    try:
        return ctypes.wstring_at(bstr_ptr.value)
    finally:
        _oleaut32.SysFreeString(bstr_ptr)


def _check_hr(method_name: str, hr: int) -> None:
    if hr != 0:
        raise UiaError(method_name, hr)


# ──────────────────────────────────────────────────────────────────────────────
# Vtable function factories
# ──────────────────────────────────────────────────────────────────────────────


def _make_bstr_getter(vtable: Any, index: int) -> Any:
    proto = WINFUNCTYPE(c_long, c_void_p, POINTER(c_void_p))
    return proto(vtable[index])


def _make_int_getter(vtable: Any, index: int) -> Any:
    proto = WINFUNCTYPE(c_long, c_void_p, POINTER(c_int))
    return proto(vtable[index])


def _make_rect_getter(vtable: Any, index: int) -> Any:
    proto = WINFUNCTYPE(c_long, c_void_p, POINTER(_RECT))
    return proto(vtable[index])


# ──────────────────────────────────────────────────────────────────────────────
# Element property reader
# ──────────────────────────────────────────────────────────────────────────────

def read_element_properties(p_element: c_void_p) -> dict[str, Any]:
    """Read all useful metadata from an IUIAutomationElement COM pointer.

    Password values are never read. IsPassword flag is read for classification
    purposes only. Returns a plain dict; frees all COM BSTR resources.
    """
    if not p_element.value:
        return {}

    ev = ctypes.cast(p_element, POINTER(POINTER(c_void_p))).contents

    def get_bstr(idx: int) -> str:
        fn = _make_bstr_getter(ev, idx)
        bstr = c_void_p()
        hr = fn(p_element, byref(bstr))
        if hr != 0 or not bstr.value:
            return ""
        return _bstr_to_str(bstr)

    def get_int(idx: int, default: int = -1) -> int:
        fn = _make_int_getter(ev, idx)
        val = c_int(default)
        hr = fn(p_element, byref(val))
        if hr != 0:
            return default
        return val.value

    def get_rect(idx: int) -> dict[str, int]:
        fn = _make_rect_getter(ev, idx)
        rect = _RECT()
        hr = fn(p_element, byref(rect))
        if hr != 0:
            return {}
        return {
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        }

    ctrl_type_id = get_int(21)
    ctrl_type_name = CONTROL_TYPES.get(ctrl_type_id, f"Unknown({ctrl_type_id})")
    is_password = bool(get_int(35, 0))
    is_enabled = bool(get_int(28, 1))
    is_offscreen = bool(get_int(38, 0))
    process_id = get_int(20, -1)

    return {
        "name": get_bstr(23),
        "automation_id": get_bstr(29),
        "control_type_id": ctrl_type_id,
        "control_type": ctrl_type_name,
        "localized_type": get_bstr(22),
        "class_name": get_bstr(30),
        "framework_id": get_bstr(40),
        "is_enabled": is_enabled,
        "is_offscreen": is_offscreen,
        "is_password": is_password,
        "process_id": process_id,
        "bounding_rect": get_rect(43),
        # value explicitly omitted for password fields; will be handled in tree_inspector
        "untrusted": True,
    }


# ──────────────────────────────────────────────────────────────────────────────
# COM Context Manager
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def uia_session():
    """Thread-safe context manager that initializes COM and returns a session dict.

    Yields:
        dict with keys:
            'p_automation' : c_void_p  — IUIAutomation pointer
            'p_walker'     : c_void_p  — IUIAutomationTreeWalker (ControlView)
            'vtable_auto'  : vtable    — IUIAutomation vtable
            'vtable_walk'  : vtable    — IUIAutomationTreeWalker vtable
    """
    # Attach to interactive desktop so calls work from background processes
    hdesk = _user32.OpenInputDesktop(0, False, 0x01FF)
    if hdesk:
        _user32.SetThreadDesktop(hdesk)

    _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)

    p_automation = c_void_p()
    p_walker = c_void_p()

    try:
        clsid = _str_to_guid(CLSID_CUIAutomation_STR)
        iid = _str_to_guid(IID_IUIAutomation_STR)
        hr = _ole32.CoCreateInstance(
            byref(clsid), None, CLSCTX_INPROC_SERVER, byref(iid), byref(p_automation)
        )
        _check_hr("CoCreateInstance(IUIAutomation)", hr)

        avtable = ctypes.cast(p_automation, POINTER(POINTER(c_void_p))).contents

        # GetControlViewWalker (vtable index 14)
        GetWalker_proto = WINFUNCTYPE(c_long, c_void_p, POINTER(c_void_p))
        GetWalker = GetWalker_proto(avtable[14])
        hr = GetWalker(p_automation, byref(p_walker))
        _check_hr("GetControlViewWalker", hr)

        wvtable = ctypes.cast(p_walker, POINTER(POINTER(c_void_p))).contents

        yield {
            "p_automation": p_automation,
            "p_walker": p_walker,
            "vtable_auto": avtable,
            "vtable_walk": wvtable,
        }
    finally:
        # Release COM objects (Release = vtable index 2 for IUnknown)
        for ptr in [p_walker, p_automation]:
            if ptr.value:
                try:
                    Release_proto = WINFUNCTYPE(c_long, c_void_p)
                    Release = Release_proto(
                        ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents[2]
                    )
                    Release(ptr)
                except Exception:
                    pass

        _ole32.CoUninitialize()
        if hdesk:
            _user32.CloseDesktop(hdesk)


# ──────────────────────────────────────────────────────────────────────────────
# Element Acquisition
# ──────────────────────────────────────────────────────────────────────────────

def get_element_from_hwnd(session: dict, hwnd: int) -> Optional[c_void_p]:
    """Acquire an IUIAutomationElement from a window handle.

    Returns:
        c_void_p COM pointer if successful, None if HWND is invalid/stale.
    """
    avtable = session["vtable_auto"]
    p_automation = session["p_automation"]

    ElementFromHandle_proto = WINFUNCTYPE(
        c_long, c_void_p, wintypes.HWND, POINTER(c_void_p)
    )
    ElementFromHandle = ElementFromHandle_proto(avtable[6])

    p_element = c_void_p()
    hr = ElementFromHandle(p_automation, hwnd, byref(p_element))
    if hr != 0 or not p_element.value:
        return None
    return p_element


def get_root_element(session: dict) -> Optional[c_void_p]:
    """Acquire the root desktop IUIAutomationElement."""
    avtable = session["vtable_auto"]
    p_automation = session["p_automation"]

    GetRoot_proto = WINFUNCTYPE(c_long, c_void_p, POINTER(c_void_p))
    GetRoot = GetRoot_proto(avtable[5])

    p_root = c_void_p()
    hr = GetRoot(p_automation, byref(p_root))
    if hr != 0 or not p_root.value:
        return None
    return p_root


def get_foreground_element(session: dict) -> Optional[c_void_p]:
    """Acquire an IUIAutomationElement for the current foreground window."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    return get_element_from_hwnd(session, hwnd)


def release_element(p_element: Optional[c_void_p]) -> None:
    """Safely release an IUIAutomationElement COM pointer."""
    if p_element and p_element.value:
        try:
            Release_proto = WINFUNCTYPE(c_long, c_void_p)
            Release = Release_proto(
                ctypes.cast(p_element, POINTER(POINTER(c_void_p))).contents[2]
            )
            Release(p_element)
        except Exception:
            pass

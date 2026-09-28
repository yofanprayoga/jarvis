"""Low-level Windows UI Automation Pattern COM wrappers (Phase 10B).

Implements COM calls for:
- InvokePattern: Invoke()
- ValuePattern: SetValue(BSTR), get_CurrentValue(BSTR*), get_CurrentIsReadOnly(BOOL*)
- TogglePattern: Toggle(), get_CurrentToggleState(int*)
- Element focus: SetFocus()

Safety principles:
- Zero persistent COM pointer retention; all pointers released in finally blocks.
- Proper HRESULT checking on every call; raises UiaError on failure.
- Graceful error handling for unsupported patterns and stale elements.
"""

from __future__ import annotations

import ctypes
from ctypes import (
    POINTER,
    WINFUNCTYPE,
    byref,
    c_int,
    c_long,
    c_void_p,
    c_wchar_p,
)
from typing import Any, Optional, Tuple

from assistant.tools.ui.uia_client import (
    UiaError,
    _bstr_to_str,
    _check_hr,
    _user32,
    _oleaut32,
)

# Pattern IDs (Windows SDK constants)
UIA_InvokePatternId = 10000
UIA_ValuePatternId = 10002
UIA_TogglePatternId = 10015

# ToggleState enum constants
TOGGLE_STATE_OFF = 0
TOGGLE_STATE_ON = 1
TOGGLE_STATE_INDETERMINATE = 2

TOGGLE_STATE_NAMES = {
    0: "Off",
    1: "On",
    2: "Indeterminate",
}


class PatternNotSupportedError(Exception):
    """Raised when an element does not support the requested UIA pattern."""
    pass


class ElementReadOnlyError(Exception):
    """Raised when attempting to modify a read-only element."""
    pass


class ElementUnavailableError(Exception):
    """Raised when the target element is stale or no longer available."""
    pass


def get_pattern(p_element: c_void_p, pattern_id: int) -> Optional[c_void_p]:
    """Retrieve an IUnknown pattern pointer from an IUIAutomationElement.

    Calls IUIAutomationElement::GetCurrentPattern (vtable index 16).
    Returns c_void_p COM pointer if supported, None if unsupported or failed.
    """
    if not p_element or not p_element.value:
        return None
    try:
        ev = ctypes.cast(p_element, POINTER(POINTER(c_void_p))).contents
        # GetCurrentPattern is vtable index 16
        proto = WINFUNCTYPE(c_long, c_void_p, c_int, POINTER(c_void_p))
        fn = proto(ev[16])
        p_pattern = c_void_p()
        hr = fn(p_element, pattern_id, byref(p_pattern))
        if hr != 0 or not p_pattern.value:
            return None
        return p_pattern
    except Exception:
        return None


def release_pattern(p_pattern: Optional[c_void_p]) -> None:
    """Safely release an IUnknown COM pointer."""
    if p_pattern and p_pattern.value:
        try:
            proto = WINFUNCTYPE(c_long, c_void_p)
            release_fn = proto(
                ctypes.cast(p_pattern, POINTER(POINTER(c_void_p))).contents[2]
            )
            release_fn(p_pattern)
        except Exception:
            pass


def focus_element(p_element: c_void_p, hwnd: Optional[int] = None) -> bool:
    """Set keyboard focus to the target element, activating owning window if needed.

    Calls IUIAutomationElement::SetFocus (vtable index 3).
    """
    if not p_element or not p_element.value:
        raise ElementUnavailableError("Target element is null or unavailable.")

    # Safely activate parent window if hwnd provided
    if hwnd:
        try:
            _user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    try:
        ev = ctypes.cast(p_element, POINTER(POINTER(c_void_p))).contents
        proto = WINFUNCTYPE(c_long, c_void_p)
        set_focus = proto(ev[3])
        hr = set_focus(p_element)
        _check_hr("IUIAutomationElement::SetFocus", hr)
        return True
    except Exception as e:
        if isinstance(e, UiaError):
            raise
        raise ElementUnavailableError(f"Failed to focus element: {e}") from e


def invoke_element(p_element: c_void_p) -> bool:
    """Invoke a control via IUIAutomationInvokePattern.

    Calls IUIAutomationInvokePattern::Invoke (vtable index 3).
    Raises:
        PatternNotSupportedError if InvokePattern is not available.
        UiaError on COM failure.
    """
    p_inv = get_pattern(p_element, UIA_InvokePatternId)
    if not p_inv or not p_inv.value:
        raise PatternNotSupportedError(
            "Control does not support InvokePattern (e.g. not a button or clickable control)."
        )
    try:
        iv = ctypes.cast(p_inv, POINTER(POINTER(c_void_p))).contents
        proto = WINFUNCTYPE(c_long, c_void_p)
        invoke_fn = proto(iv[3])
        hr = invoke_fn(p_inv)
        _check_hr("IUIAutomationInvokePattern::Invoke", hr)
        return True
    finally:
        release_pattern(p_inv)


def set_value(p_element: c_void_p, value: str) -> bool:
    """Set the text value of a control via IUIAutomationValuePattern.

    Calls IUIAutomationValuePattern::SetValue (vtable index 3).
    Checks read-only state via get_CurrentIsReadOnly (vtable index 5).
    Raises:
        PatternNotSupportedError if ValuePattern is not available.
        ElementReadOnlyError if control is read-only.
        UiaError on COM failure.
    """
    p_val = get_pattern(p_element, UIA_ValuePatternId)
    if not p_val or not p_val.value:
        raise PatternNotSupportedError(
            "Control does not support ValuePattern (e.g. not an editable text field)."
        )
    try:
        vv = ctypes.cast(p_val, POINTER(POINTER(c_void_p))).contents

        # Check read-only state (vtable index 5)
        ro = c_int(0)
        get_ro_proto = WINFUNCTYPE(c_long, c_void_p, POINTER(c_int))
        hr_ro = get_ro_proto(vv[5])(p_val, byref(ro))
        if hr_ro == 0 and ro.value:
            raise ElementReadOnlyError("Cannot set value: control is read-only.")

        # SetValue (vtable index 3)
        set_val_proto = WINFUNCTYPE(c_long, c_void_p, c_wchar_p)
        hr = set_val_proto(vv[3])(p_val, value)
        _check_hr("IUIAutomationValuePattern::SetValue", hr)
        return True
    finally:
        release_pattern(p_val)


def get_value(p_element: c_void_p) -> str:
    """Retrieve current text value via IUIAutomationValuePattern.

    Calls IUIAutomationValuePattern::get_CurrentValue (vtable index 4).
    WARNING: Do NOT call on password/credential fields (L0 violation).
    """
    p_val = get_pattern(p_element, UIA_ValuePatternId)
    if not p_val or not p_val.value:
        raise PatternNotSupportedError(
            "Control does not support ValuePattern."
        )
    try:
        vv = ctypes.cast(p_val, POINTER(POINTER(c_void_p))).contents
        bstr = c_void_p()
        get_val_proto = WINFUNCTYPE(c_long, c_void_p, POINTER(c_void_p))
        hr = get_val_proto(vv[4])(p_val, byref(bstr))
        _check_hr("IUIAutomationValuePattern::get_CurrentValue", hr)
        return _bstr_to_str(bstr)
    finally:
        release_pattern(p_val)


def toggle_element(p_element: c_void_p) -> Tuple[int, int]:
    """Toggle a control via IUIAutomationTogglePattern.

    Calls:
    - IUIAutomationTogglePattern::get_CurrentToggleState (vtable index 4)
    - IUIAutomationTogglePattern::Toggle (vtable index 3)
    Returns:
        (old_state, new_state) as integers (0=Off, 1=On, 2=Indeterminate).
    """
    p_tog = get_pattern(p_element, UIA_TogglePatternId)
    if not p_tog or not p_tog.value:
        raise PatternNotSupportedError(
            "Control does not support TogglePattern (e.g. not a checkbox or toggle switch)."
        )
    try:
        tv = ctypes.cast(p_tog, POINTER(POINTER(c_void_p))).contents
        toggle_proto = WINFUNCTYPE(c_long, c_void_p)
        get_state_proto = WINFUNCTYPE(c_long, c_void_p, POINTER(c_int))

        # Query state before toggle
        old_state = c_int(-1)
        hr_get1 = get_state_proto(tv[4])(p_tog, byref(old_state))
        _check_hr("IUIAutomationTogglePattern::get_CurrentToggleState (before)", hr_get1)

        # Execute toggle
        hr_tog = toggle_proto(tv[3])(p_tog)
        _check_hr("IUIAutomationTogglePattern::Toggle", hr_tog)

        # Query state after toggle
        new_state = c_int(-1)
        hr_get2 = get_state_proto(tv[4])(p_tog, byref(new_state))
        _check_hr("IUIAutomationTogglePattern::get_CurrentToggleState (after)", hr_get2)

        return old_state.value, new_state.value
    finally:
        release_pattern(p_tog)

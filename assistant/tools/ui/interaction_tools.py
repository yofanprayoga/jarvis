"""Phase 10B Windows UI Automation Interactive Actions.

Registers 4 interactive tools:
1. ui.focus     (L2): Set focus to target control, safely activating window
2. ui.invoke    (L2/L3): Invoke clickable controls (buttons, tabs, menu items)
3. ui.set_value (L2/L0): Set text value in editable controls (passwords strictly blocked)
4. ui.toggle    (L2/L3): Toggle checkboxes/switches (security toggles require confirmation)

All outputs are tagged untrusted=True and wrapped in <untrusted_ui_content>.
Audit logs record metadata only (no passwords, credentials, tokens, or sensitive values).
"""

from __future__ import annotations

import time
from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.ui.control_resolver import resolve_target_control
from assistant.tools.ui.risk_classifier import classify_ui_action
from assistant.tools.ui.uia_client import (
    UiaError,
    release_element,
    uia_session,
)
from assistant.tools.ui.uia_patterns import (
    ElementReadOnlyError,
    ElementUnavailableError,
    PatternNotSupportedError,
    TOGGLE_STATE_NAMES,
    focus_element,
    invoke_element,
    set_value,
    toggle_element,
)


def _wrap_untrusted_ui(text: str) -> str:
    """Wrap UI content in untrusted safety tags."""
    return f"<untrusted_ui_content>\n{text}\n</untrusted_ui_content>"


# ──────────────────────────────────────────────────────────────────────────────
# Input Models
# ──────────────────────────────────────────────────────────────────────────────

class FocusControlInput(BaseModel):
    path: Optional[str] = Field(
        default=None,
        description="Exact control path from ui.inspect_tree or ui.find_control output.",
    )
    name: Optional[str] = Field(
        default=None,
        description="Accessible name of the control to focus.",
    )
    automation_id: Optional[str] = Field(
        default=None,
        description="AutomationId of the control.",
    )
    control_type: Optional[str] = Field(
        default=None,
        description="ControlType to filter by (e.g. 'Button', 'Edit').",
    )
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window HWND. Defaults to current foreground window.",
    )


class InvokeControlInput(BaseModel):
    path: Optional[str] = Field(
        default=None,
        description="Exact control path from ui.inspect_tree or ui.find_control output.",
    )
    name: Optional[str] = Field(
        default=None,
        description="Accessible name of the control to invoke.",
    )
    automation_id: Optional[str] = Field(
        default=None,
        description="AutomationId of the control.",
    )
    control_type: Optional[str] = Field(
        default=None,
        description="ControlType to filter by (e.g. 'Button', 'MenuItem', 'TabItem').",
    )
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window HWND. Defaults to foreground window.",
    )
    confirmed: bool = Field(
        default=False,
        description="Must be set to True to execute high-impact (L3) actions like Delete, Submit, or Purchase.",
    )


class SetValueControlInput(BaseModel):
    value: str = Field(
        description="Text value to enter into the control.",
    )
    path: Optional[str] = Field(
        default=None,
        description="Exact control path from ui.inspect_tree or ui.find_control output.",
    )
    name: Optional[str] = Field(
        default=None,
        description="Accessible name of the control to edit.",
    )
    automation_id: Optional[str] = Field(
        default=None,
        description="AutomationId of the control.",
    )
    control_type: Optional[str] = Field(
        default=None,
        description="ControlType to filter by (e.g. 'Edit').",
    )
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window HWND. Defaults to foreground window.",
    )


class ToggleControlInput(BaseModel):
    path: Optional[str] = Field(
        default=None,
        description="Exact control path from ui.inspect_tree or ui.find_control output.",
    )
    name: Optional[str] = Field(
        default=None,
        description="Accessible name of the checkbox/toggle to change.",
    )
    automation_id: Optional[str] = Field(
        default=None,
        description="AutomationId of the control.",
    )
    control_type: Optional[str] = Field(
        default=None,
        description="ControlType to filter by (e.g. 'CheckBox').",
    )
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window HWND. Defaults to foreground window.",
    )
    confirmed: bool = Field(
        default=False,
        description="Must be set to True to confirm high-impact (L3) security/firewall toggles.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tool Implementations
# ──────────────────────────────────────────────────────────────────────────────

@tool(
    name="ui.focus",
    risk=Risk.LOW_ACTION,
    description="Set keyboard focus to a target UI control and safely bring its window to the foreground. Access to secure desktop or credential prompts is blocked.",
    input_model=FocusControlInput,
    timeout_s=10,
    requires_elevation=False,
)
def focus_tool(args: FocusControlInput) -> ToolResult:
    start_time = time.perf_counter()
    try:
        with uia_session() as session:
            # 1. Resolve target control
            res = resolve_target_control(
                session=session,
                hwnd=args.hwnd,
                path=args.path,
                name=args.name,
                automation_id=args.automation_id,
                control_type=args.control_type,
            )
            if not res.ok:
                if res.is_ambiguous:
                    return ToolResult.fail(
                        error=res.error or "Selector ambigu",
                        data={"ambiguous": True, "candidates": res.candidates},
                        untrusted=True,
                    )
                return ToolResult.fail(res.error or "Kontrol tidak ditemukan.")

            p_elem = res.p_element
            props = res.props

            try:
                # 2. Classify risk
                risk_level, reason = classify_ui_action(
                    action="ui.focus",
                    props=props,
                    selector_text=str(args.name or args.automation_id or args.path or ""),
                )
                if risk_level == Risk.FORBIDDEN:
                    return ToolResult.fail(
                        f"Tindakan ditolak oleh kebijakan keamanan (L0 FORBIDDEN): {reason}"
                    )

                # 3. Execute focus
                focus_element(p_elem, hwnd=args.hwnd)
                duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

                ctrl_name = props.get("name") or "(unnamed)"
                summary_text = (
                    f"Fokus UI Berhasil (L2):\n"
                    f"- Kontrol: [{props.get('control_type')}] '{ctrl_name}'\n"
                    f"- AutomationId: {props.get('automation_id') or '(none)'}\n"
                    f"- Path: {props.get('path')}\n"
                    f"- Durasi: {duration_ms} ms"
                )

                return ToolResult.success(
                    data={
                        "action": "focus",
                        "control_type": props.get("control_type"),
                        "name": ctrl_name,
                        "automation_id": props.get("automation_id"),
                        "path": props.get("path"),
                        "risk_level": "LOW_ACTION",
                        "duration_ms": duration_ms,
                        "untrusted": True,
                    },
                    summary=_wrap_untrusted_ui(summary_text),
                    untrusted=True,
                )
            finally:
                release_element(p_elem)

    except UiaError as e:
        return ToolResult.fail(f"UIA COM error saat memfokuskan elemen: {e}")
    except ElementUnavailableError as e:
        return ToolResult.fail(f"Elemen target tidak tersedia: {e}")
    except Exception as e:
        return ToolResult.fail(f"Gagal memfokuskan kontrol: {e}")


@tool(
    name="ui.invoke",
    risk=Risk.LOW_ACTION,
    description="Invoke a button, tab, menu, or clickable UI element. High-impact destructive/transactional actions (Delete, Submit, Order) require confirmed=True.",
    input_model=InvokeControlInput,
    timeout_s=15,
    requires_elevation=False,
)
def invoke_tool(args: InvokeControlInput) -> ToolResult:
    start_time = time.perf_counter()
    try:
        with uia_session() as session:
            # 1. Resolve target control
            res = resolve_target_control(
                session=session,
                hwnd=args.hwnd,
                path=args.path,
                name=args.name,
                automation_id=args.automation_id,
                control_type=args.control_type,
            )
            if not res.ok:
                if res.is_ambiguous:
                    return ToolResult.fail(
                        error=res.error or "Selector ambigu",
                        data={"ambiguous": True, "candidates": res.candidates},
                        untrusted=True,
                    )
                return ToolResult.fail(res.error or "Kontrol tidak ditemukan.")

            p_elem = res.p_element
            props = res.props

            try:
                # 2. Classify risk
                risk_level, reason = classify_ui_action(
                    action="ui.invoke",
                    props=props,
                    selector_text=str(args.name or args.automation_id or args.path or ""),
                )

                if risk_level == Risk.FORBIDDEN:
                    return ToolResult.fail(
                        f"Tindakan ditolak oleh kebijakan keamanan (L0 FORBIDDEN): {reason}"
                    )

                # 3. L3 Confirmation enforcement
                if risk_level == Risk.CONFIRM and not args.confirmed:
                    ctrl_name = props.get("name") or "(unnamed)"
                    rejection_msg = (
                        f"Konfirmasi Diperlukan (L3 CONFIRM): Tindakan [{props.get('control_type')}] '{ctrl_name}' "
                        f"terdeteksi berdampak tinggi ({reason}). "
                        f"Jalankan kembali dengan parameter confirmed=True untuk menyetujui eksekusi."
                    )
                    return ToolResult.fail(
                        error=rejection_msg,
                        data={
                            "requires_confirmation": True,
                            "risk_level": "CONFIRM",
                            "reason": reason,
                            "control_type": props.get("control_type"),
                            "name": ctrl_name,
                            "automation_id": props.get("automation_id"),
                            "path": props.get("path"),
                        },
                        untrusted=True,
                    )

                # 4. Execute invoke pattern
                invoke_element(p_elem)
                duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

                ctrl_name = props.get("name") or "(unnamed)"
                summary_text = (
                    f"Invoke UI Berhasil ({risk_level.name}):\n"
                    f"- Kontrol: [{props.get('control_type')}] '{ctrl_name}'\n"
                    f"- AutomationId: {props.get('automation_id') or '(none)'}\n"
                    f"- Path: {props.get('path')}\n"
                    f"- Terkonfirmasi: {args.confirmed}\n"
                    f"- Durasi: {duration_ms} ms"
                )

                return ToolResult.success(
                    data={
                        "action": "invoke",
                        "control_type": props.get("control_type"),
                        "name": ctrl_name,
                        "automation_id": props.get("automation_id"),
                        "path": props.get("path"),
                        "risk_level": risk_level.name,
                        "confirmed": args.confirmed,
                        "duration_ms": duration_ms,
                        "untrusted": True,
                    },
                    summary=_wrap_untrusted_ui(summary_text),
                    untrusted=True,
                )
            finally:
                release_element(p_elem)

    except PatternNotSupportedError as e:
        return ToolResult.fail(f"Pola Invoke tidak didukung: {e}")
    except UiaError as e:
        return ToolResult.fail(f"UIA COM error saat invoke: {e}")
    except Exception as e:
        return ToolResult.fail(f"Gagal invoke kontrol: {e}")


@tool(
    name="ui.set_value",
    risk=Risk.LOW_ACTION,
    description="Set the text value of an editable control. Sensitive credential and password fields are strictly blocked (L0 FORBIDDEN). Input values are never stored in audit logs.",
    input_model=SetValueControlInput,
    timeout_s=15,
    requires_elevation=False,
)
def set_value_tool(args: SetValueControlInput) -> ToolResult:
    start_time = time.perf_counter()
    try:
        with uia_session() as session:
            # 1. Resolve target control
            res = resolve_target_control(
                session=session,
                hwnd=args.hwnd,
                path=args.path,
                name=args.name,
                automation_id=args.automation_id,
                control_type=args.control_type,
            )
            if not res.ok:
                if res.is_ambiguous:
                    return ToolResult.fail(
                        error=res.error or "Selector ambigu",
                        data={"ambiguous": True, "candidates": res.candidates},
                        untrusted=True,
                    )
                return ToolResult.fail(res.error or "Kontrol tidak ditemukan.")

            p_elem = res.p_element
            props = res.props

            try:
                # 2. Classify risk: Passwords, credentials, PINs, tokens strictly blocked (L0)
                risk_level, reason = classify_ui_action(
                    action="ui.set_value",
                    props=props,
                    selector_text=str(args.name or args.automation_id or args.path or ""),
                    value=args.value,
                )

                if risk_level == Risk.FORBIDDEN:
                    # Never read, never write, never log value
                    return ToolResult.fail(
                        f"Tindakan diblokir total oleh PolicyEngine (L0 FORBIDDEN): {reason}. "
                        f"Otomasi pada kolom sensitif atau kredensial dilarang sepenuhnya."
                    )

                # 3. Execute value setting
                set_value(p_elem, args.value)
                duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

                ctrl_name = props.get("name") or "(unnamed)"
                # Audit hygiene: log only character length, NEVER the actual typed text
                summary_text = (
                    f"Input Teks Berhasil (L2):\n"
                    f"- Kontrol: [{props.get('control_type')}] '{ctrl_name}'\n"
                    f"- AutomationId: {props.get('automation_id') or '(none)'}\n"
                    f"- Path: {props.get('path')}\n"
                    f"- Karakter: {len(args.value)} karakter dimasukkan\n"
                    f"- Durasi: {duration_ms} ms"
                )

                return ToolResult.success(
                    data={
                        "action": "set_value",
                        "control_type": props.get("control_type"),
                        "name": ctrl_name,
                        "automation_id": props.get("automation_id"),
                        "path": props.get("path"),
                        "chars_written": len(args.value),
                        "risk_level": "LOW_ACTION",
                        "duration_ms": duration_ms,
                        "untrusted": True,
                    },
                    summary=_wrap_untrusted_ui(summary_text),
                    untrusted=True,
                )
            finally:
                release_element(p_elem)

    except PatternNotSupportedError as e:
        return ToolResult.fail(f"Pola Value tidak didukung pada kontrol ini: {e}")
    except ElementReadOnlyError as e:
        return ToolResult.fail(f"Kontrol berstatus read-only: {e}")
    except UiaError as e:
        return ToolResult.fail(f"UIA COM error saat set_value: {e}")
    except Exception as e:
        return ToolResult.fail(f"Gagal mengatur nilai kontrol: {e}")


@tool(
    name="ui.toggle",
    risk=Risk.LOW_ACTION,
    description="Toggle a checkbox or switch control. Security and system protection toggles require explicit confirmation (confirmed=True).",
    input_model=ToggleControlInput,
    timeout_s=15,
    requires_elevation=False,
)
def toggle_tool(args: ToggleControlInput) -> ToolResult:
    start_time = time.perf_counter()
    try:
        with uia_session() as session:
            # 1. Resolve target control
            res = resolve_target_control(
                session=session,
                hwnd=args.hwnd,
                path=args.path,
                name=args.name,
                automation_id=args.automation_id,
                control_type=args.control_type,
            )
            if not res.ok:
                if res.is_ambiguous:
                    return ToolResult.fail(
                        error=res.error or "Selector ambigu",
                        data={"ambiguous": True, "candidates": res.candidates},
                        untrusted=True,
                    )
                return ToolResult.fail(res.error or "Kontrol tidak ditemukan.")

            p_elem = res.p_element
            props = res.props

            try:
                # 2. Classify risk
                risk_level, reason = classify_ui_action(
                    action="ui.toggle",
                    props=props,
                    selector_text=str(args.name or args.automation_id or args.path or ""),
                )

                if risk_level == Risk.FORBIDDEN:
                    return ToolResult.fail(
                        f"Tindakan ditolak oleh kebijakan keamanan (L0 FORBIDDEN): {reason}"
                    )

                # 3. L3 Confirmation enforcement for security toggles
                if risk_level == Risk.CONFIRM and not args.confirmed:
                    ctrl_name = props.get("name") or "(unnamed)"
                    rejection_msg = (
                        f"Konfirmasi Diperlukan (L3 CONFIRM): Pengubahan toggle '{ctrl_name}' "
                        f"berkaitan dengan proteksi sistem/keamanan ({reason}). "
                        f"Jalankan kembali dengan parameter confirmed=True untuk menyetujui."
                    )
                    return ToolResult.fail(
                        error=rejection_msg,
                        data={
                            "requires_confirmation": True,
                            "risk_level": "CONFIRM",
                            "reason": reason,
                            "control_type": props.get("control_type"),
                            "name": ctrl_name,
                            "automation_id": props.get("automation_id"),
                            "path": props.get("path"),
                        },
                        untrusted=True,
                    )

                # 4. Execute toggle pattern
                old_state, new_state = toggle_element(p_elem)
                duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

                old_name = TOGGLE_STATE_NAMES.get(old_state, f"Unknown({old_state})")
                new_name = TOGGLE_STATE_NAMES.get(new_state, f"Unknown({new_state})")
                ctrl_name = props.get("name") or "(unnamed)"

                summary_text = (
                    f"Toggle UI Berhasil ({risk_level.name}):\n"
                    f"- Kontrol: [{props.get('control_type')}] '{ctrl_name}'\n"
                    f"- AutomationId: {props.get('automation_id') or '(none)'}\n"
                    f"- Status Sebelumnya: {old_name}\n"
                    f"- Status Sekarang: {new_name}\n"
                    f"- Terkonfirmasi: {args.confirmed}\n"
                    f"- Durasi: {duration_ms} ms"
                )

                return ToolResult.success(
                    data={
                        "action": "toggle",
                        "control_type": props.get("control_type"),
                        "name": ctrl_name,
                        "automation_id": props.get("automation_id"),
                        "path": props.get("path"),
                        "previous_state": old_name,
                        "new_state": new_name,
                        "risk_level": risk_level.name,
                        "confirmed": args.confirmed,
                        "duration_ms": duration_ms,
                        "untrusted": True,
                    },
                    summary=_wrap_untrusted_ui(summary_text),
                    untrusted=True,
                )
            finally:
                release_element(p_elem)

    except PatternNotSupportedError as e:
        return ToolResult.fail(f"Pola Toggle tidak didukung pada kontrol ini: {e}")
    except UiaError as e:
        return ToolResult.fail(f"UIA COM error saat toggle: {e}")
    except Exception as e:
        return ToolResult.fail(f"Gagal mengubah status toggle: {e}")

"""Phase 10C Windows Window Management & SendInput Fallback Tools.

Registers 5 tools:
1. window.activate : Bring window to foreground and restore if minimized
2. window.close    : Controlled close via WM_CLOSE (L3 confirmation for consequential apps)
3. ui.click_at     : Bounded coordinate click fallback with strict window boundary enforcement
4. ui.send_keys    : Keyboard shortcut / key press fallback
5. ui.type_text    : SendInput text typing fallback (passwords/credentials strictly blocked)

All outputs are wrapped in <untrusted_ui_content> and tagged untrusted=True.
Audit logs only record metadata (never secrets or typed text).
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.ui.coordinate_safety import validate_click_coordinates
from assistant.tools.ui.risk_classifier import classify_ui_action
from assistant.tools.ui.send_input import (
    click_mouse,
    send_key,
    send_key_combo,
    type_text,
)
from assistant.tools.ui.window_manager import (
    activate_window,
    close_window_safely,
    find_window_by_query,
    get_window_metadata,
    is_consequential_window,
    is_protected_process_window,
)


def _wrap_untrusted_ui(text: str) -> str:
    """Wrap UI content in untrusted safety tags."""
    return f"<untrusted_ui_content>\n{text}\n</untrusted_ui_content>"


# ──────────────────────────────────────────────────────────────────────────────
# Input Models
# ──────────────────────────────────────────────────────────────────────────────

class ActivateWindowInput(BaseModel):
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window handle (HWND). If None, search by title or process name.",
    )
    title: Optional[str] = Field(
        default=None,
        description="Window title substring to find and activate.",
    )
    process_name: Optional[str] = Field(
        default=None,
        description="Executable name of the application to activate (e.g. 'notepad.exe').",
    )


class CloseWindowInput(BaseModel):
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window handle (HWND). If None, search by title or process name.",
    )
    title: Optional[str] = Field(
        default=None,
        description="Window title substring of the window to close.",
    )
    process_name: Optional[str] = Field(
        default=None,
        description="Executable name of the application to close.",
    )
    confirmed: bool = Field(
        default=False,
        description="Must be True to close consequential/important applications (L3 CONFIRM).",
    )


class ClickAtInput(BaseModel):
    hwnd: int = Field(
        description="Target window handle (HWND). Coordinates are verified strictly within this window.",
    )
    x: int = Field(
        description="X coordinate to click (screen-absolute or window-relative).",
    )
    y: int = Field(
        description="Y coordinate to click (screen-absolute or window-relative).",
    )
    is_relative: bool = Field(
        default=False,
        description="If True, (x, y) are relative to top-left of target window. Default is screen-absolute.",
    )
    button: str = Field(
        default="left",
        description="Mouse button to click: 'left' (default) or 'right'.",
    )


class SendKeysInput(BaseModel):
    keys: str = Field(
        description="Key name (e.g. 'enter', 'tab', 'esc', 'f5') or combo (e.g. 'ctrl+s', 'alt+f4', 'ctrl+c').",
    )
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window to activate before sending keys. Defaults to current foreground window.",
    )
    confirmed: bool = Field(
        default=False,
        description="Must be set to True for destructive shortcuts like shift+delete.",
    )


class TypeTextInput(BaseModel):
    text: str = Field(
        description="Plain text to type into the active or target field. Passwords/credentials strictly blocked (L0).",
    )
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window to activate before typing.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tool Implementations
# ──────────────────────────────────────────────────────────────────────────────

@tool(
    name="window.activate",
    risk=Risk.LOW_ACTION,
    description="Bring a window to the foreground and restore it if minimized. Protected security windows cannot be activated.",
    input_model=ActivateWindowInput,
    timeout_s=10,
    requires_elevation=False,
)
def activate_window_tool(args: ActivateWindowInput) -> ToolResult:
    start_time = time.perf_counter()
    target_hwnd = args.hwnd
    if not target_hwnd:
        target_hwnd = find_window_by_query(query=args.title, process_name=args.process_name)

    if not target_hwnd:
        return ToolResult.fail("Window target tidak ditemukan berdasarkan kriteria pencarian.")

    meta = get_window_metadata(target_hwnd)
    if not meta.get("valid"):
        return ToolResult.fail(f"HWND {target_hwnd} tidak valid atau window sudah tertutup.")

    # Risk evaluation
    risk_level, reason = classify_ui_action(
        action="window.activate",
        props=meta,
        selector_text=str(args.title or args.process_name or ""),
    )
    if risk_level == Risk.FORBIDDEN:
        return ToolResult.fail(f"Aktivasi window ditolak oleh kebijakan keamanan (L0): {reason}")

    success = activate_window(target_hwnd)
    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    if not success:
        return ToolResult.fail(f"Gagal mengaktifkan window '{meta.get('title')}'.")

    summary_text = (
        f"Aktivasi Window Berhasil (L2):\n"
        f"- Judul: '{meta.get('title')}'\n"
        f"- Proses: {meta.get('process_name')} (PID: {meta.get('process_id')})\n"
        f"- HWND: {target_hwnd}\n"
        f"- Status Sebelumnya: {'Diminimalkan' if meta.get('is_minimized') else 'Normal'}\n"
        f"- Durasi: {duration_ms} ms"
    )

    return ToolResult.success(
        data={
            "action": "activate_window",
            "hwnd": target_hwnd,
            "title": meta.get("title"),
            "process_name": meta.get("process_name"),
            "process_id": meta.get("process_id"),
            "risk_level": "LOW_ACTION",
            "duration_ms": duration_ms,
            "untrusted": True,
        },
        summary=_wrap_untrusted_ui(summary_text),
        untrusted=True,
    )


@tool(
    name="window.close",
    risk=Risk.LOW_ACTION,
    description="Close a window safely via WM_CLOSE (allows app to prompt to save). Closing consequential applications requires confirmed=True.",
    input_model=CloseWindowInput,
    timeout_s=10,
    requires_elevation=False,
)
def close_window_tool(args: CloseWindowInput) -> ToolResult:
    start_time = time.perf_counter()
    target_hwnd = args.hwnd
    if not target_hwnd:
        target_hwnd = find_window_by_query(query=args.title, process_name=args.process_name)

    if not target_hwnd:
        return ToolResult.fail("Window target tidak ditemukan untuk ditutup.")

    meta = get_window_metadata(target_hwnd)
    if not meta.get("valid"):
        return ToolResult.fail(f"HWND {target_hwnd} tidak valid atau window sudah tertutup.")

    # 1. Protected system processes check (L0 FORBIDDEN)
    is_prot, prot_reason = is_protected_process_window(meta)
    if is_prot:
        return ToolResult.fail(f"Penutupan window diblokir oleh kebijakan keamanan (L0 FORBIDDEN): {prot_reason}")

    # 2. Consequential check (L3 CONFIRM)
    is_conseq, conseq_reason = is_consequential_window(meta)
    if is_conseq and not args.confirmed:
        return ToolResult.fail(
            error=(
                f"Konfirmasi Diperlukan (L3 CONFIRM): Menutup '{meta.get('title')}' "
                f"({meta.get('process_name')}) terdeteksi berisiko tinggi ({conseq_reason}). "
                f"Jalankan kembali dengan confirmed=True untuk menyetujui penutupan."
            ),
            data={
                "requires_confirmation": True,
                "risk_level": "CONFIRM",
                "reason": conseq_reason,
                "title": meta.get("title"),
                "process_name": meta.get("process_name"),
                "hwnd": target_hwnd,
            },
            untrusted=True,
        )

    # 3. Controlled safe close via WM_CLOSE (never force-kill)
    sent = close_window_safely(target_hwnd)
    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    risk_name = "CONFIRM" if is_conseq else "LOW_ACTION"
    summary_text = (
        f"Penutupan Window Dikirim ({risk_name}):\n"
        f"- Judul: '{meta.get('title')}'\n"
        f"- Proses: {meta.get('process_name')} (PID: {meta.get('process_id')})\n"
        f"- Mekanisme: WM_CLOSE (Clean message dispatch)\n"
        f"- Terkonfirmasi: {args.confirmed}\n"
        f"- Durasi: {duration_ms} ms"
    )

    return ToolResult.success(
        data={
            "action": "close_window",
            "hwnd": target_hwnd,
            "title": meta.get("title"),
            "process_name": meta.get("process_name"),
            "mechanism": "WM_CLOSE",
            "risk_level": risk_name,
            "confirmed": args.confirmed,
            "duration_ms": duration_ms,
            "untrusted": True,
        },
        summary=_wrap_untrusted_ui(summary_text),
        untrusted=True,
    )


@tool(
    name="ui.click_at",
    risk=Risk.LOW_ACTION,
    description="Fallback mouse click at verified screen coordinates strictly within target window boundaries. Clicking outside window bounds or on secure desktop is strictly rejected.",
    input_model=ClickAtInput,
    timeout_s=10,
    requires_elevation=False,
)
def click_at_tool(args: ClickAtInput) -> ToolResult:
    start_time = time.perf_counter()

    # 1. Coordinate safety check
    valid, abs_x, abs_y, err_msg = validate_click_coordinates(
        hwnd=args.hwnd,
        x=args.x,
        y=args.y,
        is_relative=args.is_relative,
    )
    if not valid:
        return ToolResult.fail(f"Pemeriksaan keselamatan koordinat gagal: {err_msg}")

    meta = get_window_metadata(args.hwnd)

    # 2. Risk check
    risk_level, reason = classify_ui_action(
        action="ui.click_at",
        props=meta,
        selector_text=f"click at ({abs_x}, {abs_y})",
    )
    if risk_level == Risk.FORBIDDEN:
        return ToolResult.fail(f"Klik koordinat diblokir oleh kebijakan keamanan (L0): {reason}")

    # 3. Perform click
    btn = args.button.lower().strip()
    clicked = click_mouse(abs_x, abs_y, button=btn)
    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    if not clicked:
        return ToolResult.fail(f"Gagal mengirimkan event klik mouse pada ({abs_x}, {abs_y}).")

    summary_text = (
        f"Klik Mouse Fallback Berhasil (L2):\n"
        f"- Target Window: '{meta.get('title')}' (HWND: {args.hwnd})\n"
        f"- Koordinat Layar: ({abs_x}, {abs_y}) [Valid di dalam batas window]\n"
        f"- Tombol: {btn.capitalize()}\n"
        f"- Durasi: {duration_ms} ms"
    )

    return ToolResult.success(
        data={
            "action": "click_at",
            "hwnd": args.hwnd,
            "window_title": meta.get("title"),
            "x": abs_x,
            "y": abs_y,
            "button": btn,
            "risk_level": "LOW_ACTION",
            "duration_ms": duration_ms,
            "untrusted": True,
        },
        summary=_wrap_untrusted_ui(summary_text),
        untrusted=True,
    )


@tool(
    name="ui.send_keys",
    risk=Risk.LOW_ACTION,
    description="Send keyboard key presses or shortcuts (e.g. 'enter', 'tab', 'ctrl+s', 'esc') as fallback. Destructive shortcuts require confirmed=True.",
    input_model=SendKeysInput,
    timeout_s=10,
    requires_elevation=False,
)
def send_keys_tool(args: SendKeysInput) -> ToolResult:
    start_time = time.perf_counter()

    # 1. Activate target window if specified
    meta: dict[str, Any] = {}
    if args.hwnd:
        meta = get_window_metadata(args.hwnd)
        if meta.get("valid"):
            activate_window(args.hwnd)

    # 2. Risk classification
    risk_level, reason = classify_ui_action(
        action="ui.send_keys",
        props=meta,
        selector_text=args.keys,
    )

    if risk_level == Risk.FORBIDDEN:
        return ToolResult.fail(f"Kombinasi tombol diblokir oleh kebijakan keamanan (L0): {reason}")

    if risk_level == Risk.CONFIRM and not args.confirmed:
        return ToolResult.fail(
            error=(
                f"Konfirmasi Diperlukan (L3 CONFIRM): Kombinasi tombol '{args.keys}' "
                f"terdeteksi berisiko tinggi ({reason}). "
                f"Jalankan kembali dengan confirmed=True untuk menyetujui."
            ),
            data={
                "requires_confirmation": True,
                "risk_level": "CONFIRM",
                "reason": reason,
                "keys": args.keys,
            },
            untrusted=True,
        )

    # 3. Send keys
    raw_keys = args.keys.strip()
    if "+" in raw_keys:
        ok = send_key_combo(raw_keys)
    else:
        ok = send_key(raw_keys)

    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    if not ok:
        return ToolResult.fail(f"Gagal mengirimkan tombol '{args.keys}'. Pastikan nama tombol valid.")

    summary_text = (
        f"Kirim Tombol Berhasil ({risk_level.name}):\n"
        f"- Tombol/Kombinasi: '{args.keys}'\n"
        f"- Target Window: '{meta.get('title') or '(Foreground)'}'\n"
        f"- Terkonfirmasi: {args.confirmed}\n"
        f"- Durasi: {duration_ms} ms"
    )

    return ToolResult.success(
        data={
            "action": "send_keys",
            "keys": args.keys,
            "target_window": meta.get("title"),
            "risk_level": risk_level.name,
            "confirmed": args.confirmed,
            "duration_ms": duration_ms,
            "untrusted": True,
        },
        summary=_wrap_untrusted_ui(summary_text),
        untrusted=True,
    )


@tool(
    name="ui.type_text",
    risk=Risk.LOW_ACTION,
    description="Type plain text using SendInput fallback into non-sensitive controls. Entry of credentials, passwords, PINs, and tokens is strictly forbidden (L0).",
    input_model=TypeTextInput,
    timeout_s=15,
    requires_elevation=False,
)
def type_text_tool(args: TypeTextInput) -> ToolResult:
    start_time = time.perf_counter()

    # 1. Activate target window if specified
    meta: dict[str, Any] = {}
    if args.hwnd:
        meta = get_window_metadata(args.hwnd)
        if meta.get("valid"):
            activate_window(args.hwnd)

    # 2. Risk classification: Passwords & credentials strictly blocked (L0)
    risk_level, reason = classify_ui_action(
        action="ui.type_text",
        props=meta,
        selector_text=meta.get("title", ""),
        value=args.text,
    )

    if risk_level == Risk.FORBIDDEN:
        # Never type, never store text, never log
        return ToolResult.fail(
            f"Pengetikan diblokir total oleh PolicyEngine (L0 FORBIDDEN): {reason}. "
            f"Otomasi kredensial/rahasia dilarang sepenuhnya."
        )

    # 3. Perform SendInput typing
    chars_sent = type_text(args.text)
    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    # Audit hygiene: record character count only, NEVER typed content
    summary_text = (
        f"Pengetikan Teks Fallback Berhasil (L2):\n"
        f"- Target Window: '{meta.get('title') or '(Foreground)'}'\n"
        f"- Karakter Dikirim: {chars_sent} karakter\n"
        f"- Durasi: {duration_ms} ms"
    )

    return ToolResult.success(
        data={
            "action": "type_text",
            "target_window": meta.get("title"),
            "chars_typed": chars_sent,
            "risk_level": "LOW_ACTION",
            "duration_ms": duration_ms,
            "untrusted": True,
        },
        summary=_wrap_untrusted_ui(summary_text),
        untrusted=True,
    )

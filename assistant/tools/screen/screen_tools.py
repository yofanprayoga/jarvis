"""Screen capture, local offline OCR, and window inspection tools (Phase 9A)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.screen.desktop import capture_screen
from assistant.tools.screen.ocr import perform_ocr
from assistant.tools.ui.window_inspector import get_foreground_window_info


class WindowInspectInput(BaseModel):
    hwnd: Optional[int] = Field(default=None, description="Optional window handle to inspect (defaults to active foreground window)")


class ScreenCaptureInput(BaseModel):
    hwnd: Optional[int] = Field(default=None, description="Optional window handle to capture")
    crop_active_window: bool = Field(default=False, description="If True, captures only the active foreground window")


class ScreenOcrInput(BaseModel):
    image_path: Optional[str] = Field(default=None, description="Path to image file to read. If not provided, captures current screen first.")
    language: str = Field(default="en-US", description="OCR recognition language tag (e.g. en-US, en-GB)")


@tool(
    name="ui.inspect_window",
    risk=Risk.OBSERVE,
    description="Inspect the active foreground window or specified window handle: title, class, process name, PID, and dimensions.",
    input_model=WindowInspectInput,
    timeout_s=10,
    requires_elevation=False,
)
def inspect_window_tool(args: WindowInspectInput) -> ToolResult:
    info = get_foreground_window_info(args.hwnd)
    if not info.get("exists"):
        return ToolResult.success(
            data=info,
            summary=info.get("message", "Tidak ada jendela aktif yang terdeteksi."),
        )

    b = info.get("bounds", {})
    summary = (
        f"Informasi Jendela Aktif: '{info['title']}'\n"
        f"- Aplikasi / Proses: {info['process_name']} (PID: {info['pid']})\n"
        f"- Window Handle: {info['hwnd_hex']} (Class: {info['class_name']})\n"
        f"- Lokasi & Ukuran: {b.get('width', 0)}x{b.get('height', 0)} px pada ({b.get('left', 0)}, {b.get('top', 0)})\n"
        f"- Status: {'Tervisualisasi (Foreground)' if info.get('is_foreground') else 'Background'}"
    )

    return ToolResult.success(data=info, summary=summary)


@tool(
    name="screen.capture",
    risk=Risk.OBSERVE,
    description="Capture a screenshot of the entire desktop or a specific window on explicit request. Output is saved to local cache.",
    input_model=ScreenCaptureInput,
    timeout_s=10,
    requires_elevation=False,
)
def capture_screen_tool(args: ScreenCaptureInput) -> ToolResult:
    target_hwnd = args.hwnd
    if not target_hwnd and args.crop_active_window:
        fg_info = get_foreground_window_info()
        if fg_info.get("exists") and fg_info.get("hwnd"):
            target_hwnd = fg_info["hwnd"]

    try:
        capture_data = capture_screen(hwnd=target_hwnd)
    except Exception as e:
        return ToolResult.fail(f"Gagal mengambil tangkapan layar: {e}")

    size_kb = round(capture_data["size_bytes"] / 1024, 1)
    summary = (
        f"Tangkapan Layar Berhasil Dibuat ({capture_data['target_type']}):\n"
        f"- Resolusi: {capture_data['width']}x{capture_data['height']} px ({size_kb} KB)\n"
        f"- Lokasi File: {capture_data['image_path']}\n"
        f"- SHA-256: {capture_data['sha256'][:16]}..."
    )

    return ToolResult.success(data=capture_data, summary=summary)


@tool(
    name="screen.ocr",
    risk=Risk.OBSERVE,
    description="Read text from an image or screenshot using offline native Windows OCR. Output is untrusted data.",
    input_model=ScreenOcrInput,
    timeout_s=20,
    requires_elevation=False,
)
def ocr_screen_tool(args: ScreenOcrInput) -> ToolResult:
    img_path = args.image_path

    # If no image path provided, capture screen automatically first
    if not img_path:
        try:
            capture_res = capture_screen()
            img_path = capture_res["image_path"]
        except Exception as e:
            return ToolResult.fail(f"Gagal mengambil tangkapan layar untuk OCR: {e}")

    try:
        ocr_data = perform_ocr(img_path, language=args.language)
    except Exception as e:
        return ToolResult.fail(f"Gagal menjalankan OCR pada gambar '{img_path}': {e}")

    text = ocr_data.get("text", "")
    preview_lines = ocr_data.get("lines", [])[:12]
    preview_snippet = "\n".join(preview_lines) if preview_lines else "[Tidak ada teks terdeteksi di layar/gambar]"

    summary = (
        f"Hasil OCR Layar ({ocr_data['word_count']} kata terdeteksi, Bahasa: {ocr_data['language']}):\n"
        f"```text\n<untrusted_screen_content>\n{preview_snippet}\n</untrusted_screen_content>\n```"
    )

    return ToolResult.success(data=ocr_data, summary=summary)

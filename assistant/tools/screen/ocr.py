"""Offline local OCR using native Windows.Media.Ocr engine (Phase 9A)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional


def perform_ocr(
    image_path: str | Path,
    language: str = "en-US",
    timeout_s: int = 15,
) -> dict[str, Any]:
    """Execute offline Windows.Media.Ocr on an image file.
    
    Returns recognized text, lines, words with bounding boxes, and untrusted flag.
    Does not require internet connection, cloud APIs, or external vision models.
    """
    img_p = Path(image_path).resolve()
    if not img_p.is_file():
        raise FileNotFoundError(f"File gambar tidak ditemukan: '{img_p}'")

    script_path = Path(__file__).parent / "windows_ocr.ps1"
    if not script_path.is_file():
        raise FileNotFoundError(f"Skrip OCR Windows tidak ditemukan di '{script_path}'")

    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script_path.resolve()),
        "-ImagePath", str(img_p),
        "-Language", language,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"OCR Windows timeout setelah {timeout_s} detik.")

    if proc.returncode != 0 and not proc.stdout.strip():
        err_msg = proc.stderr.strip() or "PowerShell error"
        raise RuntimeError(f"Gagal menjalankan Windows OCR: {err_msg}")

    try:
        # Find JSON payload in stdout
        stdout = proc.stdout.strip()
        # Find first '{' and last '}'
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(stdout[start : end + 1])
        else:
            raise ValueError("Output PowerShell bukan format JSON yang valid.")
    except Exception as e:
        raise ValueError(f"Gagal mem-parsing hasil OCR: {e}. Output: {proc.stdout[:200]}")

    if not data.get("Success", True) and "Error" in data:
        raise RuntimeError(f"Error OCR: {data['Error']}")

    lines = data.get("Lines") or []
    full_text = data.get("Text") or "\n".join(lines)
    words = data.get("Words") or []

    return {
        "image_path": str(img_p),
        "filename": img_p.name,
        "text": full_text.strip(),
        "lines": lines,
        "word_count": data.get("WordCount", len(words)),
        "words": words,
        "language": language,
        "untrusted": True,
    }

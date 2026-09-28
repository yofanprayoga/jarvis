"""File inspection utilities: Shannon entropy, SHA-256 hash, and file type detection (Section 7.2)."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Optional


def calculate_shannon_entropy(data: bytes) -> float:
    """Calculate the Shannon entropy of a byte sequence (0.0 to 8.0).
    
    Entropy > 7.5 indicates high randomness, strongly hinting at compression or encryption.
    Plaintext configuration files typically have entropy between 3.5 and 5.2.
    """
    if not data:
        return 0.0

    length = len(data)
    freq = Counter(data)
    entropy = 0.0
    for count in freq.values():
        p = count / length
        entropy -= p * math.log2(p)
    return round(entropy, 3)


def detect_file_type(header: bytes, content_sample: str = "") -> dict[str, str]:
    """Detect file category and specific format from magic bytes and text patterns."""
    # 1. Binary Magic bytes
    if header.startswith(b"SQLite format 3\x00"):
        return {"category": "binary_db", "format": "SQLite Database"}
    if header.startswith(b"PK\x03\x04"):
        return {"category": "archive", "format": "ZIP Archive"}
    if header.startswith(b"\x1f\x8b"):
        return {"category": "archive", "format": "GZIP Compressed"}
    if header.startswith(b"7z\xbc\xaf\x27\x1c"):
        return {"category": "archive", "format": "7-Zip Archive"}
    if header.startswith(b"MZ"):
        return {"category": "executable", "format": "Windows Portable Executable (EXE/DLL)"}
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"category": "image", "format": "PNG Image"}
    if header.startswith(b"\xff\xd8\xff"):
        return {"category": "image", "format": "JPEG Image"}

    # 2. Check for null bytes (strong binary indicator)
    if b"\x00" in header:
        return {"category": "binary", "format": "Binary / Proprietary Format"}

    # 3. Text format detection
    sample = content_sample.strip()
    if not sample:
        return {"category": "empty", "format": "Empty File"}

    if (sample.startswith("{") and sample.endswith("}")) or (sample.startswith("[") and sample.endswith("]")):
        try:
            json.loads(sample)
            return {"category": "text", "format": "JSON"}
        except Exception:
            pass

    if sample.startswith("<?xml") or (sample.startswith("<") and sample.endswith(">")):
        return {"category": "text", "format": "XML"}

    if any(line.strip().startswith("[") and line.strip().endswith("]") for line in sample.splitlines()[:10]):
        return {"category": "text", "format": "INI / Configuration"}

    if any("=" in line or ":" in line for line in sample.splitlines()[:5]):
        return {"category": "text", "format": "Key-Value Configuration"}

    return {"category": "text", "format": "Plain Text"}


def inspect_file_path(file_path: str | Path, max_sample_bytes: int = 65536) -> dict[str, Any]:
    """Inspect file metadata, calculate SHA-256, Shannon entropy, and detect type."""
    p = Path(file_path)
    if not p.is_file():
        return {"exists": False, "path": str(p)}

    stat = p.stat()
    size_bytes = stat.st_size

    # Hash calculation and sample read
    hasher = hashlib.sha256()
    header = b""
    sample_data = b""

    with open(p, "rb") as f:
        sample_data = f.read(max_sample_bytes)
        header = sample_data[:256]
        hasher.update(sample_data)
        # Continue hashing remaining content if file is large
        while chunk := f.read(65536):
            hasher.update(chunk)

    sha256_hash = hasher.hexdigest()
    entropy = calculate_shannon_entropy(sample_data)

    # Try decoding text sample
    text_sample = ""
    is_text = False
    try:
        text_sample = sample_data.decode("utf-8")
        is_text = True
    except UnicodeDecodeError:
        try:
            text_sample = sample_data.decode("latin-1")
            is_text = b"\x00" not in sample_data[:1024]
        except Exception:
            is_text = False

    detected = detect_file_type(header, text_sample if is_text else "")

    is_high_entropy = entropy >= 7.2

    return {
        "exists": True,
        "path": str(p.resolve()),
        "filename": p.name,
        "extension": p.suffix.lower(),
        "size_bytes": size_bytes,
        "size_str": f"{round(size_bytes / 1024, 1)} KB" if size_bytes < 1024*1024 else f"{round(size_bytes / (1024**2), 2)} MB",
        "sha256": sha256_hash,
        "shannon_entropy": entropy,
        "is_high_entropy": is_high_entropy,
        "encryption_hint": "Terkunci/Terenkripsi atau Terkompresi (High Entropy)" if is_high_entropy else "Teks Biasa / Uncompressed",
        "category": detected["category"],
        "detected_format": detected["format"],
        "modified_time": stat.st_mtime,
        "is_readable_text": is_text and detected["category"] == "text",
    }

"""PowerShell and formatting helpers for system tools."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Tuple


def run_powershell_json(script: str, timeout_s: int = 15) -> Tuple[bool, Any, str | None]:
    """Execute a fixed PowerShell script returning JSON, parse output safely.
    
    Rule 6: Fixed templates only. PowerShell outputs ConvertTo-Json -Depth 4.
    """
    full_cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]

    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() or f"Process exited with code {proc.returncode}"
            return False, None, err

        stdout = proc.stdout.strip()
        if not stdout:
            return True, None, None

        try:
            parsed = json.loads(stdout)
            return True, parsed, None
        except json.JSONDecodeError as jde:
            return False, None, f"Failed to parse JSON output: {jde}. Raw: {stdout[:200]}"

    except subprocess.TimeoutExpired:
        return False, None, f"PowerShell command timed out after {timeout_s}s"
    except Exception as e:
        return False, None, str(e)


def format_bytes(num_bytes: float | int) -> str:
    """Format bytes into human-readable string (GB/MB)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def format_duration(seconds: float | int) -> str:
    """Format seconds into human-readable duration (X days, Y hrs, Z mins)."""
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)

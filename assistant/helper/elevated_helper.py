"""Elevated Helper process for UAC-isolated operations (Section 8.4).

Runs ONLY when explicitly invoked via ShellExecute 'runas'.
Communicates via JSON request and response files in a secure temp location.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ALLOWED_COMMANDS = {"list_minidumps", "analyze_minidump", "ping"}


def run_list_minidumps() -> dict:
    minidump_dir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Minidump"
    if not minidump_dir.is_dir():
        return {"count": 0, "dumps": []}

    dumps = []
    for f in minidump_dir.glob("*.dmp"):
        stat = f.stat()
        dumps.append({
            "filename": f.name,
            "path": str(f.resolve()),
            "size": stat.st_size,
            "created": stat.st_ctime,
        })
    dumps.sort(key=lambda x: x["created"], reverse=True)
    return {"count": len(dumps), "latest": dumps[0]["path"] if dumps else None, "dumps": dumps}


def run_analyze_minidump(file_path: str) -> dict:
    p = Path(file_path).resolve()
    # Must be inside SystemRoot\Minidump or valid .dmp file
    if not p.is_file() or p.suffix.lower() != ".dmp":
        return {"ok": False, "error": "Invalid minidump file path"}

    cdb_candidates = [
        shutil.which("cdb"),
        r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe",
        r"C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe",
    ]
    cdb_path = next((c for c in cdb_candidates if c and os.path.isfile(c)), None)
    if not cdb_path:
        return {"ok": False, "error": "cdb.exe not found on system"}

    cmd = [cdb_path, "-z", str(p), "-c", "!analyze -v; q"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=40, check=False)

    import re
    module_m = re.search(r"MODULE_NAME:\s*(\S+)", proc.stdout)
    bugcheck_m = re.search(r"BUGCHECK_CODE:\s*([0-9a-fA-F]+)", proc.stdout)

    return {
        "ok": True,
        "file": str(p),
        "bugcheck_code": f"0x{bugcheck_m.group(1)}" if bugcheck_m else "Unknown",
        "probable_module": module_m.group(1) if module_m else "Unknown",
        "output_snippet": proc.stdout[:1500],
    }


def main():
    parser = argparse.ArgumentParser(description="Jarvis Elevated Helper")
    parser.add_argument("--request", required=True, help="Path to request JSON file")
    parser.add_argument("--response", required=True, help="Path to response JSON file")
    args = parser.parse_args()

    req_path = Path(args.request)
    resp_path = Path(args.response)

    if not req_path.is_file():
        sys.exit(1)

    try:
        with open(req_path, "r", encoding="utf-8") as f:
            req_data = json.load(f)

        cmd = req_data.get("command")
        if cmd not in ALLOWED_COMMANDS:
            out = {"ok": False, "error": f"Command '{cmd}' not allowed in elevated helper"}
        elif cmd == "ping":
            out = {"ok": True, "message": "pong"}
        elif cmd == "list_minidumps":
            out = {"ok": True, "data": run_list_minidumps()}
        elif cmd == "analyze_minidump":
            target = req_data.get("file_path", "")
            out = run_analyze_minidump(target)
        else:
            out = {"ok": False, "error": "Unknown command"}

    except Exception as e:
        out = {"ok": False, "error": str(e)}

    with open(resp_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()

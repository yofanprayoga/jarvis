"""Crash dump analysis and reliability tools (Section 7.2 Phase 4)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import format_bytes, run_powershell_json


class EmptyInput(BaseModel):
    pass


class DumpsListInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=50, description="Max minidump files to list")


class DumpAnalyzeInput(BaseModel):
    file_path: Optional[str] = Field(default=None, description="Path to .dmp file (defaults to most recent minidump)")


class UpdatesHistoryInput(BaseModel):
    days: int = Field(default=30, ge=1, le=180, description="Time window in days for update history")


@tool(
    name="dumps.get_config",
    risk=Risk.OBSERVE,
    description="Check Windows crash dump configuration: whether minidump generation is enabled and directory paths.",
    input_model=EmptyInput,
    timeout_s=10,
    requires_elevation=False,
)
def get_dump_config(args: EmptyInput) -> ToolResult:
    ps_script = """
    $reg = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\CrashControl' -ErrorAction SilentlyContinue
    if ($reg) {
        $typeNames = @{
            0 = "Disabled (None)";
            1 = "Complete Memory Dump";
            2 = "Kernel Memory Dump";
            3 = "Small Memory Dump (Minidump 256KB)";
            7 = "Automatic Memory Dump"
        }
        $mode = $reg.CrashDumpEnabled
        @{
            Enabled = ($mode -ne 0);
            CrashDumpTypeCode = $mode;
            CrashDumpTypeName = $(if ($typeNames.ContainsKey($mode)) { $typeNames[$mode] } else { "Unknown ($mode)" });
            MinidumpDir = $reg.MinidumpDir;
            DumpFile = $reg.DumpFile;
            AutoReboot = [bool]$reg.AutoReboot;
            Overwrite = [bool]$reg.Overwrite
        } | ConvertTo-Json
    } else {
        @{ Enabled = $false; Error = "Cannot read CrashControl registry key" } | ConvertTo-Json
    }
    """

    ok, ps_data, err = run_powershell_json(ps_script, timeout_s=8)
    if not ok or not isinstance(ps_data, dict):
        return ToolResult.fail(f"Failed to query dump config: {err}")

    enabled = ps_data.get("Enabled", False)
    type_name = ps_data.get("CrashDumpTypeName", "Unknown")
    mini_dir = ps_data.get("MinidumpDir", r"%SystemRoot%\Minidump")

    summary = (
        f"Crash Dump: {'AKTIF' if enabled else 'NONAKTIF'}\n"
        f"Tipe Dump: {type_name}\n"
        f"Folder Minidump: {mini_dir}\n"
        f"Auto Reboot: {ps_data.get('AutoReboot')}"
    )

    return ToolResult.success(data=ps_data, summary=summary)


@tool(
    name="dumps.list",
    risk=Risk.OBSERVE,
    description="List available crash minidump (.dmp) files with creation dates and sizes.",
    input_model=DumpsListInput,
    timeout_s=10,
    requires_elevation=False,
)
def list_dumps(args: DumpsListInput) -> ToolResult:
    minidump_dir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Minidump"
    if not minidump_dir.is_dir():
        return ToolResult.success(
            data={"count": 0, "directory": str(minidump_dir), "dumps": []},
            summary=f"Folder minidump '{minidump_dir}' tidak ditemukan atau belum pernah ada crash.",
        )

    dump_files = []
    try:
        for f in minidump_dir.glob("*.dmp"):
            stat = f.stat()
            dump_files.append({
                "filename": f.name,
                "path": str(f.resolve()),
                "size_bytes": stat.st_size,
                "size_str": format_bytes(stat.st_size),
                "created_time": stat.st_ctime,
            })
    except PermissionError:
        # User session cannot list directly without elevation
        return ToolResult.success(
            data={"count": 0, "permission_error": True, "directory": str(minidump_dir)},
            summary="Akses folder Minidump membutuhkan hak akses Administrator / UAC (Elevated Helper).",
        )

    dump_files.sort(key=lambda x: x["created_time"], reverse=True)
    selected = dump_files[:args.limit]

    lines = [f"- {d['filename']} ({d['size_str']})" for d in selected]
    summary = (
        f"Ditemukan {len(dump_files)} file minidump:\n"
        + ("\n".join(lines) if lines else "- Belum ada file minidump tersimpan.")
    )

    return ToolResult.success(
        data={"count": len(dump_files), "latest": selected[0]["path"] if selected else None, "dumps": selected},
        summary=summary,
    )


@tool(
    name="dumps.analyze",
    risk=Risk.OBSERVE,
    description="Analyze a crash minidump (.dmp) using cdb.exe debugger (!analyze -v) to extract probable cause driver and bugcheck.",
    input_model=DumpAnalyzeInput,
    timeout_s=45,
    requires_elevation=True,
)
def analyze_dump(args: DumpAnalyzeInput) -> ToolResult:
    # Look for cdb.exe in common Windows Kits locations
    cdb_candidates = [
        shutil.which("cdb"),
        r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe",
        r"C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe",
    ]
    cdb_path = next((c for c in cdb_candidates if c and os.path.isfile(c)), None)

    target_file = args.file_path
    if not target_file:
        # Check latest minidump
        list_res = list_dumps(DumpsListInput(limit=1))
        target_file = list_res.data.get("latest")

    if not target_file or not os.path.isfile(target_file):
        return ToolResult.fail("Tidak ada file minidump (.dmp) yang dapat dianalisis.")

    if not cdb_path:
        return ToolResult.success(
            data={"cdb_installed": False, "target_file": target_file},
            summary=(
                f"File dump ditemukan: '{Path(target_file).name}'.\n"
                f"Namun tool debugger 'cdb.exe' (Debugging Tools for Windows) belum terpasang.\n"
                f"Analisis tetap dapat dilakukan lewat Bugcheck Event Log 1001 dan tabel kamus bugcheck."
            ),
        )

    # Run cdb !analyze -v
    cmd = [
        cdb_path,
        "-z", target_file,
        "-c", "!analyze -v; q",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        output = proc.stdout

        # Extract MODULE_NAME and BUGCHECK_STR
        import re
        module_m = re.search(r"MODULE_NAME:\s*(\S+)", output)
        bugcheck_m = re.search(r"BUGCHECK_CODE:\s*([0-9a-fA-F]+)", output)
        probable_m = re.search(r"FAILURE_BUCKET_ID:\s*([^\r\n]+)", output)

        analysis = {
            "file": target_file,
            "probable_module": module_m.group(1) if module_m else "Unknown",
            "bugcheck_code": f"0x{bugcheck_m.group(1)}" if bugcheck_m else "Unknown",
            "bucket_id": probable_m.group(1).strip() if probable_m else "Unknown",
            "summary_snippet": output[:1000],
        }

        summary = (
            f"Analisis Minidump ({Path(target_file).name}):\n"
            f"- Bugcheck Code: {analysis['bugcheck_code']}\n"
            f"- Probable Cause Driver: {analysis['probable_module']}\n"
            f"- Failure Bucket: {analysis['bucket_id']}"
        )
        return ToolResult.success(data=analysis, summary=summary)

    except Exception as e:
        return ToolResult.fail(f"Gagal mengeksekusi cdb analysis: {e}")


@tool(
    name="system.get_updates_history",
    risk=Risk.OBSERVE,
    description="Get recently installed Windows hotfixes, driver updates, and OS patches to correlate with crash dates.",
    input_model=UpdatesHistoryInput,
    timeout_s=20,
    requires_elevation=False,
)
def get_updates_history(args: UpdatesHistoryInput) -> ToolResult:
    ps_script = f"""
    Get-CimInstance Win32_QuickFixEngineering |
        Select-Object HotFixID, Description, InstalledOn, InstalledBy |
        Sort-Object InstalledOn -Descending |
        Select-Object -First 15 |
        ConvertTo-Json -Depth 2
    """

    ok, ps_data, err = run_powershell_json(ps_script, timeout_s=15)
    if not ok:
        return ToolResult.fail(f"Failed to query updates history: {err}")

    updates = []
    if ps_data:
        raw_list = ps_data if isinstance(ps_data, list) else [ps_data]
        for it in raw_list:
            if not isinstance(it, dict):
                continue
            inst_on = str(it.get("InstalledOn") or "Unknown")
            if isinstance(it.get("InstalledOn"), dict) and "value" in it["InstalledOn"]:
                inst_on = str(it["InstalledOn"]["value"])

            updates.append({
                "hotfix_id": str(it.get("HotFixID", "Unknown")),
                "description": str(it.get("Description", "Update")),
                "installed_on": inst_on[:10] if len(inst_on) >= 10 else inst_on,
            })

    lines = [f"- {u['hotfix_id']} ({u['description']}) on {u['installed_on']}" for u in updates[:8]]
    summary = (
        f"Daftar Update Windows Terakhir ({len(updates)} item):\n"
        + ("\n".join(lines) if lines else "- Belum ada riwayat update")
    )

    return ToolResult.success(data={"count": len(updates), "updates": updates}, summary=summary)


@tool(
    name="reliability.get_records",
    risk=Risk.OBSERVE,
    description="Get Windows Reliability Monitor history records (crashes, update installations, driver changes).",
    input_model=UpdatesHistoryInput,
    timeout_s=25,
    requires_elevation=False,
)
def get_reliability_records(args: UpdatesHistoryInput) -> ToolResult:
    ps_script = f"""
    $startTime = (Get-Date).AddDays(-{args.days})
    try {{
        Get-CimInstance Win32_ReliabilityRecords -ErrorAction Stop |
            Where-Object {{ $_.TimeGenerated -ge $startTime }} |
            Sort-Object TimeGenerated -Descending |
            Select-Object -First 20 EventIdentifier, SourceName, Message, TimeGenerated |
            ConvertTo-Json -Depth 2
    }} catch {{
        "[]"
    }}
    """

    ok, ps_data, err = run_powershell_json(ps_script, timeout_s=20)
    records = []
    if ok and ps_data:
        raw_list = ps_data if isinstance(ps_data, list) else [ps_data]
        for it in raw_list:
            if isinstance(it, dict) and it.get("SourceName"):
                records.append({
                    "source": str(it.get("SourceName")),
                    "message": str(it.get("Message", ""))[:120],
                    "time": str(it.get("TimeGenerated", ""))[:19],
                })

    lines = [f"- [{r['time']}] {r['source']}: {r['message'][:80]}" for r in records[:8]]
    summary = (
        f"Catatan Keandalan Sistem ({args.days} hari terakhir):\n"
        + ("\n".join(lines) if lines else "- Tidak ada catatan kegagalan sistem.")
    )

    return ToolResult.success(data={"count": len(records), "records": records}, summary=summary)

"""Tool: system.get_memory (Section 7.2)."""

from __future__ import annotations

import psutil
from pydantic import BaseModel
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import format_bytes, run_powershell_json


class MemoryInput(BaseModel):
    pass


@tool(
    name="system.get_memory",
    risk=Risk.OBSERVE,
    description="Get detailed memory metrics: physical RAM, commit charge, page file usage, and paging pressure.",
    input_model=MemoryInput,
    timeout_s=15,
    requires_elevation=False,
)
def get_memory(args: MemoryInput) -> ToolResult:
    # 1. Physical RAM
    vm = psutil.virtual_memory()
    total_ram = vm.total
    available_ram = vm.available
    used_ram = vm.used
    ram_pct = vm.percent

    # 2. Swap / Pagefile
    sm = psutil.swap_memory()
    pagefile_total = sm.total
    pagefile_used = sm.used
    pagefile_free = sm.free
    pagefile_pct = sm.percent

    # 3. Commit Limit & Commit Charge via PowerShell / CIM
    ps_script = """
    $os = Get-CimInstance Win32_OperatingSystem | Select-Object TotalVirtualMemorySize, FreeVirtualMemorySize, SizeStoredInPagingFiles
    $perf = Get-Counter '\Memory\Pages/sec' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CounterSamples | Select-Object -ExpandProperty CookedValue
    @{
        TotalCommitKB = $os.TotalVirtualMemorySize;
        FreeCommitKB = $os.FreeVirtualMemorySize;
        HardFaultsPerSec = [math]::Round(($perf | Measure-Object -Average).Average, 1)
    } | ConvertTo-Json
    """
    ok, ps_data, _ = run_powershell_json(ps_script, timeout_s=10)

    total_commit = 0
    used_commit = 0
    hard_faults = 0.0
    if ok and isinstance(ps_data, dict):
        total_commit = (ps_data.get("TotalCommitKB") or 0) * 1024
        free_commit = (ps_data.get("FreeCommitKB") or 0) * 1024
        used_commit = max(0, total_commit - free_commit)
        hard_faults = ps_data.get("HardFaultsPerSec") or 0.0

    commit_pct = round((used_commit / total_commit * 100), 1) if total_commit > 0 else 0.0

    data = {
        "physical_total": format_bytes(total_ram),
        "physical_available": format_bytes(available_ram),
        "physical_used": format_bytes(used_ram),
        "physical_percent": ram_pct,
        "pagefile_total": format_bytes(pagefile_total),
        "pagefile_used": format_bytes(pagefile_used),
        "pagefile_percent": pagefile_pct,
        "commit_total": format_bytes(total_commit) if total_commit else "N/A",
        "commit_used": format_bytes(used_commit) if used_commit else "N/A",
        "commit_percent": commit_pct,
        "hard_page_faults_per_sec": hard_faults,
    }

    # Pressure warning
    pressure_notes = []
    if ram_pct > 85.0:
        pressure_notes.append("High physical RAM pressure (>85%)")
    if pagefile_pct > 75.0:
        pressure_notes.append("Heavy pagefile utilization")
    if hard_faults > 100.0:
        pressure_notes.append(f"Significant hard paging ({hard_faults}/s)")

    warning_str = f"\nAlerts: {'; '.join(pressure_notes)}" if pressure_notes else ""

    summary = (
        f"RAM: {data['physical_used']} / {data['physical_total']} ({ram_pct}% used, {data['physical_available']} avail)\n"
        f"Commit Charge: {data['commit_used']} / {data['commit_total']} ({commit_pct}%)\n"
        f"Pagefile: {data['pagefile_used']} / {data['pagefile_total']} ({pagefile_pct}%)\n"
        f"Hard Page Faults: {hard_faults}/sec{warning_str}"
    )

    return ToolResult.success(data=data, summary=summary)

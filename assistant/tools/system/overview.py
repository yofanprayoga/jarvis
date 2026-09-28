"""Tool: system.get_overview (Section 7.2)."""

from __future__ import annotations

import platform
import subprocess
import time
import psutil
from pydantic import BaseModel
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import format_bytes, format_duration, run_powershell_json


class EmptyInput(BaseModel):
    """Empty input schema for tools requiring no parameters."""
    pass


@tool(
    name="system.get_overview",
    risk=Risk.OBSERVE,
    description="Get system overview: OS version, uptime, CPU model, RAM usage, disks, GPUs, and active power plan.",
    input_model=EmptyInput,
    timeout_s=15,
    requires_elevation=False,
)
def get_overview(args: EmptyInput) -> ToolResult:
    # 1. OS & Uptime
    os_name = f"{platform.system()} {platform.release()} (Build {platform.version()})"
    boot_time = psutil.boot_time()
    uptime_sec = time.time() - boot_time
    uptime_str = format_duration(uptime_sec)

    # 2. CPU
    cpu_model = platform.processor()
    cpu_count_phys = psutil.cpu_count(logical=False) or 0
    cpu_count_log = psutil.cpu_count(logical=True) or 0

    # 3. RAM
    mem = psutil.virtual_memory()
    ram_total = format_bytes(mem.total)
    ram_used = format_bytes(mem.used)
    ram_pct = mem.percent

    # 4. Disks summary
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": format_bytes(usage.total),
                "free": format_bytes(usage.free),
                "percent": usage.percent,
            })
        except (PermissionError, OSError):
            continue

    # 5. GPUs and Power plan via fast PowerShell command
    ps_script = """
    $gpus = Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, AdapterRAM | ConvertTo-Json -Depth 2
    $scheme = (powercfg /getactivescheme) -replace '.*Guid: (.*)  \((.*)\)', '$2'
    @{ GPUs = ($gpus | ConvertFrom-Json); PowerPlan = $scheme.Trim() } | ConvertTo-Json -Depth 4
    """
    ok, ps_data, _ = run_powershell_json(ps_script, timeout_s=10)
    gpus_data = []
    power_plan = "Unknown"
    if ok and isinstance(ps_data, dict):
        gpus_raw = ps_data.get("GPUs")
        if isinstance(gpus_raw, list):
            gpus_data = gpus_raw
        elif isinstance(gpus_raw, dict):
            gpus_data = [gpus_raw]
        power_plan = ps_data.get("PowerPlan") or "Unknown"

    data = {
        "os": os_name,
        "uptime": uptime_str,
        "uptime_seconds": int(uptime_sec),
        "cpu": {
            "model": cpu_model,
            "physical_cores": cpu_count_phys,
            "logical_cores": cpu_count_log,
        },
        "memory": {
            "total": ram_total,
            "used": ram_used,
            "percent": ram_pct,
        },
        "disks": disks,
        "gpus": gpus_data,
        "power_plan": power_plan,
    }

    # Concise human & LLM readable summary
    gpu_names = ", ".join(g.get("Name", "Unknown") for g in gpus_data) if gpus_data else "None"
    disk_summaries = ", ".join(f"{d['mountpoint']} {d['free']} free ({d['percent']}% used)" for d in disks)
    summary = (
        f"OS: {os_name} | Uptime: {uptime_str}\n"
        f"CPU: {cpu_model} ({cpu_count_phys}C/{cpu_count_log}T)\n"
        f"RAM: {ram_used} / {ram_total} ({ram_pct}%)\n"
        f"Disks: {disk_summaries}\n"
        f"GPUs: {gpu_names}\n"
        f"Power Plan: {power_plan}"
    )

    return ToolResult.success(data=data, summary=summary)

"""Tools: system.get_disks and system.get_disk_activity (Section 7.2)."""

from __future__ import annotations

import os
import time
import psutil
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import format_bytes, run_powershell_json


class DisksInput(BaseModel):
    pass


class DiskActivityInput(BaseModel):
    duration_s: float = Field(
        default=2.0,
        ge=1.0,
        le=15.0,
        description="Sampling duration in seconds to measure disk read/write throughput and activity",
    )


@tool(
    name="system.get_disks",
    risk=Risk.OBSERVE,
    description="Get volume and physical disk details: drive letter, label, capacity, free space, drive type (SSD/HDD), and Windows boot drive.",
    input_model=DisksInput,
    timeout_s=20,
    requires_elevation=False,
)
def get_disks(args: DisksInput) -> ToolResult:
    # Detect Windows drive letter
    win_drive = os.environ.get("SystemDrive", "C:").upper()
    if not win_drive.endswith("\\"):
        win_drive_path = win_drive + "\\"
    else:
        win_drive_path = win_drive

    # Query physical disk media types (SSD/HDD) via PowerShell CIM
    ps_script = """
    Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, MediaType, BusType, Size | ConvertTo-Json -Depth 2
    """
    ok, ps_disks, _ = run_powershell_json(ps_script, timeout_s=10)
    physical_disks = []
    if ok:
        if isinstance(ps_disks, list):
            physical_disks = ps_disks
        elif isinstance(ps_disks, dict):
            physical_disks = [ps_disks]

    # Map volumes
    volumes = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            is_windows = (part.mountpoint.rstrip("\\").upper() == win_drive.rstrip("\\"))
            volumes.append({
                "mountpoint": part.mountpoint,
                "device": part.device,
                "fstype": part.fstype,
                "total": format_bytes(usage.total),
                "free": format_bytes(usage.free),
                "used_percent": usage.percent,
                "is_windows_drive": is_windows,
            })
        except (PermissionError, OSError):
            continue

    data = {
        "windows_drive": win_drive,
        "volumes": volumes,
        "physical_disks": [
            {
                "id": str(d.get("DeviceId", "")),
                "name": str(d.get("FriendlyName", "")),
                "media_type": str(d.get("MediaType", "Unknown")),
                "bus_type": str(d.get("BusType", "Unknown")),
                "size": format_bytes(d.get("Size", 0)) if d.get("Size") else "Unknown",
            }
            for d in physical_disks
        ],
    }

    vol_lines = []
    for v in volumes:
        win_tag = " [WINDOWS OS]" if v["is_windows_drive"] else ""
        vol_lines.append(f"- {v['mountpoint']} {v['free']} free of {v['total']} ({v['used_percent']}% used){win_tag}")

    phys_lines = [f"- {d['name']} ({d['media_type']}, {d['bus_type']}, {d['size']})" for d in data["physical_disks"]]

    summary = (
        f"Volumes:\n" + "\n".join(vol_lines) + "\n"
        f"Physical Hardware:\n" + ("\n".join(phys_lines) if phys_lines else "- Unknown")
    )

    return ToolResult.success(data=data, summary=summary)


@tool(
    name="system.get_disk_activity",
    risk=Risk.OBSERVE,
    description="Sample disk I/O activity over a duration: throughput (MB/s read/write), active time %, and queue depth.",
    input_model=DiskActivityInput,
    timeout_s=25,
    requires_elevation=False,
)
def get_disk_activity(args: DiskActivityInput) -> ToolResult:
    # 1. Sample psutil disk_io_counters delta
    io_start = psutil.disk_io_counters(perdisk=True) or {}
    t_start = time.perf_counter()
    time.sleep(args.duration_s)
    t_end = time.perf_counter()
    io_end = psutil.disk_io_counters(perdisk=True) or {}

    elapsed = max(0.001, t_end - t_start)
    per_disk_metrics = {}

    for disk_name, s_start in io_start.items():
        if disk_name not in io_end:
            continue
        s_end = io_end[disk_name]
        read_bytes = s_end.read_bytes - s_start.read_bytes
        write_bytes = s_end.write_bytes - s_start.write_bytes
        read_kb_s = round(read_bytes / elapsed / 1024.0, 1)
        write_kb_s = round(write_bytes / elapsed / 1024.0, 1)

        per_disk_metrics[disk_name] = {
            "read_speed_kbs": read_kb_s,
            "write_speed_kbs": write_kb_s,
            "total_throughput_kbs": round(read_kb_s + write_kb_s, 1),
            "read_count": s_end.read_count - s_start.read_count,
            "write_count": s_end.write_count - s_start.write_count,
        }

    # 2. Query Active Time % and Queue length from LogicalDisk performance counters
    ps_script = """
    $samples = Get-Counter '\LogicalDisk(*)\% Disk Time', '\LogicalDisk(*)\Current Disk Queue Length' -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty CounterSamples |
        Select-Object InstanceName, Path, CookedValue
    $samples | ConvertTo-Json -Depth 3
    """
    ok, ps_samples, _ = run_powershell_json(ps_script, timeout_s=10)
    perf_data = {}
    if ok and ps_samples:
        items = ps_samples if isinstance(ps_samples, list) else [ps_samples]
        for it in items:
            inst = it.get("InstanceName", "")
            if not inst or inst == "_Total":
                continue
            path = it.get("Path", "").lower()
            val = round(it.get("CookedValue", 0.0), 1)
            if inst not in perf_data:
                perf_data[inst] = {}
            if "% disk time" in path:
                perf_data[inst]["active_percent"] = val
            elif "queue length" in path:
                perf_data[inst]["queue_length"] = val

    data = {
        "sampled_duration_s": round(elapsed, 2),
        "io_throughput": per_disk_metrics,
        "logical_disk_perf": perf_data,
    }

    summary_lines = []
    for inst, p in perf_data.items():
        active = p.get("active_percent", 0.0)
        q = p.get("queue_length", 0.0)
        warning = " [HIGH DISK USAGE]" if active >= 90.0 else ""
        summary_lines.append(f"- Drive {inst}: {active}% Active Time, Queue: {q}{warning}")

    throughput_lines = []
    for disk, m in per_disk_metrics.items():
        if m["total_throughput_kbs"] > 10.0:  # only list active disks
            throughput_lines.append(f"- {disk}: Read {m['read_speed_kbs']} KB/s | Write {m['write_speed_kbs']} KB/s")

    summary = (
        f"Disk Activity ({args.duration_s}s sample):\n"
        + ("\n".join(summary_lines) if summary_lines else "- No logical disk counters returned")
        + "\nThroughput:\n"
        + ("\n".join(throughput_lines) if throughput_lines else "- Negligible I/O during sample")
    )

    return ToolResult.success(data=data, summary=summary)

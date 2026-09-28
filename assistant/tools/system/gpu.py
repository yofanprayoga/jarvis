"""Tool: system.get_gpu_info (Section 7.2)."""

from __future__ import annotations

import shutil
import subprocess
from pydantic import BaseModel
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import format_bytes, run_powershell_json


class GpuInput(BaseModel):
    pass


@tool(
    name="system.get_gpu_info",
    risk=Risk.OBSERVE,
    description="Get detailed graphics card info: GPU adapters, driver versions, driver dates, and NVIDIA telemetry if available.",
    input_model=GpuInput,
    timeout_s=15,
    requires_elevation=False,
)
def get_gpu_info(args: GpuInput) -> ToolResult:
    # 1. Query Win32_VideoController via PowerShell CIM
    ps_script = """
    Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, DriverDate, AdapterRAM, VideoProcessor, Status | ConvertTo-Json -Depth 3
    """
    ok, ps_gpus, err = run_powershell_json(ps_script, timeout_s=10)
    if not ok:
        return ToolResult.fail(f"Failed to query GPU info: {err}")

    adapters = []
    if ps_gpus:
        items = ps_gpus if isinstance(ps_gpus, list) else [ps_gpus]
        for it in items:
            vram = it.get("AdapterRAM") or 0
            # DriverDate from CIM can be formatted as datetime or dictionary
            driver_date = str(it.get("DriverDate") or "Unknown")
            if isinstance(it.get("DriverDate"), dict) and "value" in it["DriverDate"]:
                driver_date = str(it["DriverDate"]["value"])

            adapters.append({
                "name": str(it.get("Name", "Unknown")),
                "driver_version": str(it.get("DriverVersion", "Unknown")),
                "driver_date": driver_date,
                "vram": format_bytes(vram) if vram > 0 else "Shared",
                "processor": str(it.get("VideoProcessor", "")),
                "status": str(it.get("Status", "OK")),
            })

    # 2. Check for nvidia-smi
    nvidia_data = None
    nvidia_smi_path = shutil.which("nvidia-smi") or r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    try:
        res = subprocess.run(
            [
                nvidia_smi_path,
                "--query-gpu=name,driver_version,temperature.gpu,utilization.gpu,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().split(",")]
            if len(parts) >= 6:
                nvidia_data = {
                    "name": parts[0],
                    "driver_version": parts[1],
                    "temperature_c": int(parts[2]) if parts[2].isdigit() else parts[2],
                    "utilization_percent": int(parts[3]) if parts[3].isdigit() else parts[3],
                    "memory_total_mb": int(parts[4]) if parts[4].isdigit() else parts[4],
                    "memory_used_mb": int(parts[5]) if parts[5].isdigit() else parts[5],
                }
    except Exception:
        nvidia_data = None

    data = {
        "adapters": adapters,
        "nvidia_smi": nvidia_data,
    }

    summary_lines = []
    for a in adapters:
        summary_lines.append(f"- {a['name']} | Driver: {a['driver_version']} ({a['driver_date']}) | VRAM: {a['vram']}")

    if nvidia_data:
        summary_lines.append(
            f"NVIDIA Telemetry: Temp {nvidia_data['temperature_c']}°C, "
            f"GPU Util {nvidia_data['utilization_percent']}%, "
            f"VRAM {nvidia_data['memory_used_mb']}/{nvidia_data['memory_total_mb']} MB"
        )

    summary = "GPU Adapters:\n" + "\n".join(summary_lines)
    return ToolResult.success(data=data, summary=summary)

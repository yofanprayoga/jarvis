"""Tool: system.get_cpu (Section 7.2)."""

from __future__ import annotations

import psutil
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool


class CpuInput(BaseModel):
    interval_s: float = Field(
        default=1.0,
        ge=0.2,
        le=10.0,
        description="Sampling duration in seconds to calculate CPU utilization delta",
    )


@tool(
    name="system.get_cpu",
    risk=Risk.OBSERVE,
    description="Get CPU metrics: overall and per-core utilization, clock frequency, and throttling detection.",
    input_model=CpuInput,
    timeout_s=15,
    requires_elevation=False,
)
def get_cpu(args: CpuInput) -> ToolResult:
    # Sample CPU usage over interval
    per_core_pct = psutil.cpu_percent(interval=args.interval_s, percpu=True)
    total_pct = sum(per_core_pct) / len(per_core_pct) if per_core_pct else 0.0

    # CPU frequencies
    freq = psutil.cpu_freq()
    current_mhz = round(freq.current, 1) if freq else None
    base_mhz = round(freq.max, 1) if freq and freq.max else None
    min_mhz = round(freq.min, 1) if freq and freq.min else None

    # Throttling indicator
    throttling_hint = False
    if current_mhz and base_mhz and base_mhz > 0:
        # If current frequency is significantly below base clock while total CPU is high (>60%)
        if total_pct > 60.0 and (current_mhz / base_mhz) < 0.65:
            throttling_hint = True

    data = {
        "total_percent": round(total_pct, 1),
        "per_core_percent": [round(p, 1) for p in per_core_pct],
        "core_count_physical": psutil.cpu_count(logical=False),
        "core_count_logical": len(per_core_pct),
        "current_frequency_mhz": current_mhz,
        "base_frequency_mhz": base_mhz,
        "throttling_hint": throttling_hint,
    }

    cores_str = ", ".join(f"C{i}:{p}%" for i, p in enumerate(data["per_core_percent"]))
    freq_str = f"{current_mhz} MHz (Base: {base_mhz} MHz)" if current_mhz else "Unknown"
    throttle_str = " [WARNING: Possible thermal/power throttling detected]" if throttling_hint else ""

    summary = (
        f"Total CPU Usage: {total_pct:.1f}%\n"
        f"Frequency: {freq_str}{throttle_str}\n"
        f"Per-core: {cores_str}"
    )

    return ToolResult.success(data=data, summary=summary)

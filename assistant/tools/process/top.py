"""Tool: process.list_top (Section 7.2)."""

from __future__ import annotations

import time
from typing import Literal
import psutil
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import format_bytes


class TopProcessInput(BaseModel):
    by: Literal["cpu", "memory", "disk"] = Field(
        default="cpu",
        description="Metric to sort top processes by: 'cpu', 'memory', or 'disk'",
    )
    count: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Number of top processes to return (1-30)",
    )
    sample_interval_s: float = Field(
        default=1.0,
        ge=0.2,
        le=5.0,
        description="Sampling interval in seconds for calculating CPU or disk I/O rate",
    )


@tool(
    name="process.list_top",
    risk=Risk.OBSERVE,
    description="List top processes sorted by CPU, memory, or disk I/O consumption.",
    input_model=TopProcessInput,
    timeout_s=15,
    requires_elevation=False,
)
def list_top_processes(args: TopProcessInput) -> ToolResult:
    results = []

    if args.by == "memory":
        for p in psutil.process_iter(["pid", "name", "memory_info", "memory_percent"]):
            try:
                info = p.info
                rss = info["memory_info"].rss if info.get("memory_info") else 0
                results.append({
                    "pid": info["pid"],
                    "name": info["name"] or "Unknown",
                    "mem_bytes": rss,
                    "mem_str": format_bytes(rss),
                    "mem_percent": round(info.get("memory_percent") or 0.0, 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        results.sort(key=lambda x: x["mem_bytes"], reverse=True)
        top_procs = results[:args.count]

        summary_lines = [
            f"- {p['name']} (PID: {p['pid']}): {p['mem_str']} ({p['mem_percent']}%)"
            for p in top_procs
        ]
        summary = f"Top {len(top_procs)} processes by RAM:\n" + "\n".join(summary_lines)

    elif args.by == "cpu":
        procs = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                p.cpu_percent(None)  # first sample
                procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        time.sleep(args.sample_interval_s)

        for p in procs:
            try:
                cpu_pct = p.cpu_percent(None)
                mem = p.memory_info().rss
                results.append({
                    "pid": p.pid,
                    "name": p.name(),
                    "cpu_percent": round(cpu_pct, 1),
                    "mem_str": format_bytes(mem),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        results.sort(key=lambda x: x["cpu_percent"], reverse=True)
        top_procs = results[:args.count]

        summary_lines = [
            f"- {p['name']} (PID: {p['pid']}): {p['cpu_percent']}% CPU (RAM: {p['mem_str']})"
            for p in top_procs
        ]
        summary = f"Top {len(top_procs)} processes by CPU ({args.sample_interval_s}s sample):\n" + "\n".join(summary_lines)

    else:  # disk I/O
        procs_io = {}
        for p in psutil.process_iter(["pid", "name"]):
            try:
                io = p.io_counters()
                procs_io[p.pid] = (p, io, time.perf_counter())
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue

        time.sleep(args.sample_interval_s)

        for pid, (p, io_start, t_start) in procs_io.items():
            try:
                io_end = p.io_counters()
                t_end = time.perf_counter()
                elapsed = max(0.001, t_end - t_start)
                r_bytes = max(0, io_end.read_bytes - io_start.read_bytes)
                w_bytes = max(0, io_end.write_bytes - io_start.write_bytes)
                total_kb_s = round((r_bytes + w_bytes) / elapsed / 1024.0, 1)

                results.append({
                    "pid": pid,
                    "name": p.name(),
                    "io_speed_kbs": total_kb_s,
                    "read_kbs": round(r_bytes / elapsed / 1024.0, 1),
                    "write_kbs": round(w_bytes / elapsed / 1024.0, 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue

        results.sort(key=lambda x: x["io_speed_kbs"], reverse=True)
        top_procs = results[:args.count]

        summary_lines = [
            f"- {p['name']} (PID: {p['pid']}): {p['io_speed_kbs']} KB/s (R: {p['read_kbs']} KB/s, W: {p['write_kbs']} KB/s)"
            for p in top_procs
        ]
        summary = f"Top {len(top_procs)} processes by Disk I/O ({args.sample_interval_s}s sample):\n" + "\n".join(summary_lines)

    return ToolResult.success(data={"by": args.by, "processes": top_procs}, summary=summary)

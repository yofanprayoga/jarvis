"""Tool: services.list (Section 7.2)."""

from __future__ import annotations

from typing import Literal, Optional
import psutil
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool


class ServicesInput(BaseModel):
    status: Literal["all", "running", "stopped"] = Field(
        default="all",
        description="Filter by service operational state: 'all', 'running', or 'stopped'",
    )
    start_type: Literal["all", "automatic", "manual", "disabled"] = Field(
        default="all",
        description="Filter by startup type: 'all', 'automatic', 'manual', or 'disabled'",
    )
    name_filter: Optional[str] = Field(
        default=None,
        description="Filter service name or display name by case-insensitive substring",
    )
    limit: int = Field(
        default=30,
        ge=1,
        le=200,
        description="Maximum number of services to return in output",
    )


@tool(
    name="services.list",
    risk=Risk.OBSERVE,
    description="List Windows services with their current operational state and startup type, filterable by state, type, or name.",
    input_model=ServicesInput,
    timeout_s=15,
    requires_elevation=False,
)
def list_services(args: ServicesInput) -> ToolResult:
    matched = []

    for s in psutil.win_service_iter():
        try:
            info = s.as_dict()
            s_name = info.get("name") or ""
            s_display = info.get("display_name") or ""
            s_status = info.get("status") or "unknown"
            s_start = info.get("start_type") or "unknown"

            # Filter by status
            if args.status != "all" and s_status.lower() != args.status.lower():
                continue

            # Filter by start type
            if args.start_type != "all" and args.start_type.lower() not in s_start.lower():
                continue

            # Filter by name substring
            if args.name_filter:
                sub = args.name_filter.lower()
                if sub not in s_name.lower() and sub not in s_display.lower():
                    continue

            matched.append({
                "name": s_name,
                "display_name": s_display,
                "status": s_status,
                "start_type": s_start,
                "binpath": info.get("binpath", ""),
            })
        except Exception:
            continue

    total_matched = len(matched)
    results = matched[:args.limit]

    summary_lines = [
        f"- [{s['status']}|{s['start_type']}] {s['name']} ({s['display_name'][:40]})"
        for s in results[:20]
    ]
    if total_matched > 20:
        summary_lines.append(f"... and {total_matched - 20} more services matching query.")

    summary = (
        f"Windows Services ({total_matched} matching):\n"
        + ("\n".join(summary_lines) if summary_lines else "- No matching services found")
    )

    return ToolResult.success(
        data={"total_matched": total_matched, "returned_count": len(results), "services": results},
        summary=summary,
    )

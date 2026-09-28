"""Event log diagnostic tools (Section 7.2 Phase 4 & Appendix D)."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import run_powershell_json


class EventsQueryInput(BaseModel):
    log_name: str = Field(default="System", description="Event log name ('System', 'Application', etc.)")
    event_ids: Optional[list[int]] = Field(default=None, description="List of Event IDs to filter (e.g. [1001, 41])")
    providers: Optional[list[str]] = Field(default=None, description="List of provider names (e.g. ['Microsoft-Windows-Kernel-Power'])")
    days: int = Field(default=14, ge=1, le=90, description="Time window in days")
    max_count: int = Field(default=25, ge=1, le=100, description="Maximum events to return")


class CrashSummaryInput(BaseModel):
    days: int = Field(default=14, ge=1, le=90, description="Time window in days to analyze crash events")


@tool(
    name="events.query",
    risk=Risk.OBSERVE,
    description="Query Windows Event Log entries filtered by log name, event IDs, providers, and time window.",
    input_model=EventsQueryInput,
    timeout_s=25,
    requires_elevation=False,
)
def events_query(args: EventsQueryInput) -> ToolResult:
    id_filter_code = ""
    if args.event_ids:
        ids_str = ",".join(str(i) for i in args.event_ids)
        id_filter_code = f"Id = @({ids_str});"

    prov_filter_code = ""
    if args.providers:
        provs_str = ",".join(f"'{p}'" for p in args.providers)
        prov_filter_code = f"ProviderName = @({provs_str});"

    ps_script = f"""
    $startTime = (Get-Date).AddDays(-{args.days})
    $filter = @{{
        LogName = '{args.log_name}';
        StartTime = $startTime;
        {id_filter_code}
        {prov_filter_code}
    }}
    try {{
        $events = Get-WinEvent -FilterHashtable $filter -MaxEvents {args.max_count} -ErrorAction Stop |
            Select-Object Id, TimeCreated, ProviderName, LevelDisplayName, Message |
            ConvertTo-Json -Depth 3
        $events
    }} catch {{
        "[]"
    }}
    """

    ok, ps_data, err = run_powershell_json(ps_script, timeout_s=20)
    if not ok:
        return ToolResult.fail(f"Failed to query event log: {err}")

    events = []
    if ps_data:
        raw_list = ps_data if isinstance(ps_data, list) else [ps_data]
        for it in raw_list:
            if not isinstance(it, dict) or not it.get("Id"):
                continue
            tc = str(it.get("TimeCreated") or "")
            if isinstance(it.get("TimeCreated"), dict) and "value" in it["TimeCreated"]:
                tc = str(it["TimeCreated"]["value"])

            msg = str(it.get("Message") or "").strip().replace("\r", " ")
            msg_short = msg[:200] if len(msg) > 200 else msg
            events.append({
                "id": it.get("Id"),
                "time": tc,
                "provider": it.get("ProviderName"),
                "level": it.get("LevelDisplayName"),
                "message": msg_short,
            })

    summary_lines = [
        f"- [{e['time'][:19]}] ID {e['id']} ({e['provider']}): {e['message'][:80]}"
        for e in events[:10]
    ]
    if len(events) > 10:
        summary_lines.append(f"... and {len(events) - 10} more events")

    summary = (
        f"Found {len(events)} events in {args.log_name} (last {args.days} days):\n"
        + ("\n".join(summary_lines) if summary_lines else "- No events matched filter")
    )

    return ToolResult.success(data={"count": len(events), "events": events}, summary=summary)


@tool(
    name="events.get_crash_summary",
    risk=Risk.OBSERVE,
    description="Analyze critical Windows crash, BSOD, reboot, WHEA hardware, disk, and application error events.",
    input_model=CrashSummaryInput,
    timeout_s=30,
    requires_elevation=False,
)
def get_crash_summary(args: CrashSummaryInput) -> ToolResult:
    ps_script = f"""
    $startTime = (Get-Date).AddDays(-{args.days})
    $sysFilter = @{{
        LogName = 'System';
        StartTime = $startTime;
        Id = @(1001, 41, 6008, 17, 18, 19, 47, 4101, 7, 51, 153, 129)
    }}
    $appFilter = @{{
        LogName = 'Application';
        StartTime = $startTime;
        Id = @(1000, 1002)
    }}

    $sysEvents = try {{ Get-WinEvent -FilterHashtable $sysFilter -MaxEvents 50 -ErrorAction SilentlyContinue | Select-Object Id, TimeCreated, ProviderName, LevelDisplayName, Message }} catch {{ @() }}
    $appEvents = try {{ Get-WinEvent -FilterHashtable $appFilter -MaxEvents 50 -ErrorAction SilentlyContinue | Select-Object Id, TimeCreated, ProviderName, LevelDisplayName, Message }} catch {{ @() }}

    @{{
        SystemEvents = @($sysEvents)
        AppEvents = @($appEvents)
    }} | ConvertTo-Json -Depth 4
    """

    ok, ps_data, err = run_powershell_json(ps_script, timeout_s=25)
    if not ok:
        return ToolResult.fail(f"Failed to query crash summary: {err}")

    sys_events = []
    app_events = []
    if isinstance(ps_data, dict):
        raw_sys = ps_data.get("SystemEvents")
        if isinstance(raw_sys, list):
            sys_events = [e for e in raw_sys if isinstance(e, dict) and e.get("Id")]
        elif isinstance(raw_sys, dict) and raw_sys.get("Id"):
            sys_events = [raw_sys]

        raw_app = ps_data.get("AppEvents")
        if isinstance(raw_app, list):
            app_events = [e for e in raw_app if isinstance(e, dict) and e.get("Id")]
        elif isinstance(raw_app, dict) and raw_app.get("Id"):
            app_events = [raw_app]

    # Metrics aggregation
    bugcheck_1001 = [e for e in sys_events if e.get("Id") == 1001]
    kernel_power_41 = [e for e in sys_events if e.get("Id") == 41]
    unexpected_shutdown_6008 = [e for e in sys_events if e.get("Id") == 6008]
    whea_events = [e for e in sys_events if e.get("Id") in (17, 18, 19, 47)]
    display_tdr_4101 = [e for e in sys_events if e.get("Id") == 4101]
    disk_errors = [e for e in sys_events if e.get("Id") in (7, 51, 153, 129)]
    app_crashes_1000 = [e for e in app_events if e.get("Id") == 1000]
    app_hangs_1002 = [e for e in app_events if e.get("Id") == 1002]

    # Extract bugcheck codes from BugCheck 1001 messages if present
    extracted_bugcheck_codes = []
    import re
    for bc in bugcheck_1001:
        msg = bc.get("Message", "")
        # BugCheck 1001 messages contain e.g. "The computer has rebooted from a bugcheck.  The bugcheck was: 0x00000116 ..."
        m = re.search(r"0x[0-9a-fA-F]{6,8}", msg)
        if m:
            extracted_bugcheck_codes.append(m.group(0))

    data = {
        "days_analyzed": args.days,
        "bugcheck_1001_count": len(bugcheck_1001),
        "bugcheck_codes": extracted_bugcheck_codes,
        "kernel_power_41_count": len(kernel_power_41),
        "unexpected_shutdown_6008_count": len(unexpected_shutdown_6008),
        "whea_hardware_error_count": len(whea_events),
        "display_tdr_count": len(display_tdr_4101),
        "disk_io_error_count": len(disk_errors),
        "app_crash_count": len(app_crashes_1000),
        "app_hang_count": len(app_hangs_1002),
        "recent_app_crashes": [
            {
                "time": str(e.get("TimeCreated", ""))[:19],
                "message": str(e.get("Message", ""))[:120],
            }
            for e in app_crashes_1000[:5]
        ],
    }

    summary_items = []
    summary_items.append(f"BSOD Bugcheck (1001): {len(bugcheck_1001)} kali (Kode: {extracted_bugcheck_codes or 'none'})")
    summary_items.append(f"Mati Mendadak / Kernel-Power (41/6008): {len(kernel_power_41) + len(unexpected_shutdown_6008)} kali")
    summary_items.append(f"Error Hardware WHEA: {len(whea_events)} kali")
    summary_items.append(f"Display Driver TDR (VGA Crash): {len(display_tdr_4101)} kali")
    summary_items.append(f"Error Disk / Storage Controller: {len(disk_errors)} kali")
    summary_items.append(f"Aplikasi Crash (1000) / Hang (1002): {len(app_crashes_1000)} crash, {len(app_hangs_1002)} hang")

    summary = (
        f"Ringkasan Masalah Sistem ({args.days} hari terakhir):\n"
        + "\n".join(f"- {it}" for it in summary_items)
    )

    return ToolResult.success(data=data, summary=summary)

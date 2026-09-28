"""Tool: startup.list_items (Section 7.2)."""

from __future__ import annotations

from pydantic import BaseModel
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import run_powershell_json


class StartupInput(BaseModel):
    pass


@tool(
    name="startup.list_items",
    risk=Risk.OBSERVE,
    description="List all startup items configured in Registry Run keys, Startup folders, and logon Scheduled Tasks.",
    input_model=StartupInput,
    timeout_s=20,
    requires_elevation=False,
)
def list_startup_items(args: StartupInput) -> ToolResult:
    ps_script = """
    $startup = Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location, User | ConvertTo-Json -Depth 2
    $tasks = Get-ScheduledTask -ErrorAction SilentlyContinue |
        Where-Object { $_.State -ne 'Disabled' -and ($_.Triggers | Where-Object { $_.CimClass.CimClassName -match 'LogonTrigger' }) } |
        Select-Object -First 25 TaskName, TaskPath, State | ConvertTo-Json -Depth 2
    @{ StartupEntries = ($startup | ConvertFrom-Json); ScheduledLogonTasks = ($tasks | ConvertFrom-Json) } | ConvertTo-Json -Depth 4
    """

    ok, ps_data, err = run_powershell_json(ps_script, timeout_s=15)
    if not ok:
        return ToolResult.fail(f"Failed to query startup items: {err}")

    startup_entries = []
    logon_tasks = []

    if isinstance(ps_data, dict):
        raw_startup = ps_data.get("StartupEntries")
        if isinstance(raw_startup, list):
            startup_entries = raw_startup
        elif isinstance(raw_startup, dict):
            startup_entries = [raw_startup]

        raw_tasks = ps_data.get("ScheduledLogonTasks")
        if isinstance(raw_tasks, list):
            logon_tasks = raw_tasks
        elif isinstance(raw_tasks, dict):
            logon_tasks = [raw_tasks]

    data = {
        "startup_entries_count": len(startup_entries),
        "startup_entries": startup_entries,
        "logon_tasks_count": len(logon_tasks),
        "logon_tasks": logon_tasks,
    }

    entry_lines = [
        f"- {s.get('Name', 'Unknown')}: {s.get('Command', '')[:60]} ({s.get('Location', '')})"
        for s in startup_entries[:15]
    ]
    task_lines = [
        f"- {t.get('TaskName', 'Unknown')} ({t.get('TaskPath', '')})"
        for t in logon_tasks[:10]
    ]

    summary = (
        f"Startup Entries ({len(startup_entries)}):\n"
        + ("\n".join(entry_lines) if entry_lines else "- None found")
        + f"\nLogon Scheduled Tasks ({len(logon_tasks)}):\n"
        + ("\n".join(task_lines) if task_lines else "- None found")
    )

    return ToolResult.success(data=data, summary=summary)

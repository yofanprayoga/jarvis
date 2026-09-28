"""Tool: system.get_drivers (Section 7.2)."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import run_powershell_json


class DriversInput(BaseModel):
    class_name: Optional[str] = Field(
        default=None,
        description="Filter drivers by device class (e.g., 'Display', 'Net', 'MEDIA', 'DiskDrive', 'System')",
    )
    name_filter: Optional[str] = Field(
        default=None,
        description="Filter drivers by device name substring (e.g. 'NVIDIA', 'Intel', 'Realtek')",
    )
    limit: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Maximum number of driver records to return",
    )


@tool(
    name="system.get_drivers",
    risk=Risk.OBSERVE,
    description="List signed hardware drivers with versions, release dates, and providers, filterable by class or name.",
    input_model=DriversInput,
    timeout_s=20,
    requires_elevation=False,
)
def get_drivers(args: DriversInput) -> ToolResult:
    # Build filter conditions safely inside fixed script
    class_filter_expr = f"$_.DeviceClass -like '*{args.class_name}*'" if args.class_name else "$true"
    name_filter_expr = f"$_.DeviceName -like '*{args.name_filter}*'" if args.name_filter else "$true"

    ps_script = f"""
    Get-CimInstance Win32_PnPSignedDriver |
        Where-Object {{ ({class_filter_expr}) -and ({name_filter_expr}) -and $_.DeviceName }} |
        Select-Object -First {args.limit} DeviceName, DeviceClass, DriverVersion, DriverDate, DriverProviderName, IsSigned |
        ConvertTo-Json -Depth 2
    """

    ok, ps_drivers, err = run_powershell_json(ps_script, timeout_s=15)
    if not ok:
        return ToolResult.fail(f"Failed to query system drivers: {err}")

    drivers = []
    if ps_drivers:
        items = ps_drivers if isinstance(ps_drivers, list) else [ps_drivers]
        for it in items:
            driver_date = str(it.get("DriverDate") or "Unknown")
            if isinstance(it.get("DriverDate"), dict) and "value" in it["DriverDate"]:
                driver_date = str(it["DriverDate"]["value"])

            drivers.append({
                "device_name": str(it.get("DeviceName", "Unknown")),
                "device_class": str(it.get("DeviceClass", "Unknown")),
                "version": str(it.get("DriverVersion", "Unknown")),
                "date": driver_date,
                "provider": str(it.get("DriverProviderName", "Unknown")),
                "signed": bool(it.get("IsSigned", True)),
            })

    summary_lines = [
        f"- [{d['device_class']}] {d['device_name']} v{d['version']} ({d['date']}) by {d['provider']}"
        for d in drivers[:15]
    ]
    if len(drivers) > 15:
        summary_lines.append(f"... and {len(drivers) - 15} more drivers (see data)")

    summary = (
        f"Found {len(drivers)} drivers matching criteria:\n"
        + ("\n".join(summary_lines) if summary_lines else "- No drivers found")
    )

    return ToolResult.success(data={"count": len(drivers), "drivers": drivers}, summary=summary)

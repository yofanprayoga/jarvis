"""Bugcheck Lookup Seed Table and Tool (Section 7.2 & Appendix C)."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool

# Seed table mapping normalized hex strings (lowercase without leading zeroes) to descriptions
BUGCHECK_DATABASE: dict[str, dict[str, str]] = {
    "a": {
        "name": "IRQL_NOT_LESS_OR_EQUAL",
        "code_hex": "0x0000000A",
        "meaning": "An operating system process or driver attempted to access a memory address without appropriate authorization.",
        "common_causes": "Faulty or outdated hardware driver, corrupted system files, or defective RAM.",
    },
    "1a": {
        "name": "MEMORY_MANAGEMENT",
        "code_hex": "0x0000001A",
        "meaning": "A severe memory management error occurred.",
        "common_causes": "Defective RAM stick, corrupted paging file, or driver memory leak.",
    },
    "1e": {
        "name": "KMODE_EXCEPTION_NOT_HANDLED",
        "code_hex": "0x0000001E",
        "meaning": "A kernel-mode program generated an exception that the error handler did not catch.",
        "common_causes": "Kernel-mode driver bug, faulty system service, or incompatible hardware.",
    },
    "3b": {
        "name": "SYSTEM_SERVICE_EXCEPTION",
        "code_hex": "0x0000003B",
        "meaning": "An exception occurred while executing routine that transitions from non-privileged code to privileged code.",
        "common_causes": "Graphics/video driver, antivirus/anticheat filter driver, or GUI subsystem bug.",
    },
    "50": {
        "name": "PAGE_FAULT_IN_NONPAGED_AREA",
        "code_hex": "0x00000050",
        "meaning": "Invalid system memory was referenced that cannot be paged in.",
        "common_causes": "Faulty driver, bad RAM, antivirus software, or NTFS disk corruption.",
    },
    "7b": {
        "name": "INACCESSIBLE_BOOT_DEVICE",
        "code_hex": "0x0000007B",
        "meaning": "Windows could not access the system partition during boot.",
        "common_causes": "Storage controller driver, SATA/AHCI/RAID BIOS mode change, or disk drive failure.",
    },
    "7e": {
        "name": "SYSTEM_THREAD_EXCEPTION_NOT_HANDLED",
        "code_hex": "0x0000007E",
        "meaning": "A system thread generated an exception that the error handler did not catch.",
        "common_causes": "Faulty driver, incompatible BIOS, or hardware failure.",
    },
    "9f": {
        "name": "DRIVER_POWER_STATE_FAILURE",
        "code_hex": "0x0000009F",
        "meaning": "A driver is in an inconsistent or invalid power state during sleep, hibernate, or resume.",
        "common_causes": "Outdated Wi-Fi/Bluetooth or graphics driver handling power transitions poorly.",
    },
    "d1": {
        "name": "DRIVER_IRQL_NOT_LESS_OR_EQUAL",
        "code_hex": "0x000000D1",
        "meaning": "A kernel driver attempted to access pageable memory at an invalid IRQL.",
        "common_causes": "Network/Wi-Fi driver, storage driver, or third-party filter driver.",
    },
    "ef": {
        "name": "CRITICAL_PROCESS_DIED",
        "code_hex": "0x000000EF",
        "meaning": "A critical system process terminated unexpectedly.",
        "common_causes": "System file corruption, failed disk/SSD, or driver crash affecting core OS services.",
    },
    "116": {
        "name": "VIDEO_TDR_FAILURE",
        "code_hex": "0x00000116",
        "meaning": "The graphics driver stopped responding and failed to recover within the timeout period.",
        "common_causes": "Corrupted graphics driver (NVIDIA/Intel), GPU overheating, or unstable GPU clock.",
    },
    "124": {
        "name": "WHEA_UNCORRECTABLE_ERROR",
        "code_hex": "0x00000124",
        "meaning": "A fatal hardware error was detected by the Windows Hardware Error Architecture.",
        "common_causes": "Hardware defect: CPU voltage/clock, overheating, dying NVMe SSD, or failing RAM.",
    },
    "133": {
        "name": "DPC_WATCHDOG_VIOLATION",
        "code_hex": "0x00000133",
        "meaning": "The DPC watchdog detected a single long-running deferred procedure call or hung ISR.",
        "common_causes": "SSD firmware bug, outdated storage/SATA controller driver, or Wi-Fi driver hang.",
    },
    "139": {
        "name": "KERNEL_SECURITY_CHECK_FAILURE",
        "code_hex": "0x00000139",
        "meaning": "A kernel component detected corruption of a critical data structure.",
        "common_causes": "Driver bug corrupting memory structures, or bad RAM.",
    },
}


def normalize_code(raw_code: str | int) -> str:
    """Normalize bugcheck representation to stripped hex string."""
    if isinstance(raw_code, int):
        return hex(raw_code).lstrip("0x").lower()
    s = str(raw_code).strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return s.lstrip("0") or "0"


class BugcheckLookupInput(BaseModel):
    code: str = Field(description="Bugcheck code as hex string (e.g. '0x00000116', '0x124', '133') or decimal")


@tool(
    name="bugcheck.lookup",
    risk=Risk.OBSERVE,
    description="Look up a Windows BSOD bugcheck code in the offline database to get its name, meaning, and common causes.",
    input_model=BugcheckLookupInput,
    timeout_s=5,
    requires_elevation=False,
)
def bugcheck_lookup(args: BugcheckLookupInput) -> ToolResult:
    norm = normalize_code(args.code)
    match = BUGCHECK_DATABASE.get(norm)

    if not match:
        # Try decimal conversion if pure digits
        if args.code.isdigit():
            norm_dec = normalize_code(int(args.code))
            match = BUGCHECK_DATABASE.get(norm_dec)

    if match:
        summary = (
            f"Bugcheck: {match['name']} ({match['code_hex']})\n"
            f"Arti: {match['meaning']}\n"
            f"Penyebab Umum: {match['common_causes']}"
        )
        return ToolResult.success(data=match, summary=summary)

    # Unknown code
    fallback_data = {
        "name": f"BUGCHECK_0x{norm.upper()}",
        "code_hex": f"0x{norm.upper()}",
        "meaning": "Kode bugcheck tidak ada di database lokal.",
        "common_causes": "Driver tidak stabil, korupsi file sistem, atau masalah memori.",
    }
    summary = f"Bugcheck 0x{norm.upper()}: Tidak ditemukan di database bawaan."
    return ToolResult.success(data=fallback_data, summary=summary)

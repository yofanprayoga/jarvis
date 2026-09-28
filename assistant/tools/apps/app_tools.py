"""Application resolution, inspection, and CLI help tools (Section 7.2 Phase 7)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.system.helpers import run_powershell_json
from assistant.tools.launch.app_launcher import app_indexer


class AppResolveInput(BaseModel):
    name: str = Field(description="Name or keyword of the application to find (e.g. 'notepad', 'chrome', 'steam')")


class AppInspectInput(BaseModel):
    app_path: Optional[str] = Field(default=None, description="Direct executable path, or leave empty if name is given")
    name: Optional[str] = Field(default=None, description="Application name to resolve and inspect")


class AppCliHelpInput(BaseModel):
    app_path: str = Field(description="Path to executable or command name in System32/PATH")
    flag: str = Field(default="/?", description="Help flag to use ('/?', '--help', '-h')")


@tool(
    name="apps.resolve",
    risk=Risk.OBSERVE,
    description="Find an application executable path across Start Menu, App Paths registry, running processes, and PATH.",
    input_model=AppResolveInput,
    timeout_s=15,
    requires_elevation=False,
)
def resolve_app_tool(args: AppResolveInput) -> ToolResult:
    target = args.name.strip()

    # 1. Check Start Menu index
    resolved = app_indexer.resolve(target)
    matches = []
    if resolved:
        abs_path = shutil.which(resolved) or resolved
        matches.append({
            "source": "Start Menu / Allowlist",
            "path": abs_path,
            "executable_name": Path(abs_path).name,
        })

    # 2. Check shutil.which (PATH and current working directory)
    which_path = shutil.which(target) or shutil.which(f"{target}.exe")
    if which_path and not any(m["path"].lower() == which_path.lower() for m in matches):
        matches.append({
            "source": "System PATH",
            "path": which_path,
            "executable_name": Path(which_path).name,
        })

    # 3. Check App Paths in Registry via PowerShell
    ps_query = f"""
    $target = '{target}'
    $candidates = @(
        "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\$target.exe",
        "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\$target.exe"
    )
    $results = @()
    foreach ($c in $candidates) {{
        $val = (Get-ItemProperty -Path $c -ErrorAction SilentlyContinue).'(default)'
        if ($val -and (Test-Path $val)) {{
            $results += @{{ Path = $val; Source = "Registry App Paths" }}
        }}
    }}
    $results | ConvertTo-Json
    """
    ok, reg_data, _ = run_powershell_json(ps_query, timeout_s=8)
    if ok and reg_data:
        raw_list = reg_data if isinstance(reg_data, list) else [reg_data]
        for it in raw_list:
            if isinstance(it, dict) and it.get("Path"):
                p_str = it["Path"]
                if not any(m["path"].lower() == p_str.lower() for m in matches):
                    matches.append({
                        "source": it.get("Source", "Registry App Paths"),
                        "path": p_str,
                        "executable_name": Path(p_str).name,
                    })

    if not matches:
        return ToolResult.fail(f"Aplikasi '{target}' tidak ditemukan di Start Menu, PATH, atau registry sistem.")

    summary_lines = [f"Ditemukan {len(matches)} kecocokan untuk aplikasi '{target}':"]
    for m in matches:
        summary_lines.append(f"- [{m['source']}] {m['path']}")

    return ToolResult.success(
        data={"query": target, "count": len(matches), "primary_path": matches[0]["path"], "matches": matches},
        summary="\n".join(summary_lines),
    )


@tool(
    name="apps.inspect",
    risk=Risk.OBSERVE,
    description="Inspect an application executable: publisher, Authenticode digital signature, version, related services and startup entries.",
    input_model=AppInspectInput,
    timeout_s=25,
    requires_elevation=False,
)
def inspect_app_tool(args: AppInspectInput) -> ToolResult:
    target_path = args.app_path
    if not target_path and args.name:
        res = resolve_app_tool.run(name=args.name)
        if res.ok and res.data.get("primary_path"):
            target_path = res.data["primary_path"]

    if target_path and not os.path.isfile(target_path):
        resolved_p = shutil.which(target_path) or shutil.which(f"{target_path}.exe")
        if resolved_p and os.path.isfile(resolved_p):
            target_path = resolved_p

    if not target_path or not os.path.isfile(target_path):
        return ToolResult.fail(f"File aplikasi tidak ditemukan atau tidak valid: '{target_path}'")

    p = Path(target_path).resolve()
    ps_inspect = f"""
    $file = '{str(p)}'
    $item = Get-Item -Path $file
    $vi = $item.VersionInfo
    $sig = Get-AuthenticodeSignature -FilePath $file

    @{{
        FileName = $item.Name;
        FullPath = $item.FullName;
        LengthBytes = $item.Length;
        CreationTime = $item.CreationTime.ToString("yyyy-MM-dd HH:mm:ss");
        FileVersion = $vi.FileVersion;
        ProductVersion = $vi.ProductVersion;
        CompanyName = $vi.CompanyName;
        FileDescription = $vi.FileDescription;
        SignatureStatus = $sig.Status.ToString();
        SignerSubject = $(if ($sig.SignerCertificate) {{ $sig.SignerCertificate.Subject }} else {{ "None" }});
        IsOSBinary = ($item.FullName -like "*\\Windows\\System32\\*" -or $item.FullName -like "*\\Windows\\SysWOW64\\*")
    }} | ConvertTo-Json
    """

    ok, ps_data, err = run_powershell_json(ps_inspect, timeout_s=15)
    if not ok or not isinstance(ps_data, dict):
        return ToolResult.fail(f"Gagal menginspeksi aplikasi: {err}")

    # Check related services
    ps_services = f"""
    Get-CimInstance Win32_Service |
        Where-Object {{ $_.PathName -like "*{p.name}*" }} |
        Select-Object Name, DisplayName, State, StartMode |
        ConvertTo-Json
    """
    _, s_data, _ = run_powershell_json(ps_services, timeout_s=10)
    services = []
    if s_data:
        raw_s = s_data if isinstance(s_data, list) else [s_data]
        services = [s for s in raw_s if isinstance(s, dict) and s.get("Name")]

    summary = (
        f"Inspeksi Aplikasi: {ps_data.get('FileName')}\n"
        f"- Lokasi: {ps_data.get('FullPath')}\n"
        f"- Penerbit (Publisher): {ps_data.get('CompanyName') or 'Tidak diketahui'}\n"
        f"- Deskripsi: {ps_data.get('FileDescription') or '-'}\n"
        f"- Versi: {ps_data.get('ProductVersion') or ps_data.get('FileVersion') or '-'}\n"
        f"- Status Signature Digital: {ps_data.get('SignatureStatus')} ({ps_data.get('SignerSubject')[:60]})\n"
        f"- Komponen Bawaan OS: {'Ya' if ps_data.get('IsOSBinary') else 'Tidak'}\n"
        f"- Layanan (Services) Terkait: {len(services)} layanan"
    )

    data = {
        "metadata": ps_data,
        "related_services": services,
    }

    return ToolResult.success(data=data, summary=summary)


@tool(
    name="apps.get_cli_help",
    risk=Risk.OBSERVE,
    description="Get CLI usage help (/? or --help) for system binaries and applications in System32 or PATH.",
    input_model=AppCliHelpInput,
    timeout_s=10,
    requires_elevation=False,
)
def get_cli_help_tool(args: AppCliHelpInput) -> ToolResult:
    # Resolve executable path
    cmd_name = args.app_path.strip()
    full_path = shutil.which(cmd_name) or cmd_name

    if not os.path.isfile(full_path):
        return ToolResult.fail(f"Executable '{cmd_name}' tidak ditemukan di PATH sistem.")

    # Security check: Check if path is in System32 or Windows directory
    win_dir = os.environ.get("SystemRoot", r"C:\Windows").lower()
    full_lower = full_path.lower()
    is_windows_tool = full_lower.startswith(win_dir)

    flag = args.flag if args.flag in ("/?", "--help", "-h", "-help") else "/?"

    try:
        proc = subprocess.run(
            [full_path, flag],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        output = proc.stdout or proc.stderr
        clean_output = output[:2000]

        summary = (
            f"Bantuan CLI '{Path(full_path).name} {flag}':\n"
            f"```text\n{clean_output}\n```"
        )
        return ToolResult.success(
            data={"path": full_path, "flag": flag, "is_system_tool": is_windows_tool, "output": clean_output},
            summary=summary,
        )
    except Exception as e:
        return ToolResult.fail(f"Gagal mengambil bantuan CLI: {e}")

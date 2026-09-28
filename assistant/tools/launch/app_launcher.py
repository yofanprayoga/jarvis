"""Application launcher and Start Menu indexer (Section 7.2 Phase 2)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool


class OpenAppInput(BaseModel):
    name: str = Field(description="Name or alias of the application to launch (e.g., 'chrome', 'brave', 'notepad')")


class AppIndexer:
    """Indexes installed application shortcuts from Start Menu and configuration."""

    def __init__(self, config_file: str = "config/apps.yaml") -> None:
        self.config_file = Path(config_file)
        self._index: dict[str, str] = {}
        self._allowed_apps: set[str] = set()
        self._load_config()
        self._scan_start_menu()

    def _load_config(self) -> None:
        if not self.config_file.is_file():
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            aliases = data.get("aliases", {})
            for k, v in aliases.items():
                self._index[str(k).lower().strip()] = str(v).strip()
            self._allowed_apps = {str(a).lower().strip() for a in data.get("allowed_apps", [])}
        except Exception:
            pass

    def _scan_start_menu(self) -> None:
        """Scan Start Menu folders for .lnk and .exe shortcuts."""
        roots = []
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
        programdata = os.environ.get("ProgramData")
        if programdata:
            roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")

        for root in roots:
            if not root.is_dir():
                continue
            try:
                for item in root.rglob("*.lnk"):
                    clean_name = item.stem.lower()
                    if clean_name not in self._index:
                        self._index[clean_name] = str(item)
            except Exception:
                continue

    def resolve(self, query: str) -> Optional[str]:
        """Resolve an application query to an executable or shortcut path."""
        q = query.lower().strip()

        # 1. Exact match in index
        if q in self._index:
            return self._index[q]

        # 2. Check if name matches start of an indexed entry
        for k, v in self._index.items():
            if k == q or k.startswith(f"{q} ") or f" {q}" in k:
                return v

        # 3. Check if executable exists in system PATH and is allowed
        resolved_path = shutil.which(q)
        if resolved_path:
            exe_name = Path(resolved_path).name.lower()
            if exe_name in self._allowed_apps or q in self._allowed_apps:
                return resolved_path

        return None

    def is_allowed(self, target: str) -> bool:
        """Check if target executable or shortcut is allowed by policy."""
        # Shortcuts from Start Menu are considered safe user applications
        if target.lower().endswith(".lnk"):
            return True
        basename = Path(target).name.lower()
        if basename in self._allowed_apps:
            return True
        # Check standard Windows system utilities
        safe_system_apps = {"calc.exe", "notepad.exe", "explorer.exe", "taskmgr.exe", "wt.exe", "cmd.exe"}
        if basename in safe_system_apps:
            return True
        return False


app_indexer = AppIndexer()


@tool(
    name="launch.open_app",
    risk=Risk.LOW_ACTION,
    description="Launch an application from the allowlist or Start Menu index.",
    input_model=OpenAppInput,
    timeout_s=10,
    requires_elevation=False,
)
def open_app(args: OpenAppInput) -> ToolResult:
    target = app_indexer.resolve(args.name)
    if not target:
        return ToolResult.fail(f"Aplikasi '{args.name}' tidak ditemukan di daftar aplikasi terpasang.")

    if not app_indexer.is_allowed(target):
        return ToolResult.fail(f"Aplikasi '{target}' belum ada di allowlist (L0).")

    try:
        if target.lower().endswith(".lnk") and hasattr(os, "startfile"):
            os.startfile(target)
        else:
            # Launch detached process without blocking
            subprocess.Popen(
                target,
                shell=True,
                creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0,
            )
        return ToolResult.success(
            data={"query": args.name, "target": target},
            summary=f"Membuka aplikasi: {args.name}"
        )
    except Exception as e:
        return ToolResult.fail(f"Gagal menjalankan aplikasi '{args.name}': {e}")

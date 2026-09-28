"""Folder launcher tool (Section 7.2 Phase 2)."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool


class OpenFolderInput(BaseModel):
    folder: str = Field(description="Name or path of known folder (e.g., 'downloads', 'documents', 'desktop', 'project')")


def resolve_folder(folder_name: str) -> Path | None:
    """Resolve aliases to physical directory paths."""
    fn = folder_name.lower().strip()
    home = Path.home()

    known_mappings = {
        "download": home / "Downloads",
        "downloads": home / "Downloads",
        "document": home / "Documents",
        "documents": home / "Documents",
        "dokumen": home / "Documents",
        "desktop": home / "Desktop",
        "picture": home / "Pictures",
        "pictures": home / "Pictures",
        "gambar": home / "Pictures",
        "video": home / "Videos",
        "videos": home / "Videos",
        "music": home / "Music",
        "musik": home / "Music",
        "project": Path("D:/project"),
        "projects": Path("D:/project"),
        "jarvis": Path("D:/project/jarvis"),
        "c": Path("C:/"),
        "c:": Path("C:/"),
        "d": Path("D:/"),
        "d:": Path("D:/"),
    }

    if fn in known_mappings:
        candidate = known_mappings[fn]
        if candidate.is_dir():
            return candidate

    # Check persistent memory for project locations or aliases
    try:
        from assistant.memory.manager import memory_manager
        clean_target = fn.replace("project ", "").strip()
        mem_path = (
            memory_manager.recall("project", clean_target)
            or memory_manager.recall("project", fn)
            or memory_manager.recall("alias", clean_target)
        )
        if mem_path:
            p_mem = Path(mem_path)
            if p_mem.is_dir():
                return p_mem.resolve()
    except Exception:
        pass

    # Check direct relative or absolute path
    p = Path(folder_name)
    if p.is_dir():
        return p.resolve()

    return None


@tool(
    name="launch.open_folder",
    risk=Risk.LOW_ACTION,
    description="Open a known folder or directory in Windows File Explorer.",
    input_model=OpenFolderInput,
    timeout_s=10,
    requires_elevation=False,
)
def open_folder(args: OpenFolderInput) -> ToolResult:
    target_path = resolve_folder(args.folder)
    if not target_path or not target_path.is_dir():
        return ToolResult.fail(f"Folder '{args.folder}' tidak ditemukan.")

    try:
        if hasattr(os, "startfile"):
            os.startfile(str(target_path))
        else:
            import subprocess
            subprocess.Popen(["explorer.exe", str(target_path)])
        return ToolResult.success(
            data={"folder": args.folder, "path": str(target_path)},
            summary=f"Membuka folder: {target_path}"
        )
    except Exception as e:
        return ToolResult.fail(f"Gagal membuka folder '{args.folder}': {e}")

"""Reproducible Packaging Prototype for Jarvis-lite.

Builds a clean, portable distribution package (ZIP) without requiring external compilers:
- Enforces strict migration boundaries (excludes user databases, browser profiles, credentials).
- Bundles core modules, default configs, playbooks, launcher batch scripts, and test suite.
- Generates SHA-256 checksum and package metadata manifest.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
STAGE_DIR = DIST_DIR / "jarvis-portable"
ZIP_OUTPUT = DIST_DIR / "jarvis-portable.zip"

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "browser_profile",
    "scratch",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".log",
    ".tmp",
}

EXCLUDE_EXACT_FILES = {
    "memory.db",
    "audit.db",
    "test_memory.db",
    "test_audit.db",
}


def compute_sha256(file_path: Path) -> str:
    """Calculate SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def copy_tree_filtered(src: Path, dst: Path) -> None:
    """Copy directory structure recursively while respecting exclusion rules."""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name in EXCLUDE_DIRS or entry.name in EXCLUDE_EXACT_FILES:
            continue
        if entry.suffix in EXCLUDE_EXTENSIONS:
            continue

        target = dst / entry.name
        if entry.is_dir():
            copy_tree_filtered(entry, target)
        else:
            shutil.copy2(entry, target)


def create_launchers(stage_path: Path) -> None:
    """Create lightweight Windows batch launchers in the root of the distribution."""
    launchers = {
        "jarvis-tray.bat": "@echo off\r\nstart \"Jarvis Tray\" .\\.venv\\Scripts\\python.exe -m assistant tray\r\n",
        "jarvis-chat.bat": "@echo off\r\n.\\.venv\\Scripts\\python.exe -m assistant chat\r\n",
        "jarvis-cli.bat": "@echo off\r\n.\\.venv\\Scripts\\python.exe -m assistant repl\r\n",
        "jarvis-check.bat": "@echo off\r\n.\\.venv\\Scripts\\python.exe -m assistant check\r\npause\r\n",
    }
    for filename, content in launchers.items():
        with open(stage_path / filename, "w", encoding="utf-8") as f:
            f.write(content)


def ensure_data_skeleton(stage_path: Path) -> None:
    """Ensure clean data directory skeleton exists without migrating user data."""
    data_dir = stage_path / "data"
    subdirs = ["backups", "cache", "logs", "models"]
    for s in subdirs:
        sub = data_dir / s
        sub.mkdir(parents=True, exist_ok=True)
        # Create empty .gitkeep placeholder
        (sub / ".gitkeep").touch()


def build_package() -> dict[str, str]:
    """Execute clean packaging build."""
    print("=== BUILDING JARVIS PORTABLE PACKAGING PROTOTYPE ===")

    # 1. Clean previous build artifacts
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Copy source code and definitions
    folders_to_copy = ["assistant", "config", "playbooks", "scripts", "eval", "tests"]
    for folder in folders_to_copy:
        src = PROJECT_ROOT / folder
        if src.exists():
            print(f"  Copying {folder}...")
            copy_tree_filtered(src, STAGE_DIR / folder)

    # 3. Copy top-level documents and project specs
    files_to_copy = ["pyproject.toml", "requirements.txt", "README.md", "DECISIONS.md", "plan.md"]
    for file in files_to_copy:
        src = PROJECT_ROOT / file
        if src.exists():
            shutil.copy2(src, STAGE_DIR / file)

    # 4. Create launchers and skeleton
    create_launchers(STAGE_DIR)
    ensure_data_skeleton(STAGE_DIR)

    # 5. Compress into Portable ZIP
    print(f"  Compressing into {ZIP_OUTPUT.name}...")
    with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(STAGE_DIR):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(STAGE_DIR)
                zipf.write(full_path, arcname=str(rel_path))

    # 6. Metadata Manifest
    size_bytes = ZIP_OUTPUT.stat().st_size
    size_mb = round(size_bytes / (1024 * 1024), 2)
    sha256 = compute_sha256(ZIP_OUTPUT)

    manifest_path = DIST_DIR / "manifest.json"
    manifest_content = (
        f'{{\n'
        f'  "artifact": "{ZIP_OUTPUT.name}",\n'
        f'  "type": "portable_zip",\n'
        f'  "size_bytes": {size_bytes},\n'
        f'  "size_mb": {size_mb},\n'
        f'  "sha256": "{sha256}",\n'
        f'  "target_os": "Windows 10/11 x64",\n'
        f'  "python_version": ">=3.11"\n'
        f'}}\n'
    )
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest_content)

    print(f"  Build complete: {ZIP_OUTPUT}")
    print(f"  Size: {size_mb} MB ({size_bytes} bytes)")
    print(f"  SHA-256: {sha256}")

    return {
        "artifact": str(ZIP_OUTPUT),
        "size_mb": str(size_mb),
        "sha256": sha256,
    }


if __name__ == "__main__":
    build_package()

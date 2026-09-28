"""Steam and launcher game discovery utilities (Section 7.2 Phase 7)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional


def find_steam_root() -> Optional[Path]:
    """Find the primary Steam installation directory."""
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam",
        Path(r"D:\Steam"),
        Path(r"E:\Steam"),
    ]
    for c in candidates:
        if (c / "steam.exe").is_file():
            return c
    return None


def parse_vdf_library_folders(steam_root: Path) -> list[Path]:
    """Parse Steam libraryfolders.vdf to find all Steam library paths across all drives."""
    lib_file = steam_root / "steamapps" / "libraryfolders.vdf"
    libraries = [steam_root]
    if not lib_file.is_file():
        return libraries

    try:
        content = lib_file.read_text(encoding="utf-8", errors="ignore")
        # Match "path"\s+"([^"]+)"
        matches = re.findall(r'"path"\s+"([^"]+)"', content)
        for m in matches:
            p = Path(m.replace(r"\\", r"\ "))
            if p.is_dir() and p not in libraries:
                libraries.append(p)
    except Exception:
        pass

    return libraries


def discover_steam_games() -> list[dict[str, Any]]:
    """Scan all Steam libraries for installed games via appmanifest_*.acf files."""
    games = []
    steam_root = find_steam_root()
    if not steam_root:
        return games

    libraries = parse_vdf_library_folders(steam_root)
    for lib in libraries:
        steamapps = lib / "steamapps"
        if not steamapps.is_dir():
            continue

        for manifest_file in steamapps.glob("appmanifest_*.acf"):
            try:
                content = manifest_file.read_text(encoding="utf-8", errors="ignore")
                app_id_m = re.search(r'"appid"\s+"(\d+)"', content)
                name_m = re.search(r'"name"\s+"([^"]+)"', content)
                install_dir_m = re.search(r'"installdir"\s+"([^"]+)"', content)
                size_m = re.search(r'"SizeOnDisk"\s+"(\d+)"', content)

                if name_m:
                    game_name = name_m.group(1).strip()
                    # Skip Steamworks Common Redistributables or Proton tools
                    if "Steamworks" in game_name or "Proton" in game_name:
                        continue

                    appid = app_id_m.group(1) if app_id_m else "0"
                    install_folder = steamapps / "common" / (install_dir_m.group(1) if install_dir_m else "")
                    size_bytes = int(size_m.group(1)) if size_m else 0

                    games.append({
                        "name": game_name,
                        "launcher": "Steam",
                        "appid": appid,
                        "install_path": str(install_folder.resolve()) if install_folder.is_dir() else str(install_folder),
                        "exists": install_folder.is_dir(),
                        "size_bytes": size_bytes,
                        "size_gb": round(size_bytes / (1024**3), 2),
                    })
            except Exception:
                pass

    return games


def discover_epic_games() -> list[dict[str, Any]]:
    """Scan Epic Games launcher manifests."""
    games = []
    prog_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    manifests_dir = prog_data / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if not manifests_dir.is_dir():
        return games

    for item_file in manifests_dir.glob("*.item"):
        try:
            with open(item_file, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            title = data.get("DisplayName")
            install_loc = data.get("InstallLocation")
            if title and install_loc:
                p = Path(install_loc)
                games.append({
                    "name": title,
                    "launcher": "Epic Games",
                    "appid": data.get("AppName", "unknown"),
                    "install_path": str(p),
                    "exists": p.is_dir(),
                    "size_bytes": data.get("InstalledSize", 0),
                    "size_gb": round(data.get("InstalledSize", 0) / (1024**3), 2),
                })
        except Exception:
            pass

    return games

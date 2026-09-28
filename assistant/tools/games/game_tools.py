"""Game discovery and save/config inspection tools (Section 7.2 Phase 7)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.games.steam_finder import discover_steam_games, discover_epic_games, find_steam_root
from assistant.tools.web.pcgamingwiki import pcgw_client


class EmptyInput(BaseModel):
    pass


class GameFindSaveInput(BaseModel):
    game_name: str = Field(description="Name of the PC game (e.g. 'Cyberpunk 2077', 'MGSV', 'Witcher 3')")
    install_path: Optional[str] = Field(default=None, description="Optional game installation folder path")


@tool(
    name="games.list_installed",
    risk=Risk.OBSERVE,
    description="Discover installed PC games from Steam, Epic Games Launcher, and standard game directories.",
    input_model=EmptyInput,
    timeout_s=15,
    requires_elevation=False,
)
def list_installed_games(args: EmptyInput) -> ToolResult:
    games: list[dict[str, Any]] = []

    # 1. Steam games
    steam_games = discover_steam_games()
    games.extend(steam_games)

    # 2. Epic Games
    epic_games = discover_epic_games()
    games.extend(epic_games)

    # 3. Check C:\Games and D:\Games
    for g_dir in [Path(r"C:\Games"), Path(r"D:\Games")]:
        if g_dir.is_dir():
            for sub in g_dir.iterdir():
                if sub.is_dir() and not any(g["name"].lower() == sub.name.lower() for g in games):
                    games.append({
                        "name": sub.name,
                        "launcher": "Direct/Standalone",
                        "appid": "0",
                        "install_path": str(sub),
                        "exists": True,
                        "size_bytes": 0,
                        "size_gb": 0.0,
                    })

    # Sort by name
    games.sort(key=lambda x: x["name"].lower())

    lines = [f"- {g['name']} ({g['launcher']}, {g['size_gb']} GB) -> {g['install_path']}" for g in games[:15]]
    if len(games) > 15:
        lines.append(f"... dan {len(games) - 15} game lainnya")

    summary = (
        f"Ditemukan {len(games)} game terpasang di sistem:\n"
        + ("\n".join(lines) if lines else "- Belum ada game terdeteksi di direktori Steam/Epic/Games.")
    )

    return ToolResult.success(
        data={"count": len(games), "games": games},
        summary=summary,
    )


@tool(
    name="games.find_save_and_config",
    risk=Risk.OBSERVE,
    description="Locate local save game folders, configuration files, and Steam Cloud directories for a game.",
    input_model=GameFindSaveInput,
    timeout_s=25,
    requires_elevation=False,
)
def find_save_and_config(args: GameFindSaveInput) -> ToolResult:
    game_clean = args.game_name.strip()
    name_slug = re_slug(game_clean)

    user_profile = Path(os.environ.get("USERPROFILE", r"C:\Users\Default"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(user_profile / "AppData" / "Local")))
    app_data = Path(os.environ.get("APPDATA", str(user_profile / "AppData" / "Roaming")))

    # 1. Fetch PCGamingWiki candidate paths
    wiki_info = pcgw_client.get_game_info(game_clean)
    candidate_paths: list[str] = list(wiki_info.get("save_paths", [])) + list(wiki_info.get("config_paths", []))

    # 2. Add standard Windows game roots
    standard_roots = [
        user_profile / "Documents" / "My Games",
        user_profile / "Documents",
        user_profile / "Saved Games",
        local_app_data,
        app_data,
    ]

    verified_saves: list[dict[str, Any]] = []
    verified_configs: list[dict[str, Any]] = []

    # Check candidates from PCGW
    for raw_p in candidate_paths:
        expanded = os.path.expandvars(raw_p)
        p = Path(expanded)
        if p.exists():
            entry = {"path": str(p.resolve()), "is_file": p.is_file(), "source": "PCGamingWiki"}
            if p.is_file() and p.suffix.lower() in (".ini", ".cfg", ".json", ".xml", ".txt", ".yaml"):
                verified_configs.append(entry)
            else:
                verified_saves.append(entry)

    # Scan standard roots for matching subfolders
    for root in standard_roots:
        if not root.is_dir():
            continue
        try:
            for item in root.iterdir():
                if name_slug in re_slug(item.name):
                    entry = {"path": str(item.resolve()), "is_file": item.is_file(), "source": "Heuristic Scan"}
                    if not any(v["path"] == entry["path"] for v in verified_saves + verified_configs):
                        verified_saves.append(entry)
        except Exception:
            pass

    # 3. Check Steam userdata for this game (if Steam installed)
    steam_root = find_steam_root()
    steam_cloud_paths = []
    if steam_root:
        userdata = steam_root / "userdata"
        if userdata.is_dir():
            # If we have an appid from installed games
            for user_folder in userdata.iterdir():
                if user_folder.is_dir():
                    # Look for remotecache.vdf or save subfolders
                    steam_cloud_paths.append(str(user_folder))

    summary_lines = [f"Pencarian Save Game & Konfigurasi untuk '{game_clean}':"]
    if verified_saves:
        summary_lines.append("\n[Folder / File Save Game]:")
        for s in verified_saves:
            summary_lines.append(f"- {s['path']} ({s['source']})")
    else:
        summary_lines.append("\n[Folder Save Game]: Tidak ditemukan folder lokal yang cocok secara langsung.")

    if verified_configs:
        summary_lines.append("\n[File Konfigurasi]:")
        for c in verified_configs:
            summary_lines.append(f"- {c['path']} ({c['source']})")

    summary_lines.append(f"\nReferensi PCGamingWiki: {wiki_info.get('page_url')}")

    data = {
        "game_name": game_clean,
        "pcgamingwiki_url": wiki_info.get("page_url"),
        "verified_save_paths": verified_saves,
        "verified_config_paths": verified_configs,
        "candidate_paths": candidate_paths,
    }

    return ToolResult.success(data=data, summary="\n".join(summary_lines))


def re_slug(text: str) -> str:
    """Normalize game name for directory fuzzy matching."""
    return "".join(c.lower() for c in text if c.isalnum())

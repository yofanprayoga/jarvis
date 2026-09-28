"""PCGamingWiki tool for game save/config paths and known fixes (Section 7.2 & 12)."""

from __future__ import annotations

import re
from typing import Any, Optional
import httpx

from assistant.tools.web.cache import web_cache, WebCache
from assistant.tools.web.fetcher import web_fetcher, clean_html_to_text


class PCGamingWikiClient:
    """Queries PCGamingWiki for game save locations, config paths, and known fixes."""

    API_URL = "https://www.pcgamingwiki.com/w/api.php"

    def __init__(self, cache: WebCache | None = None, timeout_s: float = 12.0) -> None:
        self.cache = cache or web_cache
        self.timeout_s = timeout_s

    def search_game(self, game_name: str) -> Optional[str]:
        """Search PCGamingWiki for exact page title."""
        cache_key = f"pcgw_search_{game_name.lower().strip()}"
        cached = self.cache.get(cache_key)
        if cached and isinstance(cached, str):
            return cached

        params = {
            "action": "opensearch",
            "search": game_name,
            "limit": 3,
            "format": "json",
        }
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.get(self.API_URL, params=params)
            if resp.status_code == 200:
                data = resp.json()
                # Opensearch format: [query, [titles], [descriptions], [urls]]
                if len(data) >= 2 and data[1]:
                    page_title = data[1][0]
                    self.cache.set(cache_key, page_title, ttl_seconds=86400 * 7)
                    return page_title
        except Exception:
            pass

        return None

    def get_game_info(self, game_name: str) -> dict[str, Any]:
        """Fetch save/config locations and known issues for a game."""
        cache_key = f"pcgw_info_{game_name.lower().strip()}"
        cached = self.cache.get(cache_key)
        if cached and isinstance(cached, dict):
            return cached

        page_title = self.search_game(game_name)
        if not page_title:
            # Fallback title with spaces replaced by underscores
            page_title = game_name.strip()

        params = {
            "action": "parse",
            "page": page_title,
            "prop": "wikitext|text",
            "section": 0,  # Or parse sections
            "format": "json",
        }

        # Try API parse
        result: dict[str, Any] = {
            "game_name": game_name,
            "page_title": page_title,
            "page_url": f"https://www.pcgamingwiki.com/wiki/{page_title.replace(' ', '_')}",
            "save_paths": [],
            "config_paths": [],
            "issues_and_fixes": [],
            "summary": "",
            "untrusted": True,
        }

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.get(self.API_URL, params={"action": "parse", "page": page_title, "prop": "wikitext", "format": "json"})

            if resp.status_code == 200:
                data = resp.json()
                wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")

                # Helper to convert wikitext path template into clean path
                def clean_wiki_path(raw: str) -> str:
                    s = raw.strip()
                    s = re.sub(r"\}\}+\s*$", "", s).strip()
                    s = re.sub(r"\{\{p\|([^}]+)\}\}", r"%\1%", s)
                    s = re.sub(r"\{\{[^}]*\}\}", "", s)
                    return s.strip()

                # Parse Save game data locations
                save_matches = re.findall(r"\{\{Game data/saves\|Windows\|([^\r\n]+)", wikitext)
                for sm in save_matches:
                    clean_path = clean_wiki_path(sm)
                    if clean_path and clean_path not in result["save_paths"]:
                        result["save_paths"].append(clean_path)

                # Parse Config data locations
                config_matches = re.findall(r"\{\{Game data/config\|Windows\|([^\r\n]+)", wikitext)
                for cm in config_matches:
                    clean_path = clean_wiki_path(cm)
                    if clean_path and clean_path not in result["config_paths"]:
                        result["config_paths"].append(clean_path)

                # Parse Known Issues
                issue_sections = re.findall(r"===\s*([^=]+?)\s*===\s*\n(.*?)(?=\n===|\Z)", wikitext, flags=re.DOTALL)
                for issue_title, issue_body in issue_sections[:5]:
                    clean_issue = clean_html_to_text(issue_body)
                    result["issues_and_fixes"].append({
                        "issue": issue_title.strip(),
                        "fix": clean_issue[:300].strip(),
                    })

                self.cache.set(cache_key, result, ttl_seconds=86400 * 3)
                return result

        except Exception:
            pass

        # Fallback: Fetch page HTML directly via WebFetcher
        fetch_res = web_fetcher.fetch(result["page_url"])
        if fetch_res.get("ok"):
            text = fetch_res.get("text", "")
            # Heuristic regex on text
            saves = re.findall(r"(?:Save game data|Saves).*?([A-Za-z]:\\[^\n]+|%[A-Z]+%\\[^\n]+)", text, re.IGNORECASE)
            result["save_paths"] = list(set(saves))[:3]
            result["summary"] = text[:1500]
            self.cache.set(cache_key, result, ttl_seconds=86400 * 3)

        return result


# Global default PCGamingWiki client
pcgw_client = PCGamingWikiClient()

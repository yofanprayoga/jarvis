"""Site manager for resolving and dynamically learning website aliases."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import yaml


class SiteManager:
    """Manages static seed sites from YAML and dynamic learned aliases from SQLite."""

    def __init__(self, seed_file: str = "config/sites.yaml", db_path: str = "data/audit.db") -> None:
        self.seed_file = Path(seed_file)
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_aliases (
                    alias TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def get_seed_sites(self) -> dict[str, str]:
        if not self.seed_file.is_file():
            return {}
        try:
            with open(self.seed_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return {str(k).lower().strip(): str(v).strip() for k, v in data.items()}
        except Exception:
            return {}

    def get_dynamic_sites(self) -> dict[str, str]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute("SELECT alias, url FROM site_aliases")
            rows = cur.fetchall()
            return {r["alias"].lower(): r["url"] for r in rows}
        finally:
            conn.close()

    def list_all_sites(self) -> dict[str, str]:
        """Returns all sites, dynamic overrides seed."""
        sites = self.get_seed_sites()
        sites.update(self.get_dynamic_sites())
        return sites

    def resolve(self, query: str) -> Optional[str]:
        """Resolve a query to a valid URL."""
        q = query.lower().strip()
        all_sites = self.list_all_sites()
        if q in all_sites:
            return all_sites[q]

        # Check if query is already a full URL
        if q.startswith("http://") or q.startswith("https://"):
            return query.strip()

        # Check if query ends with common TLD (.com, .net, .org, .id)
        if "." in q and not " " in q:
            return f"https://{q}"

        return None

    def save_alias(self, alias: str, url: str) -> None:
        """Persist or update an alias in SQLite."""
        clean_alias = alias.lower().strip()
        clean_url = url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            clean_url = f"https://{clean_url}"

        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            conn.execute(
                """
                INSERT INTO site_aliases (alias, url, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    url = excluded.url,
                    updated_at = excluded.updated_at
                """,
                (clean_alias, clean_url, now),
            )
            conn.commit()
        finally:
            conn.close()


site_manager = SiteManager()

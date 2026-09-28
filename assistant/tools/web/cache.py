"""Local disk cache with TTL for web search and fetch operations (Section 12)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional


class WebCache:
    """Manages disk-based cache for web pages and search queries."""

    def __init__(self, cache_dir: str | Path = "data/cache/web") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _hash_key(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]

    def get(self, key: str) -> Optional[dict[str, Any]]:
        """Retrieve cached entry if exists and not expired."""
        h = self._hash_key(key)
        cache_file = self.cache_dir / f"{h}.json"
        if not cache_file.is_file():
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                entry = json.load(f)

            expires_at = entry.get("expires_at", 0)
            if time.time() > expires_at:
                try:
                    cache_file.unlink()
                except OSError:
                    pass
                return None

            return entry.get("payload")
        except Exception:
            return None

    def set(self, key: str, payload: Any, ttl_seconds: int = 86400) -> None:
        """Store payload in cache with TTL."""
        h = self._hash_key(key)
        cache_file = self.cache_dir / f"{h}.json"
        entry = {
            "key": key,
            "cached_at": time.time(),
            "expires_at": time.time() + ttl_seconds,
            "payload": payload,
        }
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def clear(self) -> int:
        """Clear all cached entries."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
        return count


# Global default web cache
web_cache = WebCache()

"""HTML page fetcher with HTML stripping, size limits, and security tags (Section 12)."""

from __future__ import annotations

import re
import time
from typing import Any, Optional
import httpx

from assistant.tools.web.cache import web_cache, WebCache


def clean_html_to_text(html: str) -> str:
    """Extract clean text content from HTML by stripping scripts, styles, and tags."""
    # 1. Remove script, style, svg, noscript, header, footer, nav tags
    cleaned = re.sub(r"<(script|style|svg|noscript|header|footer|nav)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)

    # 2. Replace block elements with newlines
    cleaned = re.sub(r"<(div|p|h[1-6]|li|tr|br|hr)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)

    # 3. Strip inline tags (b, i, em, strong, u, span, a) without adding extra spaces
    cleaned = re.sub(r"</?(b|strong|i|em|u|s|span|a|font|small|sub|sup)[^>]*>", "", cleaned, flags=re.IGNORECASE)

    # 4. Strip any remaining tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)

    # 5. Decode HTML entities
    import html as html_lib
    cleaned = html_lib.unescape(cleaned)

    # 6. Collapse consecutive whitespaces and clean lines
    lines = []
    for line in cleaned.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


class WebFetcher:
    """Fetches web page content, cleans HTML to plain text, and respects cache."""

    def __init__(
        self,
        cache: WebCache | None = None,
        timeout_s: float = 12.0,
        max_chars: int = 5000,
    ) -> None:
        self.cache = cache or web_cache
        self.timeout_s = timeout_s
        self.max_chars = max_chars
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        }

    def fetch(self, url: str, max_chars: int | None = None) -> dict[str, Any]:
        """Fetch URL content, return cleaned text and metadata."""
        limit = max_chars or self.max_chars

        # 1. Check cache first
        cached = self.cache.get(url)
        if cached and isinstance(cached, dict):
            cached["cached"] = True
            return cached

        # 2. Perform HTTP request
        t_start = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=True, headers=self.headers) as client:
                resp = client.get(url)

            fetch_time = round(time.perf_counter() - t_start, 2)
            if resp.status_code >= 400:
                return {
                    "url": url,
                    "ok": False,
                    "error": f"HTTP {resp.status_code}",
                    "text": "",
                    "untrusted": True,
                    "fetch_time_s": fetch_time,
                }

            html_content = resp.text

            # Extract title
            title_m = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
            title = title_m.group(1).strip() if title_m else ""
            import html as html_lib
            title = html_lib.unescape(title)

            clean_text = clean_html_to_text(html_content)
            if len(clean_text) > limit:
                clean_text = clean_text[:limit] + "\n... [teks terpotong melebihi batas]"

            payload = {
                "url": url,
                "ok": True,
                "title": title,
                "text": clean_text,
                "length": len(clean_text),
                "untrusted": True,
                "fetch_time_s": fetch_time,
            }

            # Cache successful response
            self.cache.set(url, payload, ttl_seconds=86400)
            return payload

        except Exception as e:
            return {
                "url": url,
                "ok": False,
                "error": str(e),
                "text": "",
                "untrusted": True,
                "fetch_time_s": round(time.perf_counter() - t_start, 2),
            }


# Global default web fetcher instance
web_fetcher = WebFetcher()

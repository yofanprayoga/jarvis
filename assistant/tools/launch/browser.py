"""Web and URL launching tools (Section 7.2 Phase 2)."""

from __future__ import annotations

import os
import urllib.parse
import webbrowser
from pydantic import BaseModel, Field
from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.launch.site_manager import site_manager


class OpenUrlInput(BaseModel):
    url: str = Field(description="URL to open in the user's default browser (http or https)")


class WebSearchInput(BaseModel):
    query: str = Field(description="Search terms to query on Google")


class YoutubeSearchInput(BaseModel):
    query: str = Field(description="Search terms or song title to query on YouTube")


class UpdateSiteInput(BaseModel):
    alias: str = Field(description="Alias name (e.g. 'kuramanime' or 'komik')")
    url: str = Field(description="Target destination URL")


@tool(
    name="launch.open_url",
    risk=Risk.LOW_ACTION,
    description="Open a web URL in the user's default browser (http/https only).",
    input_model=OpenUrlInput,
    timeout_s=10,
    requires_elevation=False,
)
def open_url(args: OpenUrlInput) -> ToolResult:
    target_url = args.url.strip()

    # Check if target is an alias
    resolved = site_manager.resolve(target_url)
    if resolved:
        target_url = resolved

    # Safety check on scheme
    parsed = urllib.parse.urlparse(target_url)
    if parsed.scheme.lower() not in ("http", "https"):
        return ToolResult.fail(f"URL scheme '{parsed.scheme}' is not allowed. Only HTTP and HTTPS are permitted.")

    try:
        # Use os.startfile for native Windows URL handler if available, fallback to webbrowser
        if hasattr(os, "startfile"):
            os.startfile(target_url)
        else:
            webbrowser.open(target_url)
        return ToolResult.success(data={"url": target_url}, summary=f"Membuka web: {target_url}")
    except Exception as e:
        return ToolResult.fail(f"Failed to open URL '{target_url}': {e}")


@tool(
    name="launch.web_search",
    risk=Risk.LOW_ACTION,
    description="Search Google in the user's default browser.",
    input_model=WebSearchInput,
    timeout_s=10,
    requires_elevation=False,
)
def web_search(args: WebSearchInput) -> ToolResult:
    query = args.query.strip()
    encoded = urllib.parse.quote_plus(query)
    search_url = f"https://www.google.com/search?q={encoded}"

    try:
        if hasattr(os, "startfile"):
            os.startfile(search_url)
        else:
            webbrowser.open(search_url)
        return ToolResult.success(data={"query": query, "url": search_url}, summary=f"Mencari di Google: '{query}'")
    except Exception as e:
        return ToolResult.fail(f"Failed to perform search: {e}")


@tool(
    name="launch.youtube_search",
    risk=Risk.LOW_ACTION,
    description="Search YouTube in the user's default browser.",
    input_model=YoutubeSearchInput,
    timeout_s=10,
    requires_elevation=False,
)
def youtube_search(args: YoutubeSearchInput) -> ToolResult:
    query = args.query.strip()
    encoded = urllib.parse.quote_plus(query)
    yt_url = f"https://www.youtube.com/results?search_query={encoded}"

    try:
        if hasattr(os, "startfile"):
            os.startfile(yt_url)
        else:
            webbrowser.open(yt_url)
        return ToolResult.success(data={"query": query, "url": yt_url}, summary=f"Mencari di YouTube: '{query}'")
    except Exception as e:
        return ToolResult.fail(f"Failed to perform YouTube search: {e}")


@tool(
    name="launch.update_site",
    risk=Risk.LOW_ACTION,
    description="Dynamically update or learn a website alias and save it to local persistent memory.",
    input_model=UpdateSiteInput,
    timeout_s=10,
    requires_elevation=False,
)
def update_site_alias(args: UpdateSiteInput) -> ToolResult:
    alias = args.alias.strip()
    url = args.url.strip()
    site_manager.save_alias(alias, url)
    resolved = site_manager.resolve(alias)
    return ToolResult.success(
        data={"alias": alias, "url": resolved},
        summary=f"Berhasil memperbarui alias '{alias}' ke '{resolved}'."
    )

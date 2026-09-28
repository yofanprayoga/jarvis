"""Web research tools package (Section 7.2 & 12)."""

from assistant.tools.web.cache import WebCache, web_cache
from assistant.tools.web.search_provider import (
    SearchProvider,
    SearchResult,
    DuckDuckGoSearchProvider,
    MockSearchProvider,
    get_search_provider,
)
from assistant.tools.web.fetcher import WebFetcher, web_fetcher, clean_html_to_text
from assistant.tools.web.pcgamingwiki import PCGamingWikiClient, pcgw_client
from assistant.tools.web.web_tools import web_search_tool, web_fetch_tool, pcgw_tool
from assistant.tools.web.researcher import WebResearcher, web_researcher

__all__ = [
    "WebCache",
    "web_cache",
    "SearchProvider",
    "SearchResult",
    "DuckDuckGoSearchProvider",
    "MockSearchProvider",
    "get_search_provider",
    "WebFetcher",
    "web_fetcher",
    "clean_html_to_text",
    "PCGamingWikiClient",
    "pcgw_client",
    "web_search_tool",
    "web_fetch_tool",
    "pcgw_tool",
    "WebResearcher",
    "web_researcher",
]

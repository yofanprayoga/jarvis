"""Search provider abstractions and implementations (Section 12)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel


class SearchResult(BaseModel):
    """Normalized search result item."""
    title: str
    url: str
    snippet: str
    source_rank: int = 0


class SearchProvider(ABC):
    """Abstract interface for web search engines."""

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Perform web search and return structured results."""
        pass


class DuckDuckGoSearchProvider(SearchProvider):
    """DuckDuckGo search provider using duckduckgo_search library."""

    def __init__(self, timeout_s: int = 10) -> None:
        self.timeout_s = timeout_s

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            with DDGS(timeout=self.timeout_s) as ddgs:
                raw_results = list(ddgs.text(query, max_results=max_results))

            for i, r in enumerate(raw_results, 1):
                results.append(
                    SearchResult(
                        title=str(r.get("title", "")).strip(),
                        url=str(r.get("href", "")).strip(),
                        snippet=str(r.get("body", "")).strip(),
                        source_rank=i,
                    )
                )
        except Exception as e:
            # Degrade gracefully without crashing
            pass

        return results


class MockSearchProvider(SearchProvider):
    """Mock search provider for testing and deterministic offline evaluation."""

    def __init__(self, predefined_results: Optional[dict[str, list[SearchResult]]] = None) -> None:
        self.predefined = predefined_results or {}

    def add_result(self, query_substr: str, results: list[SearchResult]) -> None:
        self.predefined[query_substr.lower()] = results

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        q = query.lower()
        for key, res in self.predefined.items():
            if key in q:
                return res[:max_results]

        # Default fallback results for testing
        return [
            SearchResult(
                title=f"Fixing {query} - Microsoft Support",
                url=f"https://support.microsoft.com/en-us/help/{abs(hash(query))%100000}",
                snippet=f"Information on diagnosing and resolving {query} in Windows.",
                source_rank=1,
            ),
            SearchResult(
                title=f"{query} Troubleshooting Guide",
                url=f"https://learn.microsoft.com/windows-hardware/drivers/debugger/{abs(hash(query))%10000}",
                snippet=f"Detailed documentation on causes and driver updates related to {query}.",
                source_rank=2,
            ),
        ][:max_results]


def get_search_provider(use_mock: bool = False) -> SearchProvider:
    """Factory to get the active search provider."""
    if use_mock:
        return MockSearchProvider()
    return DuckDuckGoSearchProvider()

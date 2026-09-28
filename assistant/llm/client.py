"""Abstract LLM Client Interface (Section 5 & 10)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMClient(ABC):
    """Abstract interface for local (and optional cloud) LLM providers."""

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if LLM server is up and responsive."""
        pass

    @abstractmethod
    def warm_up(self) -> bool:
        """Send a lightweight ping to preload the model into memory."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Generate text completion from LLM."""
        pass

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        system: str,
        schema: Optional[dict[str, Any]] = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Generate guaranteed JSON output constrained by optional JSON schema."""
        pass

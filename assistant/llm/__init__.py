"""LLM module initialization and client factory."""

from assistant.core.config import load_settings
from assistant.llm.client import LLMClient
from assistant.llm.providers.mock import MockLLMClient
from assistant.llm.providers.ollama import OllamaClient
from assistant.llm.providers.openai_compat import OpenAICompatClient


def get_llm_client() -> LLMClient:
    """Instantiate configured LLM provider from settings.yaml."""
    cfg = load_settings()
    provider = cfg.llm.provider.lower()

    if provider == "ollama":
        client = OllamaClient(
            model=cfg.llm.model,
            base_url=cfg.llm.base_url,
            keep_alive=cfg.llm.keep_alive,
            timeout_s=cfg.llm.timeout_s,
        )
        # If Ollama server is offline on dev machine, fallback to MockLLMClient for smooth dev experience
        if not client.is_healthy():
            return MockLLMClient()
        return client

    elif provider in ("openai", "openai_compat"):
        return OpenAICompatClient(
            base_url=cfg.llm.base_url,
            model=cfg.llm.model,
            timeout_s=cfg.llm.timeout_s,
        )

    elif provider == "mock":
        return MockLLMClient()

    return MockLLMClient()


# Import planner and explainer after get_llm_client definition to avoid circular import
# with modules in assistant.tools.web that import get_llm_client.
from assistant.llm.planner import LLMPlanner, PlannerDecision
from assistant.llm.explainer import LLMExplainer



__all__ = [
    "LLMClient",
    "OllamaClient",
    "OpenAICompatClient",
    "MockLLMClient",
    "LLMPlanner",
    "PlannerDecision",
    "LLMExplainer",
    "get_llm_client",
]

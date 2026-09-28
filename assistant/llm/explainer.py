"""LLM Explainer implementation (Section 10.3 & Appendix B)."""

from __future__ import annotations

from assistant.llm.client import LLMClient
from assistant.llm.prompts.explainer import build_explainer_prompt


class LLMExplainer:
    """Takes structured tool results and produces non-expert explanations in Indonesian."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def explain(self, user_query: str, findings: str) -> str:
        """Generate structured explanation grounded in facts."""
        system_prompt, user_prompt = build_explainer_prompt(
            user_query=user_query,
            findings=findings,
        )

        try:
            return self.llm.generate(
                prompt=user_prompt,
                system=system_prompt,
                temperature=0.2,
                max_tokens=1024,
            )
        except Exception as e:
            # Graceful degradation fallback
            return (
                f"Hasil diagnosa sistem:\n{findings}\n\n"
                f"(Catatan: Penjelasan otomatis LLM gagal dibuat: {e})"
            )

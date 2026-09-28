"""OpenAI-compatible LLM Provider implementation (Section 5 & 10.5)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional
import httpx
from assistant.llm.client import LLMClient


class OpenAICompatClient(LLMClient):
    """Client for any OpenAI-compatible API (e.g. llama-server, vLLM, or optional cloud)."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080/v1",
        api_key: str = "none",
        model: str = "default",
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def is_healthy(self) -> bool:
        """Check if server is reachable."""
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/models", headers=self._headers())
                return res.status_code == 200
        except Exception:
            return False

    def warm_up(self) -> bool:
        return self.is_healthy()

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                res = client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers())
                res.raise_for_status()
                data = res.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible completion failed: {e}") from e

    def generate_json(
        self,
        prompt: str,
        system: str,
        schema: Optional[dict[str, Any]] = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                res = client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers())
                res.raise_for_status()
                raw_text = res.json()["choices"][0]["message"]["content"].strip()

                cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
                cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
                return json.loads(cleaned)
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible JSON generation failed: {e}") from e

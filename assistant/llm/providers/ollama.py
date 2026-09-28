"""Ollama LLM Provider implementation (Section 5 & 10)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional
import httpx
from assistant.llm.client import LLMClient


class OllamaClient(LLMClient):
    """Client for local Ollama server with keep_alive and structured JSON output."""

    def __init__(
        self,
        model: str = "qwen2.5:3b-instruct",
        base_url: str = "http://localhost:11434",
        keep_alive: str = "5m",
        timeout_s: float = 60.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.keep_alive = keep_alive
        self.timeout_s = timeout_s

    def is_healthy(self) -> bool:
        """Check if Ollama server is running with fast connect timeout."""
        try:
            with httpx.Client(timeout=httpx.Timeout(1.0, connect=0.8)) as client:
                res = client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    def list_local_models(self) -> list[str]:
        """List all models already downloaded in Ollama."""
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = data.get("models", [])
                    return [m.get("name", "") for m in models]
        except Exception:
            pass
        return []

    def warm_up(self) -> bool:
        """Preload model in background without generating lengthy text."""
        try:
            with httpx.Client(timeout=10.0) as client:
                payload = {
                    "model": self.model,
                    "prompt": "hi",
                    "keep_alive": self.keep_alive,
                    "options": {"num_predict": 1},
                    "stream": False,
                }
                res = client.post(f"{self.base_url}/api/generate", json=payload)
                return res.status_code == 200
        except Exception:
            return False

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Generate text output from Ollama."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "keep_alive": self.keep_alive,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout_s, connect=2.0)) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
                return data.get("response", "").strip()
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {e}") from e

    def generate_json(
        self,
        prompt: str,
        system: str,
        schema: Optional[dict[str, Any]] = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Generate guaranteed JSON output constrained by JSON Schema or format='json'."""
        url = f"{self.base_url}/api/generate"
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "keep_alive": self.keep_alive,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        # Ollama supports passing JSON schema in `format`
        if schema:
            payload["format"] = schema
        else:
            payload["format"] = "json"

        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout_s, connect=2.0)) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                raw_text = res.json().get("response", "").strip()

                # Clean potential markdown fences
                cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
                cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

                return json.loads(cleaned)
        except json.JSONDecodeError as jde:
            raise ValueError(f"Model returned invalid JSON: {jde}. Raw: {raw_text[:200]}") from jde
        except Exception as e:
            raise RuntimeError(f"Ollama JSON generation failed: {e}") from e

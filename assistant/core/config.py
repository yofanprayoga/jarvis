"""Configuration loader and schema models."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field


class AssistantSettings(BaseModel):
    name: str = "Jarvis"
    language: str = "id"
    version: str = "0.1.0"


class PathsSettings(BaseModel):
    data_dir: str = "data"
    audit_db: str = "data/audit.db"
    reports_dir: str = "data/reports"
    backups_dir: str = "data/backups"
    cache_dir: str = "data/cache"


class TimeoutsSettings(BaseModel):
    default_tool_timeout_s: int = 30
    sampling_timeout_s: int = 15


class LLMSettings(BaseModel):
    provider: str = "ollama"
    model: str = "qwen2.5:3b-instruct"
    base_url: str = "http://localhost:11434"
    keep_alive: str = "5m"
    temperature: float = 0.1
    timeout_s: int = 60
    max_planning_steps: int = 6


class AppConfig(BaseModel):
    assistant: AssistantSettings = Field(default_factory=AssistantSettings)
    paths: PathsSettings = Field(default_factory=PathsSettings)
    timeouts: TimeoutsSettings = Field(default_factory=TimeoutsSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)


class PolicyConfig(BaseModel):
    protected_processes: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    allowed_read_roots: list[str] = Field(default_factory=list)
    allowed_url_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])


def load_settings(config_path: Path | str = "config/settings.yaml") -> AppConfig:
    p = Path(config_path)
    if not p.is_file():
        return AppConfig()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return AppConfig(**data)
    except Exception:
        return AppConfig()


def load_policy(policy_path: Path | str = "config/policy.yaml") -> PolicyConfig:
    p = Path(policy_path)
    if not p.is_file():
        return PolicyConfig()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return PolicyConfig(**data)
    except Exception:
        return PolicyConfig()

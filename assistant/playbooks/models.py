"""Data models for diagnostic playbooks (Section 11)."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class PlaybookStep(BaseModel):
    """Single step in a diagnostic playbook."""
    id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    when: Optional[str] = None
    elevated: bool = False
    optional: bool = False


class PlaybookRule(BaseModel):
    """Heuristic rule mapping step data conditions to findings."""
    condition: str = Field(alias="if")
    finding: str

    class Config:
        populate_by_name = True


class PlaybookDefinition(BaseModel):
    """Complete YAML playbook definition."""
    name: str
    description: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[PlaybookStep] = Field(default_factory=list)
    rules: list[PlaybookRule] = Field(default_factory=list)
    optional_web_research: Optional[dict[str, Any]] = None
    explain: bool = True

    class Config:
        populate_by_name = True


class PlaybookStepResult(BaseModel):
    """Execution result of a single playbook step."""
    step_id: str
    tool_name: str
    ok: bool
    skipped: bool = False
    skip_reason: Optional[str] = None
    data: Any = None
    summary: str = ""
    error: Optional[str] = None


class PlaybookResult(BaseModel):
    """Aggregate execution result of a playbook."""
    playbook_name: str
    ok: bool
    steps: dict[str, PlaybookStepResult] = Field(default_factory=dict)
    rule_findings: list[str] = Field(default_factory=list)
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)

"""Base classes, risk definitions, and tool decorator."""

from __future__ import annotations

import functools
import inspect
from enum import IntEnum
from typing import Any, Callable, Type
from pydantic import BaseModel, Field


class Risk(IntEnum):
    """Fixed risk levels for tools (Section 8.1)."""
    FORBIDDEN = 0    # L0: Never executed
    OBSERVE = 1      # L1: Read-only observation, no confirmation needed
    LOW_ACTION = 2   # L2: Safe low-impact actions, logged, no confirmation needed
    CONFIRM = 3      # L3: Explicit click/typed confirmation required per action


class ToolResult(BaseModel):
    """Standardized tool execution result contract (Section 7.1)."""
    ok: bool = True
    data: Any = Field(default_factory=dict, description="Full structured data for audit/reports")
    summary: str = Field(default="", description="Short text (<= 1500 chars) sent to the LLM")
    truncated: bool = False
    error: str | None = None
    untrusted: bool = False

    @classmethod
    def success(cls, data: Any, summary: str, untrusted: bool = False, max_summary_len: int = 1500) -> ToolResult:
        is_truncated = False
        clean_summary = summary
        if len(clean_summary) > max_summary_len:
            clean_summary = clean_summary[:max_summary_len] + "... [TRUNCATED]"
            is_truncated = True
        return cls(
            ok=True,
            data=data,
            summary=clean_summary,
            truncated=is_truncated,
            error=None,
            untrusted=untrusted,
        )

    @classmethod
    def fail(cls, error: str, data: Any = None, untrusted: bool = False) -> ToolResult:
        return cls(
            ok=False,
            data=data or {},
            summary=f"Error: {error}",
            truncated=False,
            error=error,
            untrusted=untrusted,
        )


class ToolDefinition:
    """Encapsulates tool metadata and execution logic."""
    def __init__(
        self,
        name: str,
        risk: Risk,
        description: str,
        input_model: Type[BaseModel],
        func: Callable[..., ToolResult],
        timeout_s: int = 20,
        requires_elevation: bool = False,
    ):
        self.name = name
        self.risk = risk
        self.description = description
        self.input_model = input_model
        self.func = func
        self.timeout_s = timeout_s
        self.requires_elevation = requires_elevation

    def get_json_schema(self) -> dict[str, Any]:
        """Returns JSON schema for LLM planner consumption."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
            "risk": self.risk.name,
            "requires_elevation": self.requires_elevation,
        }

    def run(self, **kwargs: Any) -> ToolResult:
        """Validate input arguments against schema and execute tool."""
        try:
            validated_args = self.input_model(**kwargs)
        except Exception as e:
            return ToolResult.fail(f"Invalid arguments for {self.name}: {e}")

        try:
            return self.func(validated_args)
        except Exception as e:
            return ToolResult.fail(f"Execution error in {self.name}: {e}")


def tool(
    name: str,
    risk: Risk,
    description: str,
    input_model: Type[BaseModel],
    timeout_s: int = 20,
    requires_elevation: bool = False,
) -> Callable[[Callable[..., ToolResult]], ToolDefinition]:
    """Decorator to declare a validated tool with fixed risk level."""
    def decorator(fn: Callable[..., ToolResult]) -> ToolDefinition:
        tool_def = ToolDefinition(
            name=name,
            risk=risk,
            description=description,
            input_model=input_model,
            func=fn,
            timeout_s=timeout_s,
            requires_elevation=requires_elevation,
        )
        functools.update_wrapper(tool_def, fn)
        return tool_def

    return decorator

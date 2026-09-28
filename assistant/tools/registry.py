"""Central Tool Registry."""

from __future__ import annotations

from typing import Any
from assistant.tools.base import ToolDefinition, ToolResult


class ToolRegistry:
    """Registry maintaining all available tools and their schemas."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> ToolDefinition:
        """Register a tool definition."""
        if tool_def.name in self._tools:
            raise ValueError(f"Tool '{tool_def.name}' is already registered.")
        self._tools[tool_def.name] = tool_def
        return tool_def

    def get(self, name: str) -> ToolDefinition | None:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """List all tool names."""
        return sorted(list(self._tools.keys()))

    def get_schemas(self, prefix: str | None = None) -> list[dict[str, Any]]:
        """Return JSON schemas for tools, optionally filtered by name prefix."""
        schemas = []
        for name, tool_def in self._tools.items():
            if prefix is None or name.startswith(prefix):
                schemas.append(tool_def.get_json_schema())
        return schemas

    def execute(self, tool_name: str, /, **kwargs: Any) -> ToolResult:
        """Execute a tool by name with provided keyword arguments."""
        tool_def = self.get(tool_name)
        if not tool_def:
            return ToolResult.fail(f"Tool '{tool_name}' not found in registry.")
        return tool_def.run(**kwargs)


# Global default registry instance
registry = ToolRegistry()

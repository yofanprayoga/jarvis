"""Core Orchestrator (Phase 1 Foundation)."""

from __future__ import annotations

import time
from typing import Any
from assistant.core.audit import audit_logger, AuditLogger
from assistant.core.policy import policy_engine, PolicyEngine
from assistant.tools.base import Risk, ToolResult
from assistant.tools.registry import registry, ToolRegistry


class Orchestrator:
    """Coordinates policy evaluation, tool dispatch, and audit logging."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        policy: PolicyEngine | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self.registry = tool_registry or registry
        self.policy = policy or policy_engine
        self.audit = audit or audit_logger

    def run_tool(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        """Execute a tool through the security policy and record to audit log."""
        args = args or {}
        tool_def = self.registry.get(name)
        if not tool_def:
            error_msg = f"Tool '{name}' not found."
            self.audit.log_tool_call(
                tool_name=name,
                args=args,
                risk_level="UNKNOWN",
                decision="REJECTED_NOT_FOUND",
                duration_ms=0.0,
                ok=False,
                error=error_msg,
                summary=error_msg,
            )
            return ToolResult.fail(error_msg)

        # Policy evaluation
        decision = self.policy.evaluate(tool_def, args)
        if not decision.allowed:
            self.audit.log_tool_call(
                tool_name=name,
                args=args,
                risk_level=decision.risk.name,
                decision=f"BLOCKED: {decision.reason}",
                duration_ms=0.0,
                ok=False,
                error=decision.reason,
                summary=f"Blocked by policy: {decision.reason}",
            )
            return ToolResult.fail(f"Policy violation: {decision.reason}")

        # Note: L3 confirmation check will be hooked into UI in Phase 5 / Phase 8
        if decision.needs_confirmation:
            # In Phase 1, all tools are read-only L1 (OBSERVE).
            pass

        start_time = time.perf_counter()
        result = tool_def.run(**args)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Record to audit log
        self.audit.log_tool_call(
            tool_name=name,
            args=args,
            risk_level=tool_def.risk.name,
            decision="ALLOWED",
            duration_ms=duration_ms,
            ok=result.ok,
            error=result.error,
            summary=result.summary,
        )

        return result


# Global orchestrator instance
orchestrator = Orchestrator()

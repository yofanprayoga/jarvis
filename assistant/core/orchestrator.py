"""Core Orchestrator (Phase 1, 2 & 3)."""

from __future__ import annotations

import time
from typing import Any, Optional
from assistant.core.audit import audit_logger, AuditLogger
from assistant.core.policy import policy_engine, PolicyEngine
from assistant.tools.base import Risk, ToolResult
from assistant.tools.registry import registry, ToolRegistry
from assistant.llm import get_llm_client, LLMPlanner, LLMExplainer, LLMClient


class Orchestrator:
    """Coordinates policy evaluation, tool dispatch, fast-path, and LLM planning/explaining."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        policy: PolicyEngine | None = None,
        audit: AuditLogger | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.registry = tool_registry or registry
        self.policy = policy or policy_engine
        self.audit = audit or audit_logger
        self._llm = llm or get_llm_client()
        self.planner = LLMPlanner(self._llm, self.registry)
        self.explainer = LLMExplainer(self._llm)

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

    def handle_request(self, user_query: str) -> dict[str, Any]:
        """Full end-to-end request handling (Fast-Path -> LLM Planner -> Tool/Playbook -> LLM Explainer)."""
        from assistant.core.router import intent_router

        # 1. Try Fast Path first (< 1 second, zero LLM overhead)
        route_res = intent_router.route(user_query)
        if route_res.matched:
            return {
                "route": "fast",
                "intent": route_res.intent,
                "tool": route_res.tool_name,
                "response": route_res.message,
                "ok": route_res.tool_result.ok if route_res.tool_result else True,
            }

        # 2. Analysis Path via LLM Planner
        decision = self.planner.plan(user_query)

        if decision.decision_type == "tool_call":
            tool_res = self.run_tool(decision.tool, decision.args)
            if tool_res.ok:
                explanation = self.explainer.explain(user_query, tool_res.summary)
                return {
                    "route": "llm",
                    "type": "tool_call",
                    "tool": decision.tool,
                    "response": explanation,
                    "findings": tool_res.summary,
                    "ok": True,
                }
            else:
                return {
                    "route": "llm",
                    "type": "tool_call",
                    "tool": decision.tool,
                    "response": f"Gagal menjalankan diagnosa: {tool_res.error}",
                    "ok": False,
                }

        elif decision.decision_type == "playbook":
            # Playbook execution will be wired in Phase 4
            return {
                "route": "llm",
                "type": "playbook",
                "playbook": decision.playbook,
                "response": f"Menyiapkan playbook diagnosa '{decision.playbook}' untuk menganalisis masalah ini...",
                "ok": True,
            }

        elif decision.decision_type == "answer":
            return {
                "route": "llm",
                "type": "answer",
                "response": decision.text,
                "ok": True,
            }

        else:  # clarify
            return {
                "route": "llm",
                "type": "clarify",
                "response": decision.question,
                "ok": True,
            }


# Global orchestrator instance
orchestrator = Orchestrator()

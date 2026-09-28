"""Core Orchestrator (Phase 1, 2 & 3)."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional
from assistant.core.audit import audit_logger, AuditLogger
from assistant.core.policy import policy_engine, PolicyEngine
from assistant.tools.base import Risk, ToolDefinition, ToolResult
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
        confirm_handler: Optional[Callable[[str, ToolDefinition, dict[str, Any]], bool]] = None,
    ) -> None:
        self.registry = tool_registry or registry
        self.policy = policy or policy_engine
        self.audit = audit or audit_logger
        self._llm = llm or get_llm_client()
        self.planner = LLMPlanner(self._llm, self.registry)
        self.explainer = LLMExplainer(self._llm)
        self.confirm_handler = confirm_handler

    def _request_confirmation(self, name: str, tool_def: ToolDefinition, args: dict[str, Any]) -> bool:
        """Request explicit L3 confirmation from the user (via callback, Tk modal dialog, or CLI fallback)."""
        if self.confirm_handler is not None:
            return self.confirm_handler(name, tool_def, args)

        try:
            from assistant.ui.confirm_dialog import request_confirmation

            action_title = f"Operasi Sistem: {name}"
            target = str(args.get("file_path") or args.get("original_path") or args.get("backup_path") or args.get("target") or "System")
            details = str(args.get("reason") or args.get("explanation") or tool_def.description)
            diff_text = args.get("diff") or args.get("diff_text")

            # Auto-generate diff preview for files.apply_edit if not provided in args
            if not diff_text and name == "files.apply_edit" and "file_path" in args and "new_content" in args:
                try:
                    from assistant.tools.files.edit import propose_file_edit
                    prop = propose_file_edit(args["file_path"], args["new_content"])
                    diff_text = prop.get("diff")
                except Exception:
                    pass

            return request_confirmation(
                action_title=action_title,
                tool_name=name,
                target_resource=target,
                details=details,
                diff_text=diff_text,
                backup_path=args.get("backup_path"),
                rollback_cmd=args.get("rollback_cmd"),
            )
        except Exception:
            return False

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

        # Check L3 Confirmation
        if decision.needs_confirmation:
            confirmed = self._request_confirmation(name, tool_def, args)
            if not confirmed:
                rejection_msg = f"Tindakan '{name}' dibatalkan oleh pengguna (konfirmasi L3 ditolak)."
                self.audit.log_tool_call(
                    tool_name=name,
                    args=args,
                    risk_level=decision.risk.name,
                    decision="REJECTED_BY_USER",
                    duration_ms=0.0,
                    ok=False,
                    error=rejection_msg,
                    summary=rejection_msg,
                )
                return ToolResult.fail(rejection_msg)
            audit_decision = "CONFIRMED_AND_ALLOWED"
        else:
            audit_decision = "ALLOWED"

        start_time = time.perf_counter()
        result = tool_def.run(**args)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Record to audit log
        self.audit.log_tool_call(
            tool_name=name,
            args=args,
            risk_level=tool_def.risk.name,
            decision=audit_decision,
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
            from assistant.playbooks.engine import playbook_engine

            playbook_res = playbook_engine.run(decision.playbook, decision.args)
            if playbook_res.ok:
                explanation = self.explainer.explain(user_query, playbook_res.summary)
                return {
                    "route": "llm",
                    "type": "playbook",
                    "playbook": decision.playbook,
                    "response": explanation,
                    "findings": playbook_res.summary,
                    "rule_findings": playbook_res.rule_findings,
                    "data": playbook_res.data,
                    "ok": True,
                }
            else:
                return {
                    "route": "llm",
                    "type": "playbook",
                    "playbook": decision.playbook,
                    "response": f"Playbook '{decision.playbook}' gagal dijalankan: {playbook_res.summary}",
                    "findings": playbook_res.summary,
                    "ok": False,
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

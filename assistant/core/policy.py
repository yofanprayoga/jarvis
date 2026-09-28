"""Policy Engine enforcing Risk Model and Allowlists (Section 8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from assistant.core.config import PolicyConfig, load_policy
from assistant.tools.base import Risk, ToolDefinition


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    needs_confirmation: bool
    risk: Risk


class PolicyEngine:
    """Enforces safety constraints, risk levels, and forbidden operations."""

    def __init__(self, policy: PolicyConfig | None = None) -> None:
        self.policy = policy or load_policy()

    def evaluate(self, tool_def: ToolDefinition, args: dict[str, Any]) -> PolicyDecision:
        """Evaluate if tool execution is permitted and whether it requires confirmation."""
        # 1. Check L0: Tool declared as FORBIDDEN
        if tool_def.risk == Risk.FORBIDDEN:
            return PolicyDecision(
                allowed=False,
                reason=f"Action '{tool_def.name}' is classified as L0 (FORBIDDEN).",
                needs_confirmation=False,
                risk=tool_def.risk,
            )

        # 2. Check protected processes in arguments
        process_target = str(args.get("process_name") or args.get("name") or "").lower()
        if process_target:
            for protected in self.policy.protected_processes:
                if process_target == protected.lower() or process_target.endswith(f"\\{protected.lower()}"):
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Target process '{process_target}' is a protected Windows core process (L0).",
                        needs_confirmation=False,
                        risk=Risk.FORBIDDEN,
                    )

        # 3. Check forbidden action names
        for forbidden in self.policy.forbidden_actions:
            if forbidden.lower() in tool_def.name.lower():
                return PolicyDecision(
                    allowed=False,
                    reason=f"Action '{tool_def.name}' matches forbidden rule '{forbidden}' (L0).",
                    needs_confirmation=False,
                    risk=Risk.FORBIDDEN,
                )

        # 4. Check protected filesystem paths for modifications (L0 FORBIDDEN)
        if tool_def.risk in (Risk.CONFIRM, Risk.FORBIDDEN) or "edit" in tool_def.name or "delete" in tool_def.name:
            target_path_str = str(args.get("file_path") or args.get("original_path") or args.get("target") or "").strip()
            if target_path_str:
                from pathlib import Path
                try:
                    resolved_target = str(Path(target_path_str).resolve()).lower()
                    system_dirs = ["c:\\windows", "c:\\boot", "c:\\recovery", "c:\\program files\\windows"]
                    for sdir in system_dirs:
                        if resolved_target == sdir or resolved_target.startswith(sdir + "\\"):
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Target path '{target_path_str}' is inside protected Windows system directories (L0 FORBIDDEN).",
                                needs_confirmation=False,
                                risk=Risk.FORBIDDEN,
                            )
                except Exception:
                    pass

        # 5. Check browser actions dynamic risk (Phase 9B/9C)
        if tool_def.name.startswith("browser."):
            from assistant.tools.browser.safety import classify_action_risk
            if tool_def.name == "browser.type":
                b_risk, b_reason = classify_action_risk(
                    action="type",
                    selector=str(args.get("selector", "")),
                    text=str(args.get("text", "")),
                )
                if b_risk == Risk.FORBIDDEN:
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Action '{tool_def.name}' blocked by security policy (L0): {b_reason}",
                        needs_confirmation=False,
                        risk=Risk.FORBIDDEN,
                    )
                if b_risk == Risk.CONFIRM:
                    return PolicyDecision(
                        allowed=True,
                        reason=f"Action '{tool_def.name}' requires user confirmation (L3): {b_reason}",
                        needs_confirmation=True,
                        risk=Risk.CONFIRM,
                    )
            elif tool_def.name == "browser.click":
                b_risk, b_reason = classify_action_risk(
                    action="click",
                    selector=str(args.get("selector", "")),
                    text=str(args.get("text", "")),
                    role=str(args.get("role", "")),
                )
                if b_risk == Risk.FORBIDDEN:
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Action '{tool_def.name}' blocked by security policy (L0): {b_reason}",
                        needs_confirmation=False,
                        risk=Risk.FORBIDDEN,
                    )
                if b_risk == Risk.CONFIRM:
                    return PolicyDecision(
                        allowed=True,
                        reason=f"Action '{tool_def.name}' requires user confirmation (L3): {b_reason}",
                        needs_confirmation=True,
                        risk=Risk.CONFIRM,
                    )

        # 6. Check UI Automation and Window Management actions dynamic risk (Phase 10B/10C)
        if tool_def.name in (
            "ui.focus", "ui.invoke", "ui.set_value", "ui.toggle",
            "window.activate", "window.close",
            "ui.click_at", "ui.send_keys", "ui.type_text",
        ):
            from assistant.tools.ui.risk_classifier import classify_ui_action_from_args
            u_risk, u_reason = classify_ui_action_from_args(tool_def.name, args)
            if u_risk == Risk.FORBIDDEN:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Action '{tool_def.name}' blocked by security policy (L0): {u_reason}",
                    needs_confirmation=False,
                    risk=Risk.FORBIDDEN,
                )
            if u_risk == Risk.CONFIRM:
                return PolicyDecision(
                    allowed=True,
                    reason=f"Action '{tool_def.name}' requires user confirmation (L3): {u_reason}",
                    needs_confirmation=True,
                    risk=Risk.CONFIRM,
                )

        # 7. Check L3 (CONFIRM)
        if tool_def.risk == Risk.CONFIRM:
            return PolicyDecision(
                allowed=True,
                reason=f"Action '{tool_def.name}' requires explicit user confirmation (L3).",
                needs_confirmation=True,
                risk=tool_def.risk,
            )

        # 5. L1 (OBSERVE) and L2 (LOW_ACTION)
        return PolicyDecision(
            allowed=True,
            reason="Allowed by policy.",
            needs_confirmation=False,
            risk=tool_def.risk,
        )


# Global policy engine instance
policy_engine = PolicyEngine()

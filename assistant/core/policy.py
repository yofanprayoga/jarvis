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

        # 4. Check L3 (CONFIRM)
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

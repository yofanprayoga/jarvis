"""LLM Planner implementation (Section 10.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from assistant.llm.client import LLMClient
from assistant.llm.prompts.planner import build_planner_prompt, PLANNER_JSON_SCHEMA
from assistant.llm.tool_selector import tool_selector, ToolSelector
from assistant.tools.registry import registry, ToolRegistry


@dataclass
class PlannerDecision:
    decision_type: str  # "tool_call", "playbook", "answer", "clarify"
    tool: Optional[str] = None
    playbook: Optional[str] = None
    args: Optional[dict[str, Any]] = None
    text: Optional[str] = None
    question: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


class LLMPlanner:
    """Invokes LLM to select tool, playbook, answer, or clarify."""

    def __init__(
        self,
        llm: LLMClient,
        tool_reg: ToolRegistry | None = None,
        selector: ToolSelector | None = None,
    ) -> None:
        self.llm = llm
        self.registry = tool_reg or registry
        self.selector = selector or tool_selector

    def plan(self, user_query: str) -> PlannerDecision:
        """Produce structured plan from user query with 1-shot retry on invalid JSON schema."""
        tools_subset = self.selector.select(user_query)
        system_prompt, user_prompt = build_planner_prompt(
            user_query=user_query,
            tool_schemas=tools_subset,
            playbooks=["bsod_crash_diagnosis", "disk_full_usage", "system_slowness"],
        )

        for attempt in range(2):
            try:
                res = self.llm.generate_json(
                    prompt=user_prompt,
                    system=system_prompt,
                    schema=PLANNER_JSON_SCHEMA,
                    temperature=0.1,
                )
                dtype = res.get("type", "")
                if dtype not in ("tool_call", "playbook", "answer", "clarify"):
                    raise ValueError(f"Unknown decision type '{dtype}' in {res}")

                # If tool_call, verify tool name exists
                if dtype == "tool_call":
                    t_name = res.get("tool", "")
                    if not self.registry.get(t_name):
                        # Retry with feedback
                        user_prompt += f"\nNote: Tool '{t_name}' does not exist. Choose only from the available tools list."
                        continue
                    return PlannerDecision(
                        decision_type="tool_call",
                        tool=t_name,
                        args=res.get("args") or {},
                        raw=res,
                    )

                elif dtype == "playbook":
                    return PlannerDecision(
                        decision_type="playbook",
                        playbook=res.get("name", ""),
                        args=res.get("args") or {},
                        raw=res,
                    )

                elif dtype == "answer":
                    return PlannerDecision(
                        decision_type="answer",
                        text=res.get("text", ""),
                        raw=res,
                    )

                elif dtype == "clarify":
                    return PlannerDecision(
                        decision_type="clarify",
                        question=res.get("question", ""),
                        raw=res,
                    )

            except Exception as e:
                if attempt == 0:
                    user_prompt += f"\nPrevious response was invalid JSON ({e}). Output strictly in JSON format."
                else:
                    # Fallback after retry failure
                    return PlannerDecision(
                        decision_type="clarify",
                        question="Maaf, saya belum memahami maksud pertanyaan kamu. Bisa tolong dijelaskan lagi?",
                        raw={},
                    )

        return PlannerDecision(
            decision_type="clarify",
            question="Bisa tolong jelaskan lebih spesifik apa yang mau dicek?",
            raw={},
        )

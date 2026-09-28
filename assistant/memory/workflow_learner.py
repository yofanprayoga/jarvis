"""Workflow Learning & Pattern Detector (Phase 12).

Detects repeated successful action sequences and enables safe workflow promotion:
1. Records successful tool executions.
2. Identifies recurring multi-step sequences (length 2 to 4).
3. Generates 'candidate' workflows with occurrence tracking.
4. STRICT SAFETY: Candidate workflows NEVER execute automatically; explicit user approval is required.
5. Execution runs each step through PolicyEngine (L0/L3) and audit logging.
6. Never modifies source code, tool definitions, or security policies.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from assistant.memory.store import MemoryStore


class WorkflowLearner:
    """Detects repeated action patterns and manages workflow candidates & promotions."""

    MIN_SEQUENCE_LENGTH = 2
    MAX_SEQUENCE_LENGTH = 4
    OCCURRENCE_THRESHOLD = 2

    def __init__(self, store: Optional[MemoryStore] = None) -> None:
        self.store = store or MemoryStore()

    def record_action(
        self,
        intent: str,
        tool_name: str,
        args: dict[str, Any],
        summary: str,
        ok: bool,
    ) -> Optional[dict[str, Any]]:
        """Log action and check for newly emerged repeating patterns.

        Returns:
            Candidate workflow dictionary if a recurring pattern is newly detected/updated, else None.
        """
        if not ok:
            return None

        # Exclude memory and meta-management tools from becoming workflow steps
        if tool_name.startswith("memory.") or tool_name.startswith("workflow."):
            return None

        # 1. Record into action history
        self.store.record_action(
            intent=intent,
            tool_name=tool_name,
            args=args,
            summary=summary,
            ok=ok,
        )

        # 2. Check for repeating sequences in recent actions
        return self._detect_repeating_patterns()

    def _normalize_step(self, action: dict[str, Any]) -> dict[str, Any]:
        """Normalize an action entry into a reproducible workflow step."""
        return {
            "tool": action["tool_name"],
            "args": action.get("args", {}),
        }

    def _detect_repeating_patterns(self) -> Optional[dict[str, Any]]:
        """Search recent action history for repeated multi-step subsequences."""
        recent_actions = self.store.get_recent_actions(limit=30)
        if len(recent_actions) < self.MIN_SEQUENCE_LENGTH * 2:
            return None

        n = len(recent_actions)

        # Check candidate sequence lengths from MAX down to MIN ending at the latest action
        for seq_len in range(self.MAX_SEQUENCE_LENGTH, self.MIN_SEQUENCE_LENGTH - 1, -1):
            if n < seq_len * 2:
                continue

            target_slice = recent_actions[-seq_len:]
            target_tools = [a["tool_name"] for a in target_slice]

            # Look for an earlier identical sequence of tools in history
            match_count = 1
            for start_idx in range(n - (seq_len * 2), -1, -1):
                window = recent_actions[start_idx : start_idx + seq_len]
                window_tools = [a["tool_name"] for a in window]
                if window_tools == target_tools:
                    match_count += 1
                    break

            if match_count >= self.OCCURRENCE_THRESHOLD:
                # Formulate candidate steps
                steps = [self._normalize_step(a) for a in target_slice]
                tool_slug = "_then_".join(t.replace(".", "_") for t in target_tools)
                candidate_name = f"auto_{tool_slug}"
                suggested_trigger = " ".join(t.split(".")[-1] for t in target_tools)

                candidate_id = self.store.save_workflow_candidate(
                    name=candidate_name,
                    trigger_pattern=suggested_trigger,
                    steps=steps,
                )

                if candidate_id:
                    wf = self.store.get_workflow(candidate_id)
                    return wf

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Workflow Promotion & Management
    # ──────────────────────────────────────────────────────────────────────────

    def list_workflows(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        """List workflows by status ('candidate', 'approved', 'rejected')."""
        return self.store.list_workflows(status=status)

    def list_candidates(self) -> list[dict[str, Any]]:
        """List all candidate workflows awaiting approval."""
        return self.list_workflows(status="candidate")

    def get_workflow(self, identifier: str | int) -> Optional[dict[str, Any]]:
        """Get workflow by ID or name."""
        return self.store.get_workflow(identifier)

    def approve_workflow(
        self,
        identifier: str | int,
        name: Optional[str] = None,
        trigger_pattern: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Promote a candidate workflow to approved (executable) status."""
        wf = self.store.get_workflow(identifier)
        if not wf:
            return False, f"Workflow '{identifier}' tidak ditemukan."

        final_name = name or wf["name"]
        final_trigger = trigger_pattern or wf["trigger_pattern"]

        ok = self.store.update_workflow_status(
            identifier=identifier,
            status="approved",
            name=final_name,
            trigger_pattern=final_trigger,
        )
        if ok:
            return True, f"Workflow '{final_name}' berhasil disetujui (trigger: '{final_trigger}')."
        return False, f"Gagal menyetujui workflow '{identifier}'."

    def reject_workflow(self, identifier: str | int) -> tuple[bool, str]:
        """Mark a workflow candidate as rejected."""
        wf = self.store.get_workflow(identifier)
        if not wf:
            return False, f"Workflow '{identifier}' tidak ditemukan."

        ok = self.store.update_workflow_status(identifier=identifier, status="rejected")
        if ok:
            return True, f"Workflow candidate '{wf['name']}' telah ditolak."
        return False, f"Gagal menolak workflow '{identifier}'."

    def delete_workflow(self, identifier: str | int) -> tuple[bool, str]:
        """Delete a workflow permanently."""
        ok = self.store.delete_workflow(identifier)
        if ok:
            return True, f"Workflow '{identifier}' berhasil dihapus."
        return False, f"Workflow '{identifier}' tidak ditemukan."

    def match_approved_trigger(self, query: str) -> Optional[dict[str, Any]]:
        """Match query against approved workflow triggers."""
        q = query.lower().strip()
        approved = self.store.list_workflows(status="approved")
        for wf in approved:
            trigger = wf.get("trigger_pattern", "").lower().strip()
            if not trigger:
                continue
            if trigger == q or trigger in q or q.startswith(f"jalankan {trigger}") or q.startswith(f"run {trigger}"):
                return wf
        return None

    def execute_workflow(self, workflow: dict[str, Any], orch: Any) -> dict[str, Any]:
        """Execute all steps of an approved workflow through the Orchestrator.

        Each step is validated by PolicyEngine (L0/L3) and logged to the audit trail.
        Execution aborts immediately if any step fails.
        """
        steps = workflow.get("steps", [])
        wf_name = workflow.get("name", "unnamed_workflow")

        if not steps:
            return {
                "ok": False,
                "workflow": wf_name,
                "error": "Workflow tidak memiliki langkah eksekusi.",
                "completed_steps": 0,
                "total_steps": 0,
            }

        executed_steps = []
        for idx, step in enumerate(steps, 1):
            tool_name = step.get("tool")
            args = step.get("args", {})

            # Execute through orchestrator
            res = orch.run_tool(tool_name, args)
            executed_steps.append({
                "step": idx,
                "tool": tool_name,
                "ok": res.ok,
                "summary": res.summary,
                "error": res.error,
            })

            if not res.ok:
                return {
                    "ok": False,
                    "workflow": wf_name,
                    "failed_step": idx,
                    "failed_tool": tool_name,
                    "error": f"Langkah {idx} ('{tool_name}') gagal: {res.error}",
                    "executed_steps": executed_steps,
                    "total_steps": len(steps),
                }

        return {
            "ok": True,
            "workflow": wf_name,
            "executed_steps": executed_steps,
            "total_steps": len(steps),
            "summary": f"Workflow '{wf_name}' berhasil dijalankan ({len(steps)}/{len(steps)} langkah selesai).",
        }


# Global default WorkflowLearner instance
workflow_learner = WorkflowLearner()

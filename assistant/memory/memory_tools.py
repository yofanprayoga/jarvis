"""Memory and Workflow Management Tools (Phase 12).

Registers schema-validated tools for persistent memory and safe workflow execution:
- memory.remember
- memory.recall
- memory.forget
- memory.list
- workflow.list
- workflow.approve
- workflow.run
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.memory.manager import memory_manager
from assistant.memory.workflow_learner import workflow_learner
from assistant.tools.base import Risk, ToolResult, tool


# ──────────────────────────────────────────────────────────────────────────────
# Input Models
# ──────────────────────────────────────────────────────────────────────────────

class RememberInput(BaseModel):
    category: str = Field(description="Category: 'project', 'preference', 'alias', or 'general'")
    key: str = Field(description="Identifier or name of the fact (e.g. 'jarvis', 'browser', 'language')")
    value: str = Field(description="Value to remember (e.g. 'D:\\project\\jarvis', 'chrome.exe', 'id')")


class RecallInput(BaseModel):
    category: str = Field(description="Category: 'project', 'preference', 'alias', or 'general'")
    key: str = Field(description="Identifier or name of the fact to recall")


class ForgetInput(BaseModel):
    category: str = Field(description="Category: 'project', 'preference', 'alias', or 'general'")
    key: str = Field(description="Identifier or name of the fact to remove")


class ListMemoryInput(BaseModel):
    category: Optional[str] = Field(default=None, description="Optional category filter ('project', 'preference', 'alias', 'general')")


class ListWorkflowsInput(BaseModel):
    status: Optional[str] = Field(default=None, description="Filter by status: 'candidate', 'approved', or 'rejected'")


class ApproveWorkflowInput(BaseModel):
    name_or_id: str = Field(description="Candidate workflow name or numeric ID to approve")
    name: Optional[str] = Field(default=None, description="Optional custom name for the approved workflow")
    trigger_pattern: Optional[str] = Field(default=None, description="Optional natural language trigger phrase to run the workflow")


class RunWorkflowInput(BaseModel):
    name_or_id: str = Field(description="Name or numeric ID of the approved workflow to execute")


# ──────────────────────────────────────────────────────────────────────────────
# Memory Tools
# ──────────────────────────────────────────────────────────────────────────────

@tool(
    name="memory.remember",
    risk=Risk.LOW_ACTION,
    description="Store or update a persistent user-approved fact, project path, preference, or application alias.",
    input_model=RememberInput,
    timeout_s=5,
    requires_elevation=False,
)
def remember_tool(args: RememberInput) -> ToolResult:
    ok, msg = memory_manager.remember(
        category=args.category,
        key=args.key,
        value=args.value,
        source="user",
    )
    if not ok:
        return ToolResult.fail(msg)
    return ToolResult.success(
        data={"category": args.category, "key": args.key, "value": args.value},
        summary=msg,
    )


@tool(
    name="memory.recall",
    risk=Risk.OBSERVE,
    description="Retrieve a stored fact, preference, or project path from persistent memory.",
    input_model=RecallInput,
    timeout_s=5,
    requires_elevation=False,
)
def recall_tool(args: RecallInput) -> ToolResult:
    val = memory_manager.recall(category=args.category, key=args.key)
    if val is None:
        return ToolResult.fail(f"Fakta [{args.category}] '{args.key}' tidak ditemukan di memori.")
    return ToolResult.success(
        data={"category": args.category, "key": args.key, "value": val},
        summary=f"Memori [{args.category}] '{args.key}': {val}",
    )


@tool(
    name="memory.forget",
    risk=Risk.LOW_ACTION,
    description="Remove a fact from persistent memory.",
    input_model=ForgetInput,
    timeout_s=5,
    requires_elevation=False,
)
def forget_tool(args: ForgetInput) -> ToolResult:
    ok, msg = memory_manager.forget(category=args.category, key=args.key)
    if not ok:
        return ToolResult.fail(msg)
    return ToolResult.success(
        data={"category": args.category, "key": args.key, "removed": True},
        summary=msg,
    )


@tool(
    name="memory.list",
    risk=Risk.OBSERVE,
    description="List all stored facts, preferences, project paths, and aliases from persistent memory.",
    input_model=ListMemoryInput,
    timeout_s=5,
    requires_elevation=False,
)
def list_memory_tool(args: ListMemoryInput) -> ToolResult:
    facts = memory_manager.list_facts(category=args.category)
    if not facts:
        cat_str = f" dalam kategori '{args.category}'" if args.category else ""
        return ToolResult.success(
            data={"facts": []},
            summary=f"Tidak ada fakta memori tersimpan{cat_str}.",
        )

    lines = [f"Daftar Fakta Memori ({len(facts)} item):"]
    for f in facts:
        lines.append(f"- [{f['category']}] '{f['key']}': {f['value']}")

    return ToolResult.success(
        data={"facts": facts},
        summary="\n".join(lines),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Workflow Tools
# ──────────────────────────────────────────────────────────────────────────────

@tool(
    name="workflow.list",
    risk=Risk.OBSERVE,
    description="List candidate and approved automated workflows learned from repeated action patterns.",
    input_model=ListWorkflowsInput,
    timeout_s=5,
    requires_elevation=False,
)
def list_workflows_tool(args: ListWorkflowsInput) -> ToolResult:
    wfs = workflow_learner.list_workflows(status=args.status)
    if not wfs:
        st_str = f" berstatus '{args.status}'" if args.status else ""
        return ToolResult.success(
            data={"workflows": []},
            summary=f"Tidak ada workflow{st_str} yang tercatat.",
        )

    lines = [f"Daftar Workflow ({len(wfs)} item):"]
    for w in wfs:
        lines.append(f"- [{w['status'].upper()}] ID={w['id']} '{w['name']}' (trigger: '{w['trigger_pattern']}', {len(w.get('steps', []))} steps, seen {w.get('occurrence_count', 1)}x)")

    return ToolResult.success(
        data={"workflows": wfs},
        summary="\n".join(lines),
    )


@tool(
    name="workflow.approve",
    risk=Risk.LOW_ACTION,
    description="Promote a candidate workflow to approved status so it can be triggered by name or voice.",
    input_model=ApproveWorkflowInput,
    timeout_s=5,
    requires_elevation=False,
)
def approve_workflow_tool(args: ApproveWorkflowInput) -> ToolResult:
    ok, msg = workflow_learner.approve_workflow(
        identifier=args.name_or_id,
        name=args.name,
        trigger_pattern=args.trigger_pattern,
    )
    if not ok:
        return ToolResult.fail(msg)
    return ToolResult.success(
        data={"identifier": args.name_or_id, "approved": True},
        summary=msg,
    )


@tool(
    name="workflow.run",
    risk=Risk.LOW_ACTION,
    description="Execute an approved multi-step workflow through the Orchestrator with full policy verification.",
    input_model=RunWorkflowInput,
    timeout_s=30,
    requires_elevation=False,
)
def run_workflow_tool(args: RunWorkflowInput) -> ToolResult:
    from assistant.core.orchestrator import orchestrator

    wf = workflow_learner.get_workflow(args.name_or_id)
    if not wf:
        return ToolResult.fail(f"Workflow '{args.name_or_id}' tidak ditemukan.")

    if wf.get("status") != "approved":
        return ToolResult.fail(
            f"Workflow '{wf.get('name')}' belum disetujui (status: '{wf.get('status')}'). "
            f"Gunakan 'workflow.approve' terlebih dahulu."
        )

    res = workflow_learner.execute_workflow(wf, orchestrator)
    if not res.get("ok"):
        return ToolResult.fail(res.get("error", "Eksekusi workflow gagal."), data=res)

    return ToolResult.success(data=res, summary=res.get("summary", "Workflow berhasil dieksekusi."))

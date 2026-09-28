"""Phase 10A UI Automation Tool Definitions.

Registers three read-only L1 tools:
  - ui.inspect_tree    : UIA control tree for target window
  - ui.find_control    : Semantic multi-property control search
  - ui.get_control_info: Detailed metadata for a single control path

All outputs are tagged untrusted=True and wrapped in <untrusted_ui_content>.
No UI modification, click, invoke, focus, or value-set operations are implemented here.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.ui.uia_client import UiaError, uia_session
from assistant.tools.ui.tree_inspector import inspect_tree, render_tree_text
from assistant.tools.ui.control_finder import find_controls, get_control_by_path


def _wrap_untrusted_ui(text: str) -> str:
    """Wrap UI content in untrusted safety tags."""
    return f"<untrusted_ui_content>\n{text}\n</untrusted_ui_content>"


# ──────────────────────────────────────────────────────────────────────────────
# Input models
# ──────────────────────────────────────────────────────────────────────────────

class InspectTreeInput(BaseModel):
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window handle (HWND). Defaults to current foreground window.",
    )
    max_depth: int = Field(
        default=5, ge=1, le=10,
        description="Maximum tree traversal depth (1–10, default 5).",
    )
    max_nodes: int = Field(
        default=120, ge=1, le=500,
        description="Maximum number of nodes to collect (1–500, default 120).",
    )
    timeout_s: float = Field(
        default=3.0, ge=0.5, le=15.0,
        description="Maximum traversal time in seconds (default 3.0).",
    )


class FindControlInput(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description="Accessible name to search for (partial or exact match).",
    )
    automation_id: Optional[str] = Field(
        default=None,
        description="AutomationId property to search for.",
    )
    control_type: Optional[str] = Field(
        default=None,
        description="ControlType to filter by (e.g. 'Button', 'Edit', 'CheckBox').",
    )
    class_name: Optional[str] = Field(
        default=None,
        description="Win32/WPF ClassName to match.",
    )
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window HWND. Defaults to foreground window.",
    )
    limit: int = Field(
        default=10, ge=1, le=50,
        description="Maximum number of results to return (default 10).",
    )


class GetControlInfoInput(BaseModel):
    path: str = Field(
        description="Element path string from ui.inspect_tree or ui.find_control output.",
    )
    hwnd: Optional[int] = Field(
        default=None,
        description="Target window HWND. Defaults to foreground window.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ──────────────────────────────────────────────────────────────────────────────

@tool(
    name="ui.inspect_tree",
    risk=Risk.OBSERVE,
    description="Inspect the Windows UI Automation control tree of a window. Returns the element hierarchy with Name, AutomationId, ControlType, and metadata. All content is untrusted.",
    input_model=InspectTreeInput,
    timeout_s=15,
    requires_elevation=False,
)
def inspect_tree_tool(args: InspectTreeInput) -> ToolResult:
    try:
        with uia_session() as session:
            result = inspect_tree(
                session=session,
                hwnd=args.hwnd,
                max_depth=args.max_depth,
                max_nodes=args.max_nodes,
                timeout_s=args.timeout_s,
            )
    except UiaError as e:
        return ToolResult.fail(f"UIA error: {e}")
    except Exception as e:
        return ToolResult.fail(f"Gagal mengambil UI tree: {e}")

    if not result.get("ok"):
        return ToolResult.fail(result.get("error", "Unknown error"))

    root = result.get("root", {})
    tree_text = render_tree_text(root)
    untrusted_tree = _wrap_untrusted_ui(tree_text)

    window_name = root.get("name", "?")
    truncated_note = " (TRUNCATED)" if result.get("truncated") else ""

    summary = (
        f"UI Control Tree — '{window_name}'{truncated_note}:\n"
        f"- Nodes: {result['node_count']} | Depth: {args.max_depth} | "
        f"Time: {result['elapsed_ms']} ms\n"
        f"{untrusted_tree}"
    )

    return ToolResult.success(
        data={**result, "tree_text": tree_text},
        summary=summary,
        untrusted=True,
        max_summary_len=1500,
    )


@tool(
    name="ui.find_control",
    risk=Risk.OBSERVE,
    description="Find UI controls by semantic properties (Name, AutomationId, ControlType, ClassName). Returns ranked matches with confidence scores. Ambiguous matches are flagged.",
    input_model=FindControlInput,
    timeout_s=15,
    requires_elevation=False,
)
def find_control_tool(args: FindControlInput) -> ToolResult:
    if not any([args.name, args.automation_id, args.control_type, args.class_name]):
        return ToolResult.fail(
            "Setidaknya satu kriteria pencarian harus diberikan: name, automation_id, control_type, atau class_name."
        )

    try:
        with uia_session() as session:
            tree_result = inspect_tree(
                session=session,
                hwnd=args.hwnd,
                max_depth=6,
                max_nodes=200,
                timeout_s=5.0,
            )
    except UiaError as e:
        return ToolResult.fail(f"UIA error: {e}")
    except Exception as e:
        return ToolResult.fail(f"Gagal mengambil UI tree untuk pencarian: {e}")

    if not tree_result.get("ok"):
        return ToolResult.fail(tree_result.get("error", "Unknown error"))

    matches = find_controls(
        tree_root=tree_result["root"],
        name=args.name,
        automation_id=args.automation_id,
        control_type=args.control_type,
        class_name=args.class_name,
        limit=args.limit,
    )

    if not matches:
        criteria = {
            "name": args.name,
            "automation_id": args.automation_id,
            "control_type": args.control_type,
            "class_name": args.class_name,
        }
        return ToolResult.success(
            data={"matches": [], "criteria": criteria, "total": 0, "untrusted": True},
            summary=f"Tidak ada kontrol yang ditemukan untuk kriteria: {criteria}",
            untrusted=True,
        )

    lines = [f"Ditemukan {len(matches)} kontrol:\n"]
    for i, m in enumerate(matches, 1):
        ambig = " [AMBIGU]" if m["ambiguous"] else ""
        pw = " [PASSWORD_FIELD]" if m["is_password"] else ""
        lines.append(
            f"{i}. [{m['control_type']}]{pw} \"{m['name']}\""
            f" id={m['automation_id']!r}"
            f" conf={m['confidence']:.2f}{ambig}"
            f"\n   path={m['path']}"
        )

    summary = _wrap_untrusted_ui("\n".join(lines))

    return ToolResult.success(
        data={"matches": matches, "total": len(matches), "untrusted": True},
        summary=summary,
        untrusted=True,
        max_summary_len=1500,
    )


@tool(
    name="ui.get_control_info",
    risk=Risk.OBSERVE,
    description="Get detailed UIA metadata for a specific control identified by its path. Passwords and credential values are always REDACTED.",
    input_model=GetControlInfoInput,
    timeout_s=10,
    requires_elevation=False,
)
def get_control_info_tool(args: GetControlInfoInput) -> ToolResult:
    try:
        with uia_session() as session:
            tree_result = inspect_tree(
                session=session,
                hwnd=args.hwnd,
                max_depth=8,
                max_nodes=300,
                timeout_s=5.0,
            )
    except UiaError as e:
        return ToolResult.fail(f"UIA error: {e}")
    except Exception as e:
        return ToolResult.fail(f"Gagal mengambil UI tree: {e}")

    if not tree_result.get("ok"):
        return ToolResult.fail(tree_result.get("error", "Unknown error"))

    node = get_control_by_path(tree_result["root"], args.path)
    if not node:
        return ToolResult.fail(
            f"Kontrol dengan path '{args.path}' tidak ditemukan di UI tree."
        )

    is_password = node.get("is_password", False)
    rect = node.get("bounding_rect", {})
    rect_str = (
        f"{rect.get('width', 0)}x{rect.get('height', 0)} px @ "
        f"({rect.get('left', 0)}, {rect.get('top', 0)})"
        if rect else "Unknown"
    )

    info_text = (
        f"Informasi Control:\n"
        f"- Tipe: {node.get('control_type', '?')}\n"
        f"- Nama: {'[PASSWORD_FIELD — REDACTED]' if is_password else repr(node.get('name', ''))}\n"
        f"- AutomationId: {node.get('automation_id', '') or '(none)'}\n"
        f"- ClassName: {node.get('class_name', '') or '(none)'}\n"
        f"- Framework: {node.get('framework_id', '') or '(none)'}\n"
        f"- Enabled: {node.get('is_enabled', True)} | Offscreen: {node.get('is_offscreen', False)}\n"
        f"- Ukuran: {rect_str}\n"
        f"- Path: {node.get('path', '?')}\n"
        f"- Keamanan: {'🔴 PASSWORD/CREDENTIAL FIELD — nilai tidak dapat dibaca' if is_password else '✅ Non-sensitive'}"
    )

    summary = _wrap_untrusted_ui(info_text)
    return ToolResult.success(data=node, summary=summary, untrusted=True)

"""Semantic control finder for UIA element trees (Phase 10A).

Performs multi-property matching against an inspected control tree.
Matching is based on:
  - Name (window title or accessible name)
  - AutomationId (stable developer-assigned identifier)
  - ControlType (button, edit, checkbox, etc.)
  - ClassName (Win32/WPF class name)

Confidence scoring:
  - AutomationId match:  weight 0.50 (most stable property)
  - Name exact match:    weight 0.30
  - Name partial match:  weight 0.15
  - ControlType match:   weight 0.12
  - ClassName match:     weight 0.10
  - Combined score:      summed, capped at 1.0
  - Threshold >= 0.40 to be included in results
  - Results < 0.70 are flagged as ambiguous

Security: Password field detection returns a safe metadata dict,
not the actual credential value.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Minimum confidence to include in results
_THRESHOLD = 0.40
# Confidence below this is flagged as "ambiguous"
_AMBIGUOUS_THRESHOLD = 0.70

# ControlType name aliases accepted from callers
_CONTROL_TYPE_ALIASES: dict[str, str] = {
    "btn": "Button",
    "button": "Button",
    "edit": "Edit",
    "input": "Edit",
    "textbox": "Edit",
    "text": "Text",
    "label": "Text",
    "checkbox": "CheckBox",
    "check": "CheckBox",
    "combobox": "ComboBox",
    "combo": "ComboBox",
    "list": "List",
    "listitem": "ListItem",
    "tree": "Tree",
    "treeitem": "TreeItem",
    "tab": "Tab",
    "tabitem": "TabItem",
    "window": "Window",
    "pane": "Pane",
    "menu": "Menu",
    "menuitem": "MenuItem",
    "menubar": "MenuBar",
    "radio": "RadioButton",
    "radiobutton": "RadioButton",
    "slider": "Slider",
    "spinner": "Spinner",
    "scrollbar": "ScrollBar",
    "toolbar": "ToolBar",
    "tooltip": "ToolTip",
    "progressbar": "ProgressBar",
    "hyperlink": "Hyperlink",
    "link": "Hyperlink",
    "image": "Image",
    "group": "Group",
    "document": "Document",
    "custom": "Custom",
}


def _normalize_ct(ct_query: str) -> str:
    """Normalize a caller-supplied control type string."""
    normalized = ct_query.strip().lower().replace(" ", "").replace("_", "")
    return _CONTROL_TYPE_ALIASES.get(normalized, ct_query.strip())


def _score_match(
    node: dict,
    name_query: Optional[str],
    auto_id_query: Optional[str],
    control_type_query: Optional[str],
    class_name_query: Optional[str],
) -> float:
    """Compute a confidence score [0.0, 1.0] for a node against search criteria.

    Weight design:
    - AutomationId exact: 0.50  (most stable; developer-assigned)
    - AutomationId partial: 0.25
    - Name exact: 0.35          (user-visible; localizable)
    - Name partial: 0.20
    - Name contained-in: 0.10
    - ControlType exact: 0.40   (standalone type queries must pass threshold)
    - ClassName exact: 0.15     (less semantic, more structural)
    - ClassName partial: 0.08

    Threshold = 0.40, so ControlType-only queries qualify without additional criteria.
    """
    score = 0.0
    node_name = (node.get("name") or "").strip()
    node_auto_id = (node.get("automation_id") or "").strip()
    node_ctrl_type = (node.get("control_type") or "").strip()
    node_class = (node.get("class_name") or "").strip()

    # AutomationId (highest weight, most stable)
    if auto_id_query:
        if node_auto_id.lower() == auto_id_query.strip().lower():
            score += 0.50
        elif auto_id_query.strip().lower() in node_auto_id.lower():
            score += 0.25

    # Name matching
    if name_query:
        q_lower = name_query.strip().lower()
        n_lower = node_name.lower()
        if n_lower == q_lower:
            score += 0.35
        elif q_lower in n_lower:
            score += 0.20
        elif n_lower in q_lower and n_lower:
            score += 0.10

    # ControlType matching (weight raised to 0.40 so standalone queries pass threshold)
    if control_type_query:
        normalized_ct = _normalize_ct(control_type_query)
        if node_ctrl_type.lower() == normalized_ct.lower():
            score += 0.40

    # ClassName matching
    if class_name_query:
        q_class = class_name_query.strip().lower()
        if node_class.lower() == q_class:
            score += 0.15
        elif q_class in node_class.lower():
            score += 0.08

    return min(score, 1.0)


def _collect_matches(
    node: dict,
    name_query: Optional[str],
    auto_id_query: Optional[str],
    control_type_query: Optional[str],
    class_name_query: Optional[str],
    results: list[dict],
    limit: int,
) -> None:
    """Recursively collect matching nodes from a tree."""
    if len(results) >= limit:
        return
    if node.get("truncated"):
        return

    score = _score_match(node, name_query, auto_id_query, control_type_query, class_name_query)
    if score >= _THRESHOLD:
        # Build a clean result entry (safe subset of node properties)
        is_password = node.get("is_password", False)
        result = {
            "confidence": round(score, 3),
            "ambiguous": score < _AMBIGUOUS_THRESHOLD,
            "path": node.get("path", ""),
            "name": "[PASSWORD_FIELD]" if is_password else (node.get("name") or ""),
            "automation_id": node.get("automation_id") or "",
            "control_type": node.get("control_type") or "",
            "class_name": node.get("class_name") or "",
            "framework_id": node.get("framework_id") or "",
            "is_password": is_password,
            "is_enabled": node.get("is_enabled", True),
            "is_offscreen": node.get("is_offscreen", False),
            "bounding_rect": node.get("bounding_rect", {}),
            "depth": node.get("depth", -1),
            "untrusted": True,
        }
        results.append(result)

    for child in node.get("children", []):
        if len(results) >= limit:
            break
        _collect_matches(
            child, name_query, auto_id_query, control_type_query, class_name_query,
            results, limit
        )


def find_controls(
    tree_root: dict,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Search a UIA tree for controls matching the given semantic criteria.

    At least one criterion must be provided. Returns up to `limit` results
    sorted by confidence (descending). Results with confidence < 0.70 are
    flagged as `ambiguous=True`.

    Args:
        tree_root:      Root node from tree_inspector.inspect_tree().
        name:           Accessible name to match (partial/exact).
        automation_id:  AutomationId to match (partial/exact).
        control_type:   ControlType name (e.g. "Button", "Edit"). Aliases supported.
        class_name:     Win32/WPF class name to match.
        limit:          Maximum results to return (default 10).

    Returns:
        List of match dicts ordered by confidence descending.
    """
    if not any([name, automation_id, control_type, class_name]):
        return []

    results: list[dict] = []
    _collect_matches(
        node=tree_root,
        name_query=name,
        auto_id_query=automation_id,
        control_type_query=control_type,
        class_name_query=class_name,
        results=results,
        limit=max(1, limit),
    )

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results


def get_control_by_path(tree_root: dict, path: str) -> Optional[dict]:
    """Retrieve a node from the tree by its exact path string.

    Returns a safe node dict, or None if not found.
    """
    if tree_root.get("path") == path:
        return _safe_node_copy(tree_root)
    for child in tree_root.get("children", []):
        result = get_control_by_path(child, path)
        if result is not None:
            return result
    return None


def _safe_node_copy(node: dict) -> dict:
    """Return a safe metadata copy of a node (no children, password-safe)."""
    is_password = node.get("is_password", False)
    return {
        "name": "[PASSWORD_FIELD]" if is_password else (node.get("name") or ""),
        "automation_id": node.get("automation_id") or "",
        "control_type": node.get("control_type") or "",
        "class_name": node.get("class_name") or "",
        "framework_id": node.get("framework_id") or "",
        "is_password": is_password,
        "is_enabled": node.get("is_enabled", True),
        "is_offscreen": node.get("is_offscreen", False),
        "bounding_rect": node.get("bounding_rect", {}),
        "depth": node.get("depth", -1),
        "path": node.get("path", ""),
        "untrusted": True,
    }

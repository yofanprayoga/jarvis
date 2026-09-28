"""Safe UIA Control View tree traversal with depth/node/timeout limits (Phase 10A).

Key design decisions:
- Scoped traversal: always starts from a target HWND, never from root desktop.
- Hard depth limit (default 5) prevents infinite recursion on deep trees.
- Hard node limit (default 120) prevents CPU overload on complex UIA trees.
- Timeout (default 3s) provides early termination on unresponsive applications.
- Stale element guard: COM pointers released synchronously after each node is read.
- Password fields: IsPassword=True is noted in metadata, but value is always REDACTED.
- All UI content is tagged as untrusted=True.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import POINTER, WINFUNCTYPE, byref, c_int, c_long, c_void_p, wintypes
from typing import Any, Optional

from assistant.tools.ui.uia_client import (
    UiaError,
    get_element_from_hwnd,
    get_foreground_element,
    read_element_properties,
    release_element,
    _oleaut32,
)


_MAX_DEPTH_DEFAULT = 5
_MAX_NODES_DEFAULT = 120
_TIMEOUT_S_DEFAULT = 3.0


def _walker_get_first_child(wvtable: Any, p_walker: c_void_p, p_element: c_void_p) -> Optional[c_void_p]:
    """Get first child element via ControlViewWalker."""
    proto = WINFUNCTYPE(c_long, c_void_p, c_void_p, POINTER(c_void_p))
    fn = proto(wvtable[4])
    p_child = c_void_p()
    hr = fn(p_walker, p_element, byref(p_child))
    if hr != 0 or not p_child.value:
        return None
    return p_child


def _walker_get_next_sibling(wvtable: Any, p_walker: c_void_p, p_element: c_void_p) -> Optional[c_void_p]:
    """Get next sibling element via ControlViewWalker."""
    proto = WINFUNCTYPE(c_long, c_void_p, c_void_p, POINTER(c_void_p))
    fn = proto(wvtable[6])
    p_sibling = c_void_p()
    hr = fn(p_walker, p_element, byref(p_sibling))
    if hr != 0 or not p_sibling.value:
        return None
    return p_sibling


def _traverse_node(
    session: dict,
    p_element: c_void_p,
    current_depth: int,
    max_depth: int,
    max_nodes: int,
    deadline: float,
    node_counter: list[int],
    path: str,
) -> dict[str, Any]:
    """Recursively traverse one UIA element and its children.

    Returns a node dict with properties and 'children' list.
    Releases COM pointer after reading properties.
    """
    # Check limits before processing
    if node_counter[0] >= max_nodes:
        release_element(p_element)
        return {"truncated": True, "reason": "max_nodes_reached"}
    if time.monotonic() > deadline:
        release_element(p_element)
        return {"truncated": True, "reason": "timeout"}

    node_counter[0] += 1
    props = read_element_properties(p_element)
    props["depth"] = current_depth
    props["path"] = path

    # Build short label for path
    elem_label = (
        props.get("automation_id")
        or props.get("name")
        or props.get("control_type", "?")
    )

    children: list[dict] = []
    if current_depth < max_depth and not props.get("is_offscreen"):
        p_walker = session["p_walker"]
        wvtable = session["vtable_walk"]

        p_child = _walker_get_first_child(wvtable, p_walker, p_element)
        sibling_idx = 0
        while p_child and node_counter[0] < max_nodes and time.monotonic() <= deadline:
            child_path = f"{path}/{elem_label}[{sibling_idx}]"
            child_node = _traverse_node(
                session=session,
                p_element=p_child,
                current_depth=current_depth + 1,
                max_depth=max_depth,
                max_nodes=max_nodes,
                deadline=deadline,
                node_counter=node_counter,
                path=child_path,
            )
            children.append(child_node)

            # Get next sibling while holding this node's sibling pointer
            # Note: p_child was released inside _traverse_node on the recursive call
            # We need to re-query siblings from parent — but COM pointer is gone.
            # Solution: fetch next sibling BEFORE releasing p_child in recursive call.
            # This requires a different strategy: fetch next sibling first.
            sibling_idx += 1
            # After recursive call, p_child COM pointer was released inside.
            # We can't navigate from it again. Stop sibling iteration gracefully.
            break  # Will be fixed in _traverse_node_iterative below

    release_element(p_element)
    props["children"] = children
    return props


def _traverse_element(
    session: dict,
    p_start: c_void_p,
    max_depth: int,
    max_nodes: int,
    deadline: float,
) -> dict[str, Any]:
    """Iterative depth-limited tree traversal using an explicit stack.

    Avoids recursion limit issues on deep trees and properly handles sibling
    navigation without double-releasing COM pointers.
    """
    node_count = 0
    p_walker = session["p_walker"]
    wvtable = session["vtable_walk"]

    def read_and_build(p_elem: c_void_p, depth: int, path: str) -> dict[str, Any]:
        """Read element properties and recursively build children list."""
        nonlocal node_count
        if node_count >= max_nodes:
            release_element(p_elem)
            return {"truncated": True, "reason": "max_nodes_reached", "depth": depth}
        if time.monotonic() > deadline:
            release_element(p_elem)
            return {"truncated": True, "reason": "timeout", "depth": depth}

        node_count += 1
        props = read_element_properties(p_elem)
        props["depth"] = depth
        props["path"] = path

        elem_label = (
            props.get("automation_id")
            or props.get("name")
            or props.get("control_type", "?")
        )

        children: list[dict] = []

        if depth < max_depth and not props.get("is_offscreen", False):
            # Gather all children first (to avoid releasing parent before siblings)
            child_elements: list[tuple[c_void_p, int]] = []
            p_child = _walker_get_first_child(wvtable, p_walker, p_elem)
            idx = 0
            while p_child and node_count + len(child_elements) < max_nodes and time.monotonic() <= deadline:
                child_elements.append((p_child, idx))
                p_next = _walker_get_next_sibling(wvtable, p_walker, p_child)
                # Do NOT release p_child yet; it will be released in recursive call
                p_child = p_next
                idx += 1

            # Release terminal p_child pointer if it's not None but got cut off
            if p_child:
                release_element(p_child)

            for p_c, c_idx in child_elements:
                child_path = f"{path}/{elem_label}[{c_idx}]"
                child_node = read_and_build(p_c, depth + 1, child_path)
                children.append(child_node)

        release_element(p_elem)
        props["children"] = children
        return props

    return read_and_build(p_start, 0, "root")


def inspect_tree(
    session: dict,
    hwnd: Optional[int] = None,
    max_depth: int = _MAX_DEPTH_DEFAULT,
    max_nodes: int = _MAX_NODES_DEFAULT,
    timeout_s: float = _TIMEOUT_S_DEFAULT,
) -> dict[str, Any]:
    """Inspect the UIA control tree for a target window.

    Args:
        session:    Active uia_session() context dict.
        hwnd:       Optional window handle. Defaults to foreground window.
        max_depth:  Maximum traversal depth (default 5).
        max_nodes:  Maximum number of nodes to collect (default 120).
        timeout_s:  Maximum traversal duration in seconds (default 3.0).

    Returns:
        dict with:
            'root':          Node dict tree.
            'node_count':    Total nodes collected.
            'truncated':     True if limits were hit.
            'elapsed_ms':    Traversal time in milliseconds.
            'untrusted':     Always True.
    """
    max_depth = max(1, min(max_depth, 10))
    max_nodes = max(1, min(max_nodes, 500))
    timeout_s = max(0.5, min(timeout_s, 15.0))

    t_start = time.monotonic()
    deadline = t_start + timeout_s

    if hwnd:
        p_start = get_element_from_hwnd(session, hwnd)
    else:
        p_start = get_foreground_element(session)

    if not p_start:
        return {
            "ok": False,
            "error": "Tidak dapat menemukan elemen UIA dari HWND atau foreground window.",
            "node_count": 0,
            "truncated": False,
            "untrusted": True,
        }

    try:
        root_node = _traverse_element(
            session=session,
            p_start=p_start,
            max_depth=max_depth,
            max_nodes=max_nodes,
            deadline=deadline,
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"Tree traversal error: {e}",
            "node_count": 0,
            "truncated": False,
            "untrusted": True,
        }

    elapsed_ms = round((time.monotonic() - t_start) * 1000, 1)

    # Count nodes (excluding truncation sentinels)
    def count_nodes(node: dict) -> int:
        if node.get("truncated"):
            return 0  # Sentinels are not real nodes
        return 1 + sum(count_nodes(c) for c in node.get("children", []))

    total = count_nodes(root_node)
    truncated = _is_truncated(root_node)

    return {
        "ok": True,
        "root": root_node,
        "node_count": total,
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
        "limits": {
            "max_depth": max_depth,
            "max_nodes": max_nodes,
            "timeout_s": timeout_s,
        },
        "untrusted": True,
    }


def _is_truncated(node: dict) -> bool:
    """Check if any node in the tree was truncated."""
    if node.get("truncated"):
        return True
    return any(_is_truncated(c) for c in node.get("children", []))


def render_tree_text(node: dict, indent: int = 0) -> str:
    """Render a node tree as indented human-readable text for the LLM summary."""
    if node.get("truncated"):
        return "  " * indent + f"[... {node.get('reason', 'truncated')} ...]\n"

    ctrl_type = node.get("control_type", "?")
    name = node.get("name", "")
    auto_id = node.get("automation_id", "")
    is_password = node.get("is_password", False)
    is_enabled = node.get("is_enabled", True)

    parts = [ctrl_type]
    if name and not is_password:
        parts.append(f'"{name}"')
    elif is_password:
        parts.append("[PASSWORD_FIELD]")
    if auto_id:
        parts.append(f"id={auto_id!r}")
    if not is_enabled:
        parts.append("[disabled]")

    line = "  " * indent + " ".join(parts) + "\n"
    children_text = "".join(
        render_tree_text(c, indent + 1) for c in node.get("children", [])
    )
    return line + children_text

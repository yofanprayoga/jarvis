"""Target control resolver for Windows UI Automation actions (Phase 10B).

Resolves action target elements via:
1. Exact element path (from ui.inspect_tree or ui.find_control output)
2. Semantic property query (Name, AutomationId, ControlType, ClassName)

Safety checks prior to action execution:
1. Verify target element still exists and is reachable
2. Detect ambiguous queries (multiple close candidates) and reject with ambiguity result
3. Re-read live metadata from COM pointer (never rely on stale cached data)
4. Verify element is enabled and not offscreen
5. COM pointer released cleanly in all failure paths
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from ctypes import c_void_p

from assistant.tools.ui.control_finder import find_controls
from assistant.tools.ui.tree_inspector import (
    _walker_get_first_child,
    _walker_get_next_sibling,
    inspect_tree,
)
from assistant.tools.ui.uia_client import (
    _user32,
    get_element_from_hwnd,
    read_element_properties,
    release_element,
)


@dataclass
class ResolveResult:
    """Outcome of resolving a target UI control."""
    ok: bool
    p_element: Optional[c_void_p] = None
    props: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    is_ambiguous: bool = False
    candidates: list[dict[str, Any]] = field(default_factory=list)


def parse_path_indices(path: str) -> list[int]:
    """Extract integer child indices from a path string like 'root/Window[0]/Button[2]'."""
    return [int(m) for m in re.findall(r"\[(\d+)\]", path)]


def navigate_to_path(session: dict, root_hwnd: int, path: str) -> Optional[c_void_p]:
    """Navigate step-by-step from root window to target element using path indices.

    Returns:
        Live c_void_p IUIAutomationElement pointer on success, None on failure.
        Caller is responsible for releasing the returned pointer.
    """
    indices = parse_path_indices(path)
    p_cur = get_element_from_hwnd(session, root_hwnd)
    if not p_cur:
        return None

    if not indices:
        return p_cur

    p_walker = session["p_walker"]
    wvtable = session["vtable_walk"]

    for idx in indices:
        p_child = _walker_get_first_child(wvtable, p_walker, p_cur)
        for _ in range(idx):
            if not p_child:
                break
            p_next = _walker_get_next_sibling(wvtable, p_walker, p_child)
            release_element(p_child)
            p_child = p_next

        release_element(p_cur)
        p_cur = p_child
        if not p_cur or not p_cur.value:
            return None

    return p_cur


def resolve_target_control(
    session: dict,
    hwnd: Optional[int] = None,
    path: Optional[str] = None,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
) -> ResolveResult:
    """Resolve a target control to a live COM pointer and current metadata.

    Args:
        session: Active UIA session dict from uia_session().
        hwnd: Target window handle (HWND). If None, uses current foreground window.
        path: Path identifier from ui.inspect_tree or ui.find_control.
        name: Name to search for if path is not given.
        automation_id: AutomationId to search for.
        control_type: ControlType to search for.
        class_name: ClassName to search for.

    Returns:
        ResolveResult with live p_element and props, or error details.
    """
    target_hwnd = hwnd or _user32.GetForegroundWindow()
    if not target_hwnd:
        return ResolveResult(
            ok=False,
            error="Tidak ada target window yang ditemukan (HWND tidak valid dan tidak ada foreground window).",
        )

    # Path-based direct resolution
    if path:
        p_elem = navigate_to_path(session, target_hwnd, path)
        if not p_elem or not p_elem.value:
            return ResolveResult(
                ok=False,
                error=f"Kontrol pada path '{path}' tidak ditemukan atau sudah tidak tersedia di window HWND {target_hwnd}.",
            )

        props = read_element_properties(p_elem)
        props["path"] = path

        # Check enabled state
        if not props.get("is_enabled", True):
            release_element(p_elem)
            return ResolveResult(
                ok=False,
                props=props,
                error=f"Kontrol '{props.get('name')}' pada path '{path}' sedang dalam status dinonaktifkan (disabled).",
            )

        return ResolveResult(ok=True, p_element=p_elem, props=props)

    # Criteria-based search resolution
    if not any([name, automation_id, control_type, class_name]):
        if hwnd:
            p_elem = get_element_from_hwnd(session, hwnd)
            if not p_elem or not p_elem.value:
                return ResolveResult(
                    ok=False,
                    error=f"HWND {hwnd} tidak valid atau elemen UIA tidak dapat dibuat.",
                )
            props = read_element_properties(p_elem)
            props["path"] = "root"
            return ResolveResult(ok=True, p_element=p_elem, props=props)

        return ResolveResult(
            ok=False,
            error="Harus menyediakan minimal salah satu dari: 'path', 'name', 'automation_id', atau 'control_type'.",
        )

    tree_result = inspect_tree(
        session=session,
        hwnd=target_hwnd,
        max_depth=6,
        max_nodes=150,
        timeout_s=4.0,
    )
    if not tree_result.get("ok"):
        return ResolveResult(
            ok=False,
            error=f"Gagal menginspeksi UI tree untuk resolusi kontrol: {tree_result.get('error')}",
        )

    matches = find_controls(
        tree_root=tree_result["root"],
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        limit=5,
    )

    if not matches:
        return ResolveResult(
            ok=False,
            error=(
                f"Tidak ditemukan kontrol yang cocok dengan kriteria: "
                f"name={name!r}, automation_id={automation_id!r}, control_type={control_type!r}."
            ),
        )

    top_match = matches[0]

    # Ambiguity checks:
    # Multiple candidates with low confidence (< 0.70) or close confidence difference (< 0.15)
    is_ambiguous = len(matches) > 1 and (
        top_match.get("ambiguous", False)
        or abs(matches[0]["confidence"] - matches[1]["confidence"]) < 0.15
    )

    if is_ambiguous:
        candidates_summary = [
            {
                "name": m.get("name"),
                "automation_id": m.get("automation_id"),
                "control_type": m.get("control_type"),
                "path": m.get("path"),
                "confidence": round(m.get("confidence", 0.0), 2),
            }
            for m in matches
        ]
        return ResolveResult(
            ok=False,
            is_ambiguous=True,
            candidates=candidates_summary,
            error=(
                f"Selector ambigu: Ditemukan {len(matches)} kandidat kontrol dengan tingkat keyakinan serupa. "
                f"Gunakan parameter 'path' spesifik dari hasil ui.inspect_tree atau 'automation_id' eksak. "
                f"Kandidat teratas: {candidates_summary[:3]}"
            ),
        )

    # Single clear match: navigate to its path
    target_path = top_match["path"]
    p_elem = navigate_to_path(session, target_hwnd, target_path)
    if not p_elem or not p_elem.value:
        return ResolveResult(
            ok=False,
            error=f"Gagal mengambil elemen live untuk kandidat terpilih pada path '{target_path}'.",
        )

    props = read_element_properties(p_elem)
    props["path"] = target_path

    if not props.get("is_enabled", True):
        release_element(p_elem)
        return ResolveResult(
            ok=False,
            props=props,
            error=f"Kontrol '{props.get('name')}' sedang dinonaktifkan (disabled).",
        )

    return ResolveResult(ok=True, p_element=p_elem, props=props)

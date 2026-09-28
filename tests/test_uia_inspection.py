"""Unit tests for Phase 10A — Desktop GUI Inspection via Windows UI Automation.

Tests cover:
1. COM/UIA initialization
2. Foreground HWND → IUIAutomationElement acquisition
3. Tree traversal
4. Depth limit enforcement
5. Node limit enforcement
6. Timeout/early termination (on large desktop tree)
7. Semantic control finder
8. Name/AutomationId/ControlType/ClassName extraction
9. Password metadata detection + value redaction (unit + structural tests)
10. Untrusted tagging
11. Invalid/stale HWND handling
12. Tool registration and policy
"""

from __future__ import annotations

import subprocess
import sys
import time
import unittest
from pathlib import Path

# ------------------------------------------------------------------
# Ensure assistant package is importable
# ------------------------------------------------------------------
import assistant.tools  # noqa: F401

from assistant.core.policy import PolicyEngine
from assistant.tools.base import Risk
from assistant.tools.registry import registry
from assistant.tools.ui.control_finder import find_controls, _normalize_ct
from assistant.tools.ui.tree_inspector import (
    inspect_tree,
    render_tree_text,
    _is_truncated,
)
from assistant.tools.ui.uia_client import (
    UiaError,
    get_element_from_hwnd,
    get_foreground_element,
    get_root_element,
    read_element_properties,
    release_element,
    uia_session,
)


# ------------------------------------------------------------------
# Fixture helpers
# ------------------------------------------------------------------

_FIXTURE_PROC: subprocess.Popen = None


def _launch_fixture_and_get_hwnd(timeout_s: float = 20.0) -> int:
    """Launch the Tkinter fixture window and return its HWND."""
    global _FIXTURE_PROC
    fixture_script = str(
        (Path("tests") / "fixtures" / "test_gui_window.py").resolve()
    )
    _FIXTURE_PROC = subprocess.Popen(
        [sys.executable, fixture_script, str(timeout_s)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    for _ in range(40):
        line = _FIXTURE_PROC.stdout.readline().strip()
        if line.startswith("HWND:"):
            hwnd = int(line.split(":")[1])
            # Give Tk a moment to fully render before UIA is queried
            time.sleep(0.4)
            return hwnd
        time.sleep(0.15)
    return 0


def _close_fixture():
    global _FIXTURE_PROC
    if _FIXTURE_PROC and _FIXTURE_PROC.poll() is None:
        _FIXTURE_PROC.kill()
        try:
            _FIXTURE_PROC.stdout.close()
        except Exception:
            pass
        _FIXTURE_PROC = None


# ------------------------------------------------------------------
# Helper: build a fake tree dict for structural unit tests
# ------------------------------------------------------------------

def _make_fake_tree():
    """Return a small fake control tree dict for structural unit tests."""
    return {
        "name": "Test Window",
        "control_type": "Window",
        "automation_id": "MainWindow",
        "class_name": "MyAppClass",
        "framework_id": "Win32",
        "is_enabled": True,
        "is_offscreen": False,
        "is_password": False,
        "process_id": 9999,
        "bounding_rect": {"left": 0, "top": 0, "right": 800, "height": 600, "width": 800, "bottom": 600},
        "depth": 0,
        "path": "root",
        "untrusted": True,
        "children": [
            {
                "name": "OK",
                "control_type": "Button",
                "automation_id": "btn_ok",
                "class_name": "Button",
                "framework_id": "Win32",
                "is_enabled": True,
                "is_offscreen": False,
                "is_password": False,
                "process_id": 9999,
                "bounding_rect": {},
                "depth": 1,
                "path": "root/MainWindow[0]",
                "untrusted": True,
                "children": [],
            },
            {
                "name": "Cancel",
                "control_type": "Button",
                "automation_id": "btn_cancel",
                "class_name": "Button",
                "framework_id": "Win32",
                "is_enabled": True,
                "is_offscreen": False,
                "is_password": False,
                "process_id": 9999,
                "bounding_rect": {},
                "depth": 1,
                "path": "root/MainWindow[1]",
                "untrusted": True,
                "children": [],
            },
            {
                "name": "",
                "control_type": "Edit",
                "automation_id": "search_input",
                "class_name": "Edit",
                "framework_id": "Win32",
                "is_enabled": True,
                "is_offscreen": False,
                "is_password": False,
                "process_id": 9999,
                "bounding_rect": {},
                "depth": 1,
                "path": "root/MainWindow[2]",
                "untrusted": True,
                "children": [],
            },
            {
                "name": "",
                "control_type": "Edit",
                "automation_id": "password_field",
                "class_name": "Edit",
                "framework_id": "Win32",
                "is_enabled": True,
                "is_offscreen": False,
                "is_password": True,   # <-- password field
                "process_id": 9999,
                "bounding_rect": {},
                "depth": 1,
                "path": "root/MainWindow[3]",
                "untrusted": True,
                "children": [],
            },
        ],
    }


# ==================================================================================
# Test Classes
# ==================================================================================


class TestUiaCore(unittest.TestCase):
    """Tests for uia_client COM initialization and element acquisition."""

    def test_01_com_initialization(self):
        """UIA session must initialize COM and create IUIAutomation without error."""
        with uia_session() as session:
            self.assertIsNotNone(session["p_automation"].value)
            self.assertIsNotNone(session["p_walker"].value)

    def test_02_get_root_element(self):
        """Root desktop element must be acquirable."""
        with uia_session() as session:
            p_root = get_root_element(session)
            self.assertIsNotNone(p_root)
            props = read_element_properties(p_root)
            self.assertIn("Desktop", props.get("name", ""))
            release_element(p_root)

    def test_03_foreground_element(self):
        """Foreground window element must be acquirable."""
        with uia_session() as session:
            p_elem = get_foreground_element(session)
            self.assertIsNotNone(p_elem, "Should get a foreground element")
            props = read_element_properties(p_elem)
            self.assertIn("name", props)
            self.assertIn("control_type", props)
            self.assertTrue(props["untrusted"])
            release_element(p_elem)

    def test_04_invalid_hwnd_returns_none(self):
        """Getting element from an invalid/stale HWND must return None gracefully."""
        with uia_session() as session:
            p_elem = get_element_from_hwnd(session, hwnd=0xDEAD)
            self.assertIsNone(p_elem)


class TestTreeInspector(unittest.TestCase):
    """Tests for tree traversal limits and structure."""

    @classmethod
    def setUpClass(cls):
        cls.fixture_hwnd = _launch_fixture_and_get_hwnd()

    @classmethod
    def tearDownClass(cls):
        _close_fixture()

    def test_05_basic_tree_traversal(self):
        """Tree inspection must return a structured result with nodes."""
        with uia_session() as session:
            result = inspect_tree(
                session, hwnd=self.fixture_hwnd, max_depth=4, max_nodes=100
            )
        self.assertTrue(result.get("ok"), result.get("error"))
        self.assertGreater(result["node_count"], 0)
        self.assertIn("root", result)
        self.assertTrue(result["untrusted"])

    def test_06_depth_limit_enforced(self):
        """Tree traversal must not exceed max_depth."""
        with uia_session() as session:
            result = inspect_tree(
                session, hwnd=self.fixture_hwnd, max_depth=1, max_nodes=200
            )
        self.assertTrue(result.get("ok"))

        def max_depth_in_tree(node: dict, current: int = 0) -> int:
            if node.get("truncated"):
                return current
            children = node.get("children", [])
            if not children:
                return current
            return max(max_depth_in_tree(c, current + 1) for c in children)

        actual_depth = max_depth_in_tree(result["root"])
        self.assertLessEqual(actual_depth, 1, f"Max depth exceeded: actual={actual_depth}")

    def test_07_node_limit_enforced(self):
        """Tree traversal must respect max_nodes cap (sentinel nodes not counted)."""
        with uia_session() as session:
            result = inspect_tree(
                session, hwnd=self.fixture_hwnd, max_depth=10, max_nodes=5
            )
        self.assertTrue(result.get("ok"))
        # node_count excludes truncation sentinels → must be ≤ max_nodes
        self.assertLessEqual(result["node_count"], 5, f"node_count={result['node_count']}")
        self.assertTrue(result.get("truncated"), "Large-depth traversal should truncate at 5 nodes")

    def test_08_timeout_early_termination(self):
        """Timeout mechanism must produce a truncated sentinel when deadline is past.

        We call _traverse_element directly with deadline=time.monotonic()-1.0
        (1 second in the past) to reliably trigger the timeout check without
        depending on machine speed or tree size.
        """
        import time
        from assistant.tools.ui.tree_inspector import _traverse_element
        from assistant.tools.ui.uia_client import get_element_from_hwnd

        with uia_session() as session:
            p_start = get_element_from_hwnd(session, self.fixture_hwnd)
            self.assertIsNotNone(p_start)
            # Deadline is 1 second in the past → first child traversal will timeout
            already_expired = time.monotonic() - 1.0
            root_node = _traverse_element(
                session=session,
                p_start=p_start,
                max_depth=5,
                max_nodes=500,
                deadline=already_expired,
            )
        # When deadline is already expired, the first or any node will be truncated
        self.assertTrue(
            _is_truncated(root_node),
            "Tree traversal must detect and report truncation when deadline is expired",
        )

    def test_09_render_tree_text(self):
        """render_tree_text must produce non-empty human-readable output."""
        with uia_session() as session:
            result = inspect_tree(
                session, hwnd=self.fixture_hwnd, max_depth=3, max_nodes=60
            )
        self.assertTrue(result.get("ok"))
        text = render_tree_text(result["root"])
        self.assertGreater(len(text), 0)
        self.assertIsInstance(text, str)

    def test_10_untrusted_tagging_on_all_nodes(self):
        """Every non-sentinel node must carry untrusted=True."""
        with uia_session() as session:
            result = inspect_tree(
                session, hwnd=self.fixture_hwnd, max_depth=3, max_nodes=50
            )
        self.assertTrue(result.get("ok"))

        def check_untrusted(node: dict) -> None:
            if node.get("truncated"):
                return
            self.assertTrue(
                node.get("untrusted"),
                f"Node missing untrusted flag: {node.get('name')}",
            )
            for child in node.get("children", []):
                check_untrusted(child)

        check_untrusted(result["root"])


class TestPasswordRedactionUnit(unittest.TestCase):
    """Structural unit tests for password field detection and redaction.

    Uses a fake tree dict instead of a live Tkinter fixture because Tkinter
    does not expose `IsPassword=True` through UIA for its Entry(show='*') widget.
    Tests verify that OUR code correctly handles `is_password=True` when UIA
    delivers it (which it does for real Win32 apps, WPF, UWP etc.).
    """

    def setUp(self):
        self.tree = _make_fake_tree()

    def test_11_password_field_detected_in_fake_tree(self):
        """Password node with is_password=True must be detectable in tree search."""
        def find_passwords(node: dict) -> list[dict]:
            if node.get("truncated"):
                return []
            hits = []
            if node.get("is_password"):
                hits.append(node)
            for child in node.get("children", []):
                hits.extend(find_passwords(child))
            return hits

        pws = find_passwords(self.tree)
        self.assertEqual(len(pws), 1)
        self.assertEqual(pws[0]["automation_id"], "password_field")

    def test_12_render_tree_text_redacts_password_name(self):
        """render_tree_text must show [PASSWORD_FIELD] for password nodes."""
        # Inject actual password text into the node name to simulate a leak
        for child in self.tree["children"]:
            if child.get("is_password"):
                child["name"] = "super_secret_text"  # Simulate name accidentally set

        text = render_tree_text(self.tree)
        self.assertIn("[PASSWORD_FIELD]", text)
        self.assertNotIn("super_secret_text", text,
                         "Credential text must not appear in rendered tree")

    def test_12b_find_controls_redacts_password_name(self):
        """find_controls must return [PASSWORD_FIELD] for name of password nodes."""
        matches = find_controls(
            self.tree,
            automation_id="password_field",
            limit=5,
        )
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertTrue(m["is_password"])
        self.assertEqual(m["name"], "[PASSWORD_FIELD]",
                         "find_controls must redact password field name")


class TestControlFinder(unittest.TestCase):
    """Tests for semantic control finder and confidence scoring."""

    @classmethod
    def setUpClass(cls):
        cls.tree = _make_fake_tree()

    def test_13_find_by_control_type_button(self):
        """Should find Button controls in fake tree."""
        matches = find_controls(self.tree, control_type="Button", limit=10)
        self.assertGreaterEqual(len(matches), 2, "Should find OK and Cancel buttons")
        for m in matches:
            self.assertEqual(m["control_type"], "Button")
            self.assertTrue(m["untrusted"])
            self.assertGreaterEqual(m["confidence"], 0.40)

    def test_14_find_by_name_ok_button(self):
        """Should find OK button by name (exact match → confidence ≥ 0.70)."""
        matches = find_controls(
            self.tree,
            name="OK",
            control_type="Button",
            limit=5,
        )
        self.assertGreater(len(matches), 0, "Should find OK button")
        best = matches[0]
        self.assertGreaterEqual(best["confidence"], 0.70,
                                "Exact name + ControlType should be ≥ 0.70")
        self.assertEqual(best["name"], "OK")

    def test_15_empty_criteria_returns_empty(self):
        """No criteria should return empty list, not an error."""
        matches = find_controls(self.tree)
        self.assertEqual(matches, [])

    def test_16_no_match_returns_empty(self):
        """Non-matching criteria should return empty list."""
        matches = find_controls(
            self.tree,
            automation_id="nonexistent_automation_id_xyz_12345",
            limit=5,
        )
        self.assertEqual(matches, [])

    def test_17_ambiguous_flag_on_partial_match(self):
        """Matches with confidence < 0.70 should be flagged as ambiguous."""
        # ControlType-only match gives 0.40 → ambiguous
        matches = find_controls(self.tree, control_type="Edit", limit=10)
        for m in matches:
            self.assertTrue(m["untrusted"])
            if m["confidence"] < 0.70:
                self.assertTrue(
                    m["ambiguous"],
                    f"Low-confidence match not flagged ambiguous: conf={m['confidence']}",
                )

    def test_18_control_type_aliases(self):
        """Control type aliases (btn, input, check) should be resolved."""
        self.assertEqual(_normalize_ct("btn"), "Button")
        self.assertEqual(_normalize_ct("input"), "Edit")
        self.assertEqual(_normalize_ct("check"), "CheckBox")
        self.assertEqual(_normalize_ct("textbox"), "Edit")

    def test_18b_automation_id_exact_match_high_confidence(self):
        """AutomationId exact match must yield confidence ≥ 0.50."""
        matches = find_controls(self.tree, automation_id="btn_ok", limit=5)
        self.assertGreater(len(matches), 0)
        self.assertGreaterEqual(matches[0]["confidence"], 0.50)

    def test_18c_results_sorted_by_confidence_desc(self):
        """Results must be sorted by confidence in descending order."""
        matches = find_controls(self.tree, control_type="Button", limit=10)
        for i in range(len(matches) - 1):
            self.assertGreaterEqual(
                matches[i]["confidence"], matches[i + 1]["confidence"],
                "Results not sorted by confidence descending",
            )


class TestToolRegistration(unittest.TestCase):
    """Tests for Phase 10A tool registration and policy evaluation."""

    def test_19_tools_registered(self):
        """ui.inspect_tree, ui.find_control, ui.get_control_info must be registered."""
        for tool_name in ["ui.inspect_tree", "ui.find_control", "ui.get_control_info"]:
            t = registry.get(tool_name)
            self.assertIsNotNone(t, f"Tool '{tool_name}' not registered")
            self.assertEqual(t.risk, Risk.OBSERVE)

    def test_20_policy_allows_l1_without_confirmation(self):
        """All Phase 10A tools must be L1 (allowed without confirmation)."""
        policy = PolicyEngine()
        for tool_name in ["ui.inspect_tree", "ui.find_control", "ui.get_control_info"]:
            t = registry.get(tool_name)
            decision = policy.evaluate(t, {})
            self.assertTrue(decision.allowed)
            self.assertFalse(decision.needs_confirmation)
            self.assertEqual(decision.risk, Risk.OBSERVE)


class TestToolExecution(unittest.TestCase):
    """Integration tests for the @tool-decorated functions via tool.run()."""

    @classmethod
    def setUpClass(cls):
        cls.fixture_hwnd = _launch_fixture_and_get_hwnd()

    @classmethod
    def tearDownClass(cls):
        _close_fixture()

    def test_21_inspect_tree_tool_run(self):
        """ui.inspect_tree tool must return ok=True and untrusted=True."""
        tool_def = registry.get("ui.inspect_tree")
        result = tool_def.run(hwnd=self.fixture_hwnd, max_depth=3, max_nodes=80)
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.untrusted)
        self.assertIn("<untrusted_ui_content>", result.summary)

    def test_22_find_control_tool_run(self):
        """ui.find_control must return controls and untrusted=True."""
        tool_def = registry.get("ui.find_control")
        # Search by ControlType=Pane which Tkinter definitely exposes
        result = tool_def.run(hwnd=self.fixture_hwnd, control_type="Pane")
        self.assertTrue(result.ok)
        self.assertTrue(result.untrusted)
        self.assertGreater(result.data.get("total", 0), 0,
                           "Should find at least one Pane in Tkinter window")

    def test_23_get_control_info_with_valid_path(self):
        """ui.get_control_info must return metadata for a valid path."""
        td_tree = registry.get("ui.inspect_tree")
        tr = td_tree.run(hwnd=self.fixture_hwnd, max_depth=3, max_nodes=80)
        self.assertTrue(tr.ok)
        root_path = tr.data.get("root", {}).get("path", "root")

        td_info = registry.get("ui.get_control_info")
        result = td_info.run(hwnd=self.fixture_hwnd, path=root_path)
        self.assertTrue(result.ok)
        self.assertTrue(result.untrusted)
        self.assertIn("<untrusted_ui_content>", result.summary)

    def test_24_get_control_info_invalid_path(self):
        """ui.get_control_info must return ok=False for an invalid path."""
        tool_def = registry.get("ui.get_control_info")
        result = tool_def.run(hwnd=self.fixture_hwnd, path="invalid/nonexistent/path")
        self.assertFalse(result.ok)

    def test_25_find_control_no_criteria_fails(self):
        """ui.find_control with no criteria must return an error."""
        tool_def = registry.get("ui.find_control")
        result = tool_def.run()
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)


if __name__ == "__main__":
    unittest.main()

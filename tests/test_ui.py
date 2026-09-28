"""Unit tests for Phase 5 UI components (ChatWindow, Tray, Hotkey, Reports, Confirmation)."""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from assistant.ui.reports import save_markdown_report, get_reports_dir
from assistant.ui.tray import create_tray_icon_image, TrayApplication
from assistant.ui.hotkey import GlobalHotkeyListener
from assistant.ui.chat_window import ChatWindow
from assistant.tools.base import ToolResult


class TestPhase5UI(unittest.TestCase):
    def test_save_markdown_report(self):
        reports_dir = get_reports_dir()
        self.assertTrue(reports_dir.is_dir())

        test_path = save_markdown_report(
            title="Uji Diagnosa Unit Test",
            query="cek sistem",
            response="Sistem beroperasi normal.",
            findings="CPU: 15%\nRAM: 45%",
            rule_findings=["Aturan 1: OK", "Aturan 2: OK"],
            playbook_name="test_playbook",
        )
        self.assertTrue(test_path.is_file())
        content = test_path.read_text(encoding="utf-8")
        self.assertIn("# Laporan Diagnosa: Uji Diagnosa Unit Test", content)
        self.assertIn("Sistem beroperasi normal.", content)
        self.assertIn("CPU: 15%", content)
        self.assertIn("Aturan 1: OK", content)
        self.assertIn("test_playbook", content)

        # Cleanup test file
        try:
            test_path.unlink()
        except Exception:
            pass

    def test_tray_icon_image_creation(self):
        img = create_tray_icon_image((64, 64))
        self.assertIsNotNone(img)
        self.assertEqual(img.size, (64, 64))
        self.assertEqual(img.mode, "RGBA")

    def test_hotkey_listener_initialization(self):
        called = [False]
        def _cb():
            called[0] = True

        listener = GlobalHotkeyListener(callback=_cb, vk_key=ord("J"), hotkey_id=999)
        self.assertEqual(listener.vk_key, ord("J"))
        self.assertEqual(listener.hotkey_id, 999)
        self.assertFalse(listener._running)

    def test_chat_window_lifecycle(self):
        mock_orch = MagicMock()
        mock_orch.handle_request.return_value = {
            "route": "fast",
            "intent": "test_intent",
            "tool": "launch.open_url",
            "response": "Membuka URL...",
            "ok": True,
        }

        # Create window with mocked orchestrator
        window = ChatWindow(orch=mock_orch)
        self.assertIsNotNone(window.root)

        # Test message appending
        window.append_message("Anda", "buka youtube", tag="user")
        window.append_message("Jarvis", "Siap!", tag="jarvis")

        # Test status updating
        window.update_status("Uji status aktif", is_working=True)
        self.assertTrue(window._is_working)

        window.update_status("Siap", is_working=False)
        self.assertFalse(window._is_working)

        # Test hide / show / toggle
        window.hide()
        self.assertFalse(window.root.winfo_viewable())

        window.show()
        self.assertTrue(window.root.winfo_viewable())

        window.toggle()
        self.assertFalse(window.root.winfo_viewable())

        # Test save report with result populated
        window.last_result = {
            "playbook": "test_pb",
            "response": "Hasil diagnosa.",
            "findings": "Detail telemetri.",
            "rule_findings": ["Aturan A"],
        }
        window.last_query = "cek diagnosa"

        with patch("tkinter.messagebox.showinfo") as mock_info:
            window.save_current_report()
            self.assertTrue(mock_info.called)

        # Cleanly destroy Tkinter root
        window.destroy()

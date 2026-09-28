"""Unit tests for Phase 7: Game & App Investigation, File Inspection & Backup (Section 7.2)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from assistant.tools.registry import registry
from assistant.tools.files.inspect import (
    calculate_shannon_entropy,
    detect_file_type,
    inspect_file_path,
)


class TestGamesAndApps(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="jarvis_test_p7_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_shannon_entropy_calculation(self):
        # 1. Zero/Identical bytes -> entropy 0.0
        zero_entropy = calculate_shannon_entropy(b"\x00" * 500)
        self.assertEqual(zero_entropy, 0.0)

        # 2. Typical plaintext -> entropy between 3.0 and 5.5
        text_data = b"This is a standard configuration file with key=value pairs and typical English words."
        text_entropy = calculate_shannon_entropy(text_data)
        self.assertTrue(3.0 <= text_entropy <= 5.5, f"Text entropy was {text_entropy}")

        # 3. High entropy / pseudorandom bytes -> entropy > 7.2
        random_bytes = os.urandom(1024)
        rand_entropy = calculate_shannon_entropy(random_bytes)
        self.assertTrue(rand_entropy >= 7.2, f"Random entropy was {rand_entropy}")

    def test_detect_file_type(self):
        # JSON
        json_type = detect_file_type(b'{"key": "value"}', '{"key": "value"}')
        self.assertEqual(json_type["format"], "JSON")

        # INI
        ini_content = "[Graphics]\nResolution=1920x1080\nFullscreen=true"
        ini_type = detect_file_type(b"[Graphics]", ini_content)
        self.assertEqual(ini_type["format"], "INI / Configuration")

        # SQLite
        sqlite_header = b"SQLite format 3\x00\x10\x00"
        sqlite_type = detect_file_type(sqlite_header, "")
        self.assertEqual(sqlite_type["format"], "SQLite Database")

        # Binary null bytes
        bin_header = b"\x01\x00\x03\x04\x00\x00"
        bin_type = detect_file_type(bin_header, "")
        self.assertIn("Binary", bin_type["format"])

    def test_files_inspect_tool(self):
        sample_file = self.test_dir / "settings.ini"
        sample_file.write_text("[Audio]\nVolume=80\nMute=false\n", encoding="utf-8")

        res = registry.execute("files.inspect", file_path=str(sample_file))
        self.assertTrue(res.ok)
        self.assertEqual(res.data["filename"], "settings.ini")
        self.assertEqual(res.data["detected_format"], "INI / Configuration")
        self.assertTrue(res.data["is_readable_text"])
        self.assertFalse(res.data["is_high_entropy"])

    def test_files_read_text_tool(self):
        sample_file = self.test_dir / "readme.txt"
        sample_file.write_text("Baris 1: Petunjuk konfigurasi\nBaris 2: Nilai parameter\n", encoding="utf-8")

        res = registry.execute("files.read_text", file_path=str(sample_file), max_lines=10)
        self.assertTrue(res.ok)
        self.assertEqual(res.data["lines_count"], 2)
        self.assertIn("Petunjuk konfigurasi", res.data["content"])

    def test_files_backup_tool(self):
        sample_file = self.test_dir / "user_save.dat"
        sample_file.write_bytes(b"GAME_SAVE_DATA_LEVEL_99_COINS_50000")

        res = registry.execute("files.backup", file_path=str(sample_file), subfolder="test_game")
        self.assertTrue(res.ok)
        self.assertIn("backup_path", res.data)
        self.assertIn("rollback_command", res.data)

        backup_file = Path(res.data["backup_path"])
        self.assertTrue(backup_file.is_file())
        self.assertEqual(backup_file.read_bytes(), sample_file.read_bytes())

        # Cleanup backup test file
        try:
            backup_file.unlink()
            manifest_file = backup_file.parent / f"{backup_file.stem}_manifest.json"
            if manifest_file.is_file():
                manifest_file.unlink()
        except Exception:
            pass

    def test_apps_resolve_tool(self):
        res = registry.execute("apps.resolve", name="notepad")
        self.assertTrue(res.ok)
        self.assertTrue(res.data["count"] > 0)
        self.assertIn("notepad.exe", res.data["primary_path"].lower())

    def test_apps_inspect_tool(self):
        notepad_path = os.path.expandvars(r"%SystemRoot%\System32\notepad.exe")
        res = registry.execute("apps.inspect", app_path=notepad_path)
        self.assertTrue(res.ok)
        meta = res.data["metadata"]
        self.assertEqual(meta["FileName"].lower(), "notepad.exe")
        self.assertTrue(meta["IsOSBinary"])
        self.assertIn("Microsoft", meta["CompanyName"])

    def test_apps_get_cli_help_tool(self):
        res = registry.execute("apps.get_cli_help", app_path="cmd.exe", flag="/?")
        self.assertTrue(res.ok)
        self.assertIn("CMD", res.data["output"])

    def test_games_tools_smoke(self):
        # 1. list_installed
        res_list = registry.execute("games.list_installed")
        self.assertTrue(res_list.ok)
        self.assertIsInstance(res_list.data["games"], list)

        # 2. find_save_and_config
        res_save = registry.execute("games.find_save_and_config", game_name="TestGameDemo")
        self.assertTrue(res_save.ok)
        self.assertEqual(res_save.data["game_name"], "TestGameDemo")

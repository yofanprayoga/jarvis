"""Unit tests for Phase 8: Controlled File Modifications (L3 Safe Edits, Diffs, Backups, and Rollback)."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from assistant.core.audit import AuditLogger
from assistant.core.orchestrator import Orchestrator
from assistant.core.policy import PolicyEngine
from assistant.tools.base import Risk
from assistant.tools.files.edit import (
    apply_file_edit,
    generate_unified_diff,
    propose_file_edit,
    restore_file_backup,
)
from assistant.tools.files.file_tools import (
    apply_edit_tool,
    backup_file_tool,
    propose_edit_tool,
    restore_backup_tool,
    FileApplyEditInput,
    FileBackupInput,
    FileProposeEditInput,
    FileRestoreBackupInput,
)
from assistant.tools.registry import registry


class TestFileModifications(unittest.TestCase):
    """Test suite for Phase 8 controlled file modification tools and security guarantees."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="jarvis_test_mod_")
        self.sample_file = Path(self.test_dir) / "game_settings.ini"
        self.initial_content = (
            "[Graphics]\n"
            "resolution = 1920x1080\n"
            "fullscreen = true\n"
            "fps_limit = 60\n"
            "vsync = 1\n"
        )
        self.sample_file.write_bytes(self.initial_content.encode("utf-8"))
        self.initial_hash = hashlib.sha256(self.sample_file.read_bytes()).hexdigest()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_generate_unified_diff(self):
        original = "line 1\nline 2\nline 3\n"
        modified = "line 1\nline 2 modified\nline 3\nline 4\n"
        diff = generate_unified_diff(original, modified, "test.txt")
        self.assertIn("-line 2", diff)
        self.assertIn("+line 2 modified", diff)
        self.assertIn("+line 4", diff)

    def test_propose_file_edit_does_not_modify_file(self):
        new_content = (
            "[Graphics]\n"
            "resolution = 1920x1080\n"
            "fullscreen = true\n"
            "fps_limit = 144\n"
            "vsync = 0\n"
        )
        proposal = propose_file_edit(
            file_path=str(self.sample_file),
            new_content=new_content,
            explanation="Tingkatkan FPS limit dan nonaktifkan VSync untuk mengurangi input lag.",
        )

        self.assertTrue(proposal["has_changes"])
        self.assertEqual(proposal["sha256_before"], self.initial_hash)
        self.assertNotEqual(proposal["sha256_after"], self.initial_hash)
        self.assertIn("-fps_limit = 60", proposal["diff"])
        self.assertIn("+fps_limit = 144", proposal["diff"])
        self.assertEqual(proposal["stats"]["additions"], 2)
        self.assertEqual(proposal["stats"]["deletions"], 2)

        # CRITICAL ACCEPTANCE CRITERIA: File must remain completely unchanged on disk!
        current_disk_content = self.sample_file.read_text(encoding="utf-8")
        self.assertEqual(current_disk_content, self.initial_content)
        self.assertEqual(hashlib.sha256(current_disk_content.encode("utf-8")).hexdigest(), self.initial_hash)

    def test_propose_file_edit_binary_rejected(self):
        binary_file = Path(self.test_dir) / "save.dat"
        # Write explicit binary bytes with null bytes and invalid UTF-8
        binary_file.write_bytes(b"\x00\xFF\xFE\x00\x1F\x8B" + os.urandom(1024))

        with self.assertRaises(ValueError) as ctx:
            propose_file_edit(str(binary_file), "some text", "coba edit")
        self.assertTrue(len(str(ctx.exception)) > 0)

    def test_apply_file_edit_and_verification(self):
        new_content = (
            "[Graphics]\n"
            "resolution = 1920x1080\n"
            "fullscreen = true\n"
            "fps_limit = 144\n"
            "vsync = 0\n"
        )
        result = apply_file_edit(
            file_path=str(self.sample_file),
            new_content=new_content,
            expected_hash=self.initial_hash,
            reason="Update fps limit",
            backup_subfolder="test_pre_edit",
        )

        self.assertEqual(result["status"], "APPLIED_AND_VERIFIED")
        self.assertEqual(result["sha256_before"], self.initial_hash)
        expected_new_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        self.assertEqual(result["sha256_after"], expected_new_hash)

        # Verify disk content is updated and verified
        written_content = self.sample_file.read_text(encoding="utf-8")
        self.assertEqual(written_content, new_content)

        # Verify backup was created
        backup_path = Path(result["backup_path"])
        self.assertTrue(backup_path.is_file())
        self.assertEqual(hashlib.sha256(backup_path.read_bytes()).hexdigest(), self.initial_hash)

    def test_apply_file_edit_concurrency_mismatch_rejected(self):
        new_content = "modified content\n"
        wrong_hash = "0" * 64

        with self.assertRaises(ValueError) as ctx:
            apply_file_edit(
                file_path=str(self.sample_file),
                new_content=new_content,
                expected_hash=wrong_hash,
                reason="Race condition test",
            )
        self.assertIn("file telah berubah sejak proposal dibuat", str(ctx.exception).lower())
        # File must remain untouched
        self.assertEqual(self.sample_file.read_text(encoding="utf-8"), self.initial_content)

    def test_restore_file_backup_byte_identical(self):
        # 1. Back up original
        backup_res = backup_file_tool.run(file_path=str(self.sample_file), subfolder="test_restore")
        self.assertTrue(backup_res.ok)
        backup_path = backup_res.data["backup_path"]

        # 2. Modify original file
        modified_content = "[Modified]\nall = gone\n"
        self.sample_file.write_text(modified_content, encoding="utf-8")
        self.assertNotEqual(hashlib.sha256(self.sample_file.read_bytes()).hexdigest(), self.initial_hash)

        # 3. Restore backup
        restore_info = restore_file_backup(backup_path=backup_path, original_path=str(self.sample_file))
        self.assertTrue(restore_info["byte_identical"])
        self.assertEqual(restore_info["sha256"], self.initial_hash)

        # 4. Verify disk byte-identical match
        restored_disk_bytes = self.sample_file.read_bytes()
        self.assertEqual(hashlib.sha256(restored_disk_bytes).hexdigest(), self.initial_hash)
        self.assertEqual(restored_disk_bytes.decode("utf-8"), self.initial_content)

    def test_policy_blocks_windows_system_modification(self):
        policy = PolicyEngine()
        tool_def = registry.get("files.apply_edit")
        self.assertIsNotNone(tool_def)

        # Attempt to target C:\Windows\System32
        args = {"file_path": r"C:\Windows\System32\drivers\etc\hosts", "new_content": "127.0.0.1 malicious"}
        decision = policy.evaluate(tool_def, args)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk, Risk.FORBIDDEN)
        self.assertIn("protected windows system directories", decision.reason.lower())

    def test_orchestrator_l3_confirmation_flow(self):
        audit_db_path = Path(self.test_dir) / "test_audit.db"
        audit = AuditLogger(db_path=audit_db_path)

        # Case 1: User Rejects L3 Confirmation
        orch_reject = Orchestrator(
            audit=audit,
            confirm_handler=lambda name, tool_def, args: False,
        )

        res_reject = orch_reject.run_tool(
            "files.apply_edit",
            {
                "file_path": str(self.sample_file),
                "new_content": "rejected changes\n",
                "reason": "Test rejection",
            },
        )
        self.assertFalse(res_reject.ok)
        self.assertIn("dibatalkan oleh pengguna", res_reject.error)
        self.assertEqual(self.sample_file.read_text(encoding="utf-8"), self.initial_content)

        # Case 2: User Confirms L3 Action
        orch_accept = Orchestrator(
            audit=audit,
            confirm_handler=lambda name, tool_def, args: True,
        )

        res_accept = orch_accept.run_tool(
            "files.apply_edit",
            {
                "file_path": str(self.sample_file),
                "new_content": "approved changes\n",
                "reason": "Test acceptance",
            },
        )
        self.assertTrue(res_accept.ok)
        self.assertEqual(self.sample_file.read_text(encoding="utf-8"), "approved changes\n")

    def test_registered_tools_execution(self):
        # Test propose_edit_tool via registry
        p_res = registry.execute(
            "files.propose_edit",
            file_path=str(self.sample_file),
            new_content="new test content\n",
            explanation="Registry execution test",
        )
        self.assertTrue(p_res.ok)
        self.assertIn("Proposal Perubahan File", p_res.summary)

        # Verify risk level is CONFIRM for apply_edit and restore_backup
        apply_def = registry.get("files.apply_edit")
        restore_def = registry.get("files.restore_backup")
        self.assertEqual(apply_def.risk, Risk.CONFIRM)
        self.assertEqual(restore_def.risk, Risk.CONFIRM)


if __name__ == "__main__":
    unittest.main()

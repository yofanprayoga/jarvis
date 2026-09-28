"""File inspection, safe text reading, and timestamped backup tools (Section 7.2 Phase 7)."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

from assistant.tools.base import Risk, ToolResult, tool
from assistant.tools.files.inspect import inspect_file_path


class FileInspectInput(BaseModel):
    file_path: str = Field(description="Full path to the file to inspect")


class FileReadTextInput(BaseModel):
    file_path: str = Field(description="Full path to the text file to read")
    max_lines: int = Field(default=150, ge=1, le=500, description="Max lines to read")
    max_chars: int = Field(default=8000, ge=500, le=25000, description="Max characters to return")


class FileBackupInput(BaseModel):
    file_path: str = Field(description="Path to the file to back up")
    subfolder: Optional[str] = Field(default=None, description="Optional subfolder name in data/backups/ (e.g. game name)")


@tool(
    name="files.inspect",
    risk=Risk.OBSERVE,
    description="Inspect a file: size, SHA-256 hash, format type detection, and Shannon entropy (encryption hint).",
    input_model=FileInspectInput,
    timeout_s=10,
    requires_elevation=False,
)
def inspect_file_tool(args: FileInspectInput) -> ToolResult:
    info = inspect_file_path(args.file_path)
    if not info.get("exists"):
        return ToolResult.fail(f"File tidak ditemukan: '{args.file_path}'")

    summary = (
        f"Inspeksi File: {info['filename']}\n"
        f"- Ukuran: {info['size_str']} ({info['size_bytes']} bytes)\n"
        f"- Tipe Format: {info['detected_format']} (Kategori: {info['category']})\n"
        f"- Shannon Entropy: {info['shannon_entropy']} / 8.0 -> {info['encryption_hint']}\n"
        f"- SHA-256: {info['sha256'][:16]}...\n"
        f"- Dapat Dibaca Teks: {'Ya' if info['is_readable_text'] else 'Tidak'}"
    )

    return ToolResult.success(data=info, summary=summary)


@tool(
    name="files.read_text",
    risk=Risk.OBSERVE,
    description="Read text configuration or readable save file. Restricted to allowlisted roots and size-limited. Output is untrusted data.",
    input_model=FileReadTextInput,
    timeout_s=10,
    requires_elevation=False,
)
def read_text_tool(args: FileReadTextInput) -> ToolResult:
    p = Path(args.file_path)
    if not p.is_file():
        return ToolResult.fail(f"File tidak ditemukan: '{args.file_path}'")

    # Inspect first to check if binary
    info = inspect_file_path(p)
    if not info.get("is_readable_text") and info.get("category") == "binary":
        return ToolResult.fail(
            f"File '{p.name}' terdeteksi sebagai file biner ({info.get('detected_format')}), tidak dapat dibaca sebagai teks biasa."
        )

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return ToolResult.fail(f"Gagal membaca file: {e}")

    lines = content.splitlines()[:args.max_lines]
    truncated_text = "\n".join(lines)
    if len(truncated_text) > args.max_chars:
        truncated_text = truncated_text[:args.max_chars] + "\n... [teks terpotong melebihi batas]"

    summary = (
        f"Isi File '{p.name}' ({len(lines)} baris dibaca, {len(truncated_text)} karakter):\n"
        f"```text\n{truncated_text}\n```"
    )

    data = {
        "path": str(p.resolve()),
        "lines_count": len(lines),
        "total_chars": len(content),
        "content": truncated_text,
        "untrusted": True,
    }

    return ToolResult.success(data=data, summary=summary)


@tool(
    name="files.backup",
    risk=Risk.LOW_ACTION,
    description="Create a safe, timestamped backup copy of a file with SHA-256 manifest in data/backups/.",
    input_model=FileBackupInput,
    timeout_s=15,
    requires_elevation=False,
)
def backup_file_tool(args: FileBackupInput) -> ToolResult:
    source_path = Path(args.file_path)
    if not source_path.is_file():
        return ToolResult.fail(f"File sumber tidak ditemukan: '{args.file_path}'")

    # Hash original file
    h_orig = hashlib.sha256(source_path.read_bytes()).hexdigest()

    # Destination directory
    sub = args.subfolder or source_path.parent.name
    safe_sub = "".join(c if c.isalnum() else "_" for c in sub).strip("_") or "general"
    backup_dir = Path("data/backups") / safe_sub
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{timestamp_str}_{source_path.name}"
    backup_dest = backup_dir / backup_filename

    # Copy byte-for-byte
    shutil.copy2(source_path, backup_dest)

    # Hash backup file to verify identical copy
    h_backup = hashlib.sha256(backup_dest.read_bytes()).hexdigest()
    if h_orig != h_backup:
        return ToolResult.fail("Verifikasi integritas backup gagal: hash tidak cocok.")

    # Write backup manifest
    manifest_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "original_path": str(source_path.resolve()),
        "backup_path": str(backup_dest.resolve()),
        "sha256": h_orig,
        "size_bytes": backup_dest.stat().st_size,
        "rollback_command": f'copy /Y "{backup_dest.resolve()}" "{source_path.resolve()}"',
    }
    manifest_file = backup_dir / f"{timestamp_str}_{source_path.stem}_manifest.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    summary = (
        f"Backup Berhasil Dibuat:\n"
        f"- Sumber: {source_path.name}\n"
        f"- Tujuan: {backup_dest}\n"
        f"- SHA-256: {h_orig[:16]}... (Terverifikasi identik)\n"
        f"- Perintah Rollback: {manifest_data['rollback_command']}"
    )

    return ToolResult.success(data=manifest_data, summary=summary)


class FileProposeEditInput(BaseModel):
    file_path: str = Field(description="Full path to the text file to edit")
    new_content: str = Field(description="Proposed new content of the file")
    explanation: str = Field(default="", description="Explanation of what changes are being proposed and why")


class FileApplyEditInput(BaseModel):
    file_path: str = Field(description="Full path to the text file to edit")
    new_content: str = Field(description="Approved new content to write to the file")
    expected_hash: Optional[str] = Field(default=None, description="Expected SHA-256 before edit to guard against race conditions")
    reason: str = Field(default="", description="Reason for applying the edit")


class FileRestoreBackupInput(BaseModel):
    backup_path: Optional[str] = Field(default=None, description="Path to the backup file to restore from")
    original_path: Optional[str] = Field(default=None, description="Original file path to restore (if backup_path not specified, restores latest backup)")
    manifest_path: Optional[str] = Field(default=None, description="Path to the backup manifest json file")


@tool(
    name="files.propose_edit",
    risk=Risk.OBSERVE,
    description="Propose an edit to a text configuration or settings file. Generates a unified diff and preview without writing any changes to disk.",
    input_model=FileProposeEditInput,
    timeout_s=10,
    requires_elevation=False,
)
def propose_edit_tool(args: FileProposeEditInput) -> ToolResult:
    from assistant.tools.files.edit import propose_file_edit
    try:
        proposal = propose_file_edit(
            file_path=args.file_path,
            new_content=args.new_content,
            explanation=args.explanation,
        )
    except Exception as e:
        return ToolResult.fail(f"Gagal membuat proposal edit: {e}")

    diff_preview = proposal["diff"] if proposal["diff"] else "[Tidak ada perubahan konten terdeteksi]"
    summary = (
        f"Proposal Perubahan File: '{proposal['filename']}' ({proposal['proposal_id']})\n"
        f"- Alasan: {proposal['explanation']}\n"
        f"- Statistik: +{proposal['stats']['additions']} baris, -{proposal['stats']['deletions']} baris\n"
        f"- SHA-256 Sebelum: {proposal['sha256_before'][:16]}...\n"
        f"- SHA-256 Sesudah: {proposal['sha256_after'][:16]}...\n"
        f"- Diff Preview:\n```diff\n{diff_preview}\n```"
    )

    return ToolResult.success(data=proposal, summary=summary)


@tool(
    name="files.apply_edit",
    risk=Risk.CONFIRM,
    description="Apply an approved edit to a text configuration file. Requires existing file, automatically creates an intact backup first, atomically writes changes, and verifies hash. (L3 - Requires User Confirmation)",
    input_model=FileApplyEditInput,
    timeout_s=15,
    requires_elevation=False,
)
def apply_edit_tool(args: FileApplyEditInput) -> ToolResult:
    from assistant.tools.files.edit import apply_file_edit
    try:
        result = apply_file_edit(
            file_path=args.file_path,
            new_content=args.new_content,
            expected_hash=args.expected_hash,
            reason=args.reason,
        )
    except Exception as e:
        return ToolResult.fail(f"Gagal menerapkan edit: {e}")

    summary = (
        f"Perubahan File Berhasil Diterapkan & Diverifikasi:\n"
        f"- Target: {result['filename']}\n"
        f"- Backup Tersimpan: {result['backup_path']}\n"
        f"- SHA-256 Sebelum: {result['sha256_before'][:16]}...\n"
        f"- SHA-256 Sesudah: {result['sha256_after'][:16]}... (Terverifikasi)\n"
        f"- Perintah Rollback: {result['rollback_command']}"
    )

    return ToolResult.success(data=result, summary=summary)


@tool(
    name="files.restore_backup",
    risk=Risk.CONFIRM,
    description="Restore a file from a verified backup in data/backups/. Restores byte-for-byte and verifies SHA-256 match. (L3 - Requires User Confirmation)",
    input_model=FileRestoreBackupInput,
    timeout_s=15,
    requires_elevation=False,
)
def restore_backup_tool(args: FileRestoreBackupInput) -> ToolResult:
    from assistant.tools.files.edit import restore_file_backup
    try:
        result = restore_file_backup(
            backup_path=args.backup_path,
            original_path=args.original_path,
            manifest_path=args.manifest_path,
        )
    except Exception as e:
        return ToolResult.fail(f"Gagal memulihkan file dari backup: {e}")

    summary = (
        f"File Berhasil Dipulihkan dari Backup:\n"
        f"- File Target: {result['restored_path']}\n"
        f"- Sumber Backup: {result['backup_path']}\n"
        f"- SHA-256: {result['sha256'][:16]}... (Byte-Identical Terverifikasi)\n"
        f"- Waktu Pemulihan: {result['timestamp']}"
    )

    return ToolResult.success(data=result, summary=summary)


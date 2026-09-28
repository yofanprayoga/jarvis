"""Text configuration file modification, diff generation, atomic editing, and backup restoration (Section 7.2 Phase 8)."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from assistant.tools.files.inspect import inspect_file_path


def compute_sha256(content_bytes: bytes) -> str:
    """Compute SHA-256 hexadecimal hash of bytes."""
    return hashlib.sha256(content_bytes).hexdigest()


def generate_unified_diff(original_text: str, new_text: str, filename: str = "file") -> str:
    """Generate a clean unified diff between original and proposed content."""
    orig_lines = original_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines,
        new_lines,
        fromfile=f"a/{filename} (sebelum)",
        tofile=f"b/{filename} (sesudah)",
        lineterm="",
    )
    return "\n".join(diff)


def count_diff_stats(diff_text: str) -> dict[str, int]:
    """Count additions and deletions in unified diff."""
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {"additions": additions, "deletions": deletions}


def propose_file_edit(
    file_path: str | Path,
    new_content: str,
    explanation: str = "",
) -> dict[str, Any]:
    """Propose an edit to a text configuration or settings file.
    
    Validates that target exists and is text, calculates unified diff, before/after SHA-256 hashes,
    and returns proposal metadata without modifying any file on disk.
    """
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"File target tidak ditemukan: '{p}'")

    # Safety: Verify it's a readable text file (not binary)
    info = inspect_file_path(p)
    if not info.get("is_readable_text") or info.get("category") != "text":
        raise ValueError(
            f"File '{p.name}' terdeteksi sebagai {info.get('detected_format', 'bukan teks')} "
            f"(Kategori: {info.get('category')}). "
            f"Modifikasi hanya diizinkan untuk file konfigurasi berbasis teks."
        )

    # Size safety limit (2 MB max for controlled text edits)
    if p.stat().st_size > 2 * 1024 * 1024:
        raise ValueError(f"Ukuran file ({info.get('size_str')}) melebihi batas aman untuk modifikasi teks (2 MB).")

    try:
        orig_content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise IOError(f"Gagal membaca isi file: {e}")

    orig_bytes = orig_content.encode("utf-8")
    new_bytes = new_content.encode("utf-8")

    sha256_before = compute_sha256(orig_bytes)
    sha256_after = compute_sha256(new_bytes)

    diff = generate_unified_diff(orig_content, new_content, filename=p.name)
    stats = count_diff_stats(diff)

    proposal_id = f"prop_{sha256_before[:8]}_{int(time.time())}"

    return {
        "proposal_id": proposal_id,
        "file_path": str(p),
        "filename": p.name,
        "sha256_before": sha256_before,
        "sha256_after": sha256_after,
        "diff": diff,
        "explanation": explanation or "Perubahan konfigurasi teks.",
        "stats": stats,
        "lines_count_new": len(new_content.splitlines()),
        "has_changes": sha256_before != sha256_after,
    }


def apply_file_edit(
    file_path: str | Path,
    new_content: str,
    expected_hash: Optional[str] = None,
    reason: str = "",
    backup_subfolder: str = "pre_edit",
) -> dict[str, Any]:
    """Apply an approved edit to a text configuration file.
    
    Guarantees:
    1. Pre-edit backup is created and hash-verified before writing.
    2. Atomic write using temporary file and atomic replace.
    3. Post-write SHA-256 verification. If verification fails, automatic rollback is triggered.
    """
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"File target tidak ditemukan: '{p}'")

    # Safety: Verify it's a readable text file
    info = inspect_file_path(p)
    if not info.get("is_readable_text") or info.get("category") != "text":
        raise ValueError(
            f"File '{p.name}' terdeteksi sebagai {info.get('detected_format', 'bukan teks')} "
            f"(Kategori: {info.get('category')}). "
            f"Modifikasi hanya diizinkan untuk file teks."
        )

    orig_bytes = p.read_bytes()
    current_hash = compute_sha256(orig_bytes)

    # Concurrency / Stale proposal check
    if expected_hash and current_hash.lower() != expected_hash.lower():
        raise ValueError(
            f"File telah berubah sejak proposal dibuat!\n"
            f"Hash yang diharapkan: {expected_hash[:16]}...\n"
            f"Hash saat ini: {current_hash[:16]}..."
        )

    # Step 1: Create intact backup before touching the file
    from assistant.tools.files.file_tools import backup_file_tool
    backup_res = backup_file_tool.run(file_path=str(p), subfolder=backup_subfolder)
    if not backup_res.ok or not backup_res.data:
        raise RuntimeError(f"Gagal membuat backup pra-edit: {backup_res.error}. Modifikasi dibatalkan.")

    backup_info = backup_res.data
    backup_path = Path(backup_info["backup_path"])

    # Verify backup integrity matches current file
    if compute_sha256(backup_path.read_bytes()) != current_hash:
        raise RuntimeError("Integritas backup tidak cocok dengan file saat ini. Modifikasi dibatalkan.")

    # Step 2: Atomic Write
    new_bytes = new_content.encode("utf-8")
    expected_new_hash = compute_sha256(new_bytes)

    temp_file = p.parent / f".jarvis_tmp_{uuid.uuid4().hex[:8]}_{p.name}"
    try:
        with open(temp_file, "wb") as f:
            f.write(new_bytes)
            f.flush()
            os.fsync(f.fileno())

        # Atomically replace target
        os.replace(temp_file, p)
    except Exception as write_err:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass
        raise IOError(f"Gagal menulis file: {write_err}")

    # Step 3: Verify Result
    try:
        written_bytes = p.read_bytes()
        written_hash = compute_sha256(written_bytes)
        if written_hash != expected_new_hash:
            # AUTO-ROLLBACK!
            shutil.copy2(backup_path, p)
            raise RuntimeError(
                f"Verifikasi integritas penulisan gagal: hash tidak cocok. "
                f"File telah otomatis dikembalikan (rollback) ke backup: {backup_path}"
            )
    except Exception as verify_err:
        # Emergency rollback if anything goes wrong during verification
        try:
            shutil.copy2(backup_path, p)
        except Exception:
            pass
        raise RuntimeError(f"Gagal verifikasi hasil edit: {verify_err}")

    return {
        "file_path": str(p),
        "filename": p.name,
        "backup_path": str(backup_path),
        "sha256_before": current_hash,
        "sha256_after": expected_new_hash,
        "rollback_command": backup_info.get("rollback_command", f'copy /Y "{backup_path}" "{p}"'),
        "reason": reason,
        "status": "APPLIED_AND_VERIFIED",
    }


def restore_file_backup(
    backup_path: Optional[str | Path] = None,
    original_path: Optional[str | Path] = None,
    manifest_path: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Restore a file from a verified backup in data/backups/.
    
    Guarantees:
    1. Backup file exists and its hash is verified against manifest.
    2. Restores byte-for-byte to original target path.
    3. Post-restore SHA-256 verification confirms byte-identical restoration.
    """
    backup_p: Optional[Path] = Path(backup_path).resolve() if backup_path else None
    target_p: Optional[Path] = Path(original_path).resolve() if original_path else None
    manifest_p: Optional[Path] = Path(manifest_path).resolve() if manifest_path else None

    # If manifest given, read it
    manifest_data: dict[str, Any] = {}
    if manifest_p and manifest_p.is_file():
        try:
            manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"Gagal membaca file manifest: {e}")
        if not backup_p and "backup_path" in manifest_data:
            backup_p = Path(manifest_data["backup_path"]).resolve()
        if not target_p and "original_path" in manifest_data:
            target_p = Path(manifest_data["original_path"]).resolve()

    # If no backup_path but original_path is given, search data/backups/ for latest matching manifest
    if not backup_p and target_p:
        backups_root = Path("data/backups")
        candidate_manifests = sorted(backups_root.glob(f"**/*_{target_p.stem}_manifest.json"), reverse=True)
        for cand in candidate_manifests:
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                if Path(data.get("original_path", "")).resolve() == target_p:
                    manifest_data = data
                    manifest_p = cand
                    backup_p = Path(data["backup_path"]).resolve()
                    break
            except Exception:
                continue

    if not backup_p or not backup_p.is_file():
        raise FileNotFoundError(f"File backup tidak ditemukan atau belum ditentukan.")

    if not target_p:
        # Try finding manifest alongside backup file
        potential_manifest = backup_p.parent / f"{backup_p.stem}_manifest.json"
        if potential_manifest.is_file():
            try:
                manifest_data = json.loads(potential_manifest.read_text(encoding="utf-8"))
                target_p = Path(manifest_data.get("original_path", "")).resolve()
            except Exception:
                pass

    if not target_p:
        raise ValueError("Lokasi file target asli (original_path) tidak dapat ditentukan.")

    # Hash backup file
    backup_bytes = backup_p.read_bytes()
    backup_hash = compute_sha256(backup_bytes)

    # If manifest contains hash, verify backup integrity
    expected_original_hash = manifest_data.get("sha256")
    if expected_original_hash and expected_original_hash.lower() != backup_hash.lower():
        raise RuntimeError(
            f"Verifikasi backup gagal: Hash file backup tidak cocok dengan catatan manifest!\n"
            f"Backup: {backup_hash[:16]}... vs Manifest: {expected_original_hash[:16]}..."
        )

    # Atomic restore to target
    temp_restore = target_p.parent / f".jarvis_restore_{uuid.uuid4().hex[:8]}_{target_p.name}"
    try:
        shutil.copy2(backup_p, temp_restore)
        os.replace(temp_restore, target_p)
    except Exception as e:
        if temp_restore.exists():
            try:
                temp_restore.unlink()
            except Exception:
                pass
        raise IOError(f"Gagal memulihkan file dari backup: {e}")

    # Post-restore verification: Must be byte-identical
    restored_bytes = target_p.read_bytes()
    restored_hash = compute_sha256(restored_bytes)
    if restored_hash != backup_hash:
        raise RuntimeError("Verifikasi pemulihan gagal: file target yang dipulihkan tidak identik dengan backup!")

    return {
        "restored_path": str(target_p),
        "backup_path": str(backup_p),
        "sha256": restored_hash,
        "byte_identical": True,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "RESTORED_AND_VERIFIED",
    }

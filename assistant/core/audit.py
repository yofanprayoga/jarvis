"""SQLite Audit Logger (Section 8.5)."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    """Records every request, tool execution, decision, and risk level into SQLite."""

    def __init__(self, db_path: str = "data/audit.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    ok INTEGER NOT NULL,
                    error TEXT,
                    summary TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_log(tool_name);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def log_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        decision: str,
        duration_ms: float,
        ok: bool,
        error: str | None = None,
        summary: str = "",
    ) -> int:
        """Write a tool execution record to the audit database."""
        now_utc = datetime.now(timezone.utc).isoformat()
        args_str = json.dumps(args, default=str)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            cur = conn.execute(
                """
                INSERT INTO audit_log (
                    timestamp, tool_name, args_json, risk_level,
                    decision, duration_ms, ok, error, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_utc,
                    tool_name,
                    args_str,
                    risk_level,
                    decision,
                    duration_ms,
                    1 if ok else 0,
                    error,
                    summary,
                ),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve the most recent audit records."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                SELECT id, timestamp, tool_name, args_json, risk_level,
                       decision, duration_ms, ok, error, summary
                FROM audit_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# Global audit logger instance
audit_logger = AuditLogger()

"""Persistent SQLite Storage for Assistant Memory (Phase 12).

Provides local, inspectable, and removable SQLite storage:
- Facts (user-approved preferences, project directories, app aliases).
- Conversation context (rolling short-term memory).
- Action history (for workflow pattern detection).
- Workflows (candidate and approved action sequences).
- Explicit connection closure to prevent Windows WinError 32 file locks.
- Graceful degradation: database errors never crash the assistant.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Optional


class MemoryStore:
    """Manages persistent SQLite storage for assistant memory and workflows."""

    DEFAULT_DB_PATH = "data/memory.db"

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = str(Path(db_path))
        self._ensure_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with timeout and Row factory."""
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _ensure_db(self) -> None:
        """Initialize database directory and tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS facts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            category TEXT NOT NULL,
                            key TEXT NOT NULL,
                            value TEXT NOT NULL,
                            source TEXT NOT NULL DEFAULT 'user',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(category, key)
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_cat_key ON facts(category, key);")

                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS conversation_context (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            session_id TEXT NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            tool_calls TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_context(session_id);")

                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS action_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            intent TEXT NOT NULL,
                            tool_name TEXT NOT NULL,
                            args_json TEXT NOT NULL,
                            summary TEXT NOT NULL,
                            ok INTEGER NOT NULL,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_act_time ON action_history(timestamp);")

                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS workflows (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL UNIQUE,
                            trigger_pattern TEXT NOT NULL,
                            steps_json TEXT NOT NULL,
                            status TEXT NOT NULL DEFAULT 'candidate',
                            occurrence_count INTEGER DEFAULT 1,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            approved_at TIMESTAMP
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_wf_status ON workflows(status);")
            finally:
                conn.close()
        except sqlite3.Error as e:
            # Memory failure must not crash startup
            print(f"[WARN] MemoryStore init warning: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Facts CRUD
    # ──────────────────────────────────────────────────────────────────────────

    def set_fact(self, category: str, key: str, value: str, source: str = "user") -> bool:
        """Insert or update a memory fact."""
        try:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO facts (category, key, value, source, updated_at)
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(category, key) DO UPDATE SET
                            value=excluded.value,
                            source=excluded.source,
                            updated_at=CURRENT_TIMESTAMP;
                    """, (category.lower().strip(), key.lower().strip(), value.strip(), source))
                return True
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def get_fact(self, category: str, key: str) -> Optional[dict[str, Any]]:
        """Retrieve a specific fact by category and key."""
        try:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT id, category, key, value, source, created_at, updated_at FROM facts WHERE category = ? AND key = ?",
                    (category.lower().strip(), key.lower().strip())
                )
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()
        except sqlite3.Error:
            return None

    def delete_fact(self, category: str, key: str) -> bool:
        """Remove a fact from memory."""
        try:
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        "DELETE FROM facts WHERE category = ? AND key = ?",
                        (category.lower().strip(), key.lower().strip())
                    )
                    return cur.rowcount > 0
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def list_facts(self, category: Optional[str] = None) -> list[dict[str, Any]]:
        """List stored facts, optionally filtered by category."""
        try:
            conn = self._get_connection()
            try:
                if category:
                    cur = conn.execute(
                        "SELECT id, category, key, value, source, created_at, updated_at FROM facts WHERE category = ? ORDER BY key ASC",
                        (category.lower().strip(),)
                    )
                else:
                    cur = conn.execute(
                        "SELECT id, category, key, value, source, created_at, updated_at FROM facts ORDER BY category ASC, key ASC"
                    )
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    def clear_facts(self, category: Optional[str] = None) -> int:
        """Clear all facts or facts under a specific category."""
        try:
            conn = self._get_connection()
            try:
                with conn:
                    if category:
                        cur = conn.execute("DELETE FROM facts WHERE category = ?", (category.lower().strip(),))
                    else:
                        cur = conn.execute("DELETE FROM facts")
                    return cur.rowcount
            finally:
                conn.close()
        except sqlite3.Error:
            return 0

    # ──────────────────────────────────────────────────────────────────────────
    # Conversation Context CRUD
    # ──────────────────────────────────────────────────────────────────────────

    def add_conversation_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list[dict[str, Any]]] = None,
        max_turns_per_session: int = 20,
    ) -> bool:
        """Record a conversation turn and prune old turns exceeding max_turns."""
        try:
            calls_str = json.dumps(tool_calls or [])
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO conversation_context (session_id, role, content, tool_calls)
                        VALUES (?, ?, ?, ?)
                    """, (session_id, role, content, calls_str))

                    # Prune old turns beyond limit
                    conn.execute("""
                        DELETE FROM conversation_context
                        WHERE session_id = ? AND id NOT IN (
                            SELECT id FROM conversation_context
                            WHERE session_id = ?
                            ORDER BY id DESC LIMIT ?
                        )
                    """, (session_id, session_id, max_turns_per_session))
                return True
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def get_conversation_turns(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve recent conversation turns for a session in chronological order."""
        try:
            conn = self._get_connection()
            try:
                cur = conn.execute("""
                    SELECT id, session_id, role, content, tool_calls, created_at
                    FROM (
                        SELECT id, session_id, role, content, tool_calls, created_at
                        FROM conversation_context
                        WHERE session_id = ?
                        ORDER BY id DESC LIMIT ?
                    ) ORDER BY id ASC
                """, (session_id, limit))
                results = []
                for row in cur.fetchall():
                    item = dict(row)
                    try:
                        item["tool_calls"] = json.loads(item.get("tool_calls") or "[]")
                    except Exception:
                        item["tool_calls"] = []
                    results.append(item)
                return results
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # Action History & Workflows
    # ──────────────────────────────────────────────────────────────────────────

    def record_action(
        self,
        intent: str,
        tool_name: str,
        args: dict[str, Any],
        summary: str,
        ok: bool,
    ) -> int:
        """Log an action execution into history."""
        try:
            args_str = json.dumps(args, default=str)
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute("""
                        INSERT INTO action_history (intent, tool_name, args_json, summary, ok)
                        VALUES (?, ?, ?, ?, ?)
                    """, (intent, tool_name, args_str, summary[:500], 1 if ok else 0))
                    return cur.lastrowid or 0
            finally:
                conn.close()
        except sqlite3.Error:
            return 0

    def get_recent_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve recent action history."""
        try:
            conn = self._get_connection()
            try:
                cur = conn.execute("""
                    SELECT id, intent, tool_name, args_json, summary, ok, timestamp
                    FROM action_history
                    ORDER BY id DESC LIMIT ?
                """, (limit,))
                results = []
                for row in cur.fetchall():
                    item = dict(row)
                    try:
                        item["args"] = json.loads(item.get("args_json") or "{}")
                    except Exception:
                        item["args"] = {}
                    results.append(item)
                return results[::-1]  # Return chronological
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    def save_workflow_candidate(
        self,
        name: str,
        trigger_pattern: str,
        steps: list[dict[str, Any]],
    ) -> int:
        """Save or increment count for a candidate workflow."""
        try:
            steps_str = json.dumps(steps)
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO workflows (name, trigger_pattern, steps_json, status, occurrence_count)
                        VALUES (?, ?, ?, 'candidate', 1)
                        ON CONFLICT(name) DO UPDATE SET
                            occurrence_count = occurrence_count + 1,
                            steps_json = excluded.steps_json;
                    """, (name.lower().strip(), trigger_pattern.lower().strip(), steps_str))
                    cur = conn.execute("SELECT id FROM workflows WHERE name = ?", (name.lower().strip(),))
                    row = cur.fetchone()
                    return row["id"] if row else 0
            finally:
                conn.close()
        except sqlite3.Error:
            return 0

    def list_workflows(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        """List workflows, optionally filtered by status ('candidate', 'approved', 'rejected')."""
        try:
            conn = self._get_connection()
            try:
                if status:
                    cur = conn.execute("""
                        SELECT id, name, trigger_pattern, steps_json, status, occurrence_count, created_at, approved_at
                        FROM workflows WHERE status = ? ORDER BY id DESC
                    """, (status.lower().strip(),))
                else:
                    cur = conn.execute("""
                        SELECT id, name, trigger_pattern, steps_json, status, occurrence_count, created_at, approved_at
                        FROM workflows ORDER BY id DESC
                    """)
                results = []
                for row in cur.fetchall():
                    item = dict(row)
                    try:
                        item["steps"] = json.loads(item.get("steps_json") or "[]")
                    except Exception:
                        item["steps"] = []
                    results.append(item)
                return results
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    def get_workflow(self, identifier: str | int) -> Optional[dict[str, Any]]:
        """Find workflow by ID or name."""
        try:
            conn = self._get_connection()
            try:
                if isinstance(identifier, int) or (isinstance(identifier, str) and str(identifier).isdigit()):
                    cur = conn.execute("""
                        SELECT id, name, trigger_pattern, steps_json, status, occurrence_count, created_at, approved_at
                        FROM workflows WHERE id = ?
                    """, (int(identifier),))
                else:
                    cur = conn.execute("""
                        SELECT id, name, trigger_pattern, steps_json, status, occurrence_count, created_at, approved_at
                        FROM workflows WHERE name = ?
                    """, (str(identifier).lower().strip(),))

                row = cur.fetchone()
                if not row:
                    return None
                item = dict(row)
                try:
                    item["steps"] = json.loads(item.get("steps_json") or "[]")
                except Exception:
                    item["steps"] = []
                return item
            finally:
                conn.close()
        except sqlite3.Error:
            return None

    def update_workflow_status(
        self,
        identifier: str | int,
        status: str,
        name: Optional[str] = None,
        trigger_pattern: Optional[str] = None,
    ) -> bool:
        """Update workflow status (e.g. promoting 'candidate' to 'approved')."""
        try:
            conn = self._get_connection()
            try:
                is_num = isinstance(identifier, int) or (isinstance(identifier, str) and str(identifier).isdigit())
                where_clause = "id = ?" if is_num else "name = ?"
                param = int(identifier) if is_num else str(identifier).lower().strip()

                approved_clause = ", approved_at = CURRENT_TIMESTAMP" if status == "approved" else ""

                with conn:
                    if name and trigger_pattern:
                        query = f"""
                            UPDATE workflows
                            SET status = ?, name = ?, trigger_pattern = ? {approved_clause}
                            WHERE {where_clause}
                        """
                        cur = conn.execute(query, (status, name.lower().strip(), trigger_pattern.lower().strip(), param))
                    else:
                        query = f"""
                            UPDATE workflows
                            SET status = ? {approved_clause}
                            WHERE {where_clause}
                        """
                        cur = conn.execute(query, (status, param))

                    return cur.rowcount > 0
            finally:
                conn.close()
        except sqlite3.Error:
            return False

    def delete_workflow(self, identifier: str | int) -> bool:
        """Delete a workflow from database."""
        try:
            conn = self._get_connection()
            try:
                with conn:
                    if isinstance(identifier, int) or (isinstance(identifier, str) and str(identifier).isdigit()):
                        cur = conn.execute("DELETE FROM workflows WHERE id = ?", (int(identifier),))
                    else:
                        cur = conn.execute("DELETE FROM workflows WHERE name = ?", (str(identifier).lower().strip(),))
                    return cur.rowcount > 0
            finally:
                conn.close()
        except sqlite3.Error:
            return False

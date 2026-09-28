"""High-Level Memory & Context Manager (Phase 12).

Provides unified memory access:
- User-approved facts & preferences
- Project locations & physical folder context
- Application aliases
- Dynamic context resolution for user queries
- Conversation history tracking
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from assistant.memory.sanitizer import MemorySanitizer, MemorySecurityError
from assistant.memory.store import MemoryStore


class MemoryManager:
    """Coordinates memory facts, context resolution, and conversation state."""

    VALID_CATEGORIES = {"preference", "project", "alias", "general"}

    def __init__(self, store: Optional[MemoryStore] = None) -> None:
        self.store = store or MemoryStore()

    # ──────────────────────────────────────────────────────────────────────────
    # Facts Management
    # ──────────────────────────────────────────────────────────────────────────

    def remember(
        self,
        category: str,
        key: str,
        value: str,
        source: str = "user",
    ) -> tuple[bool, str]:
        """Store or update a sanitized memory fact.

        Returns:
            (ok, message_or_error)
        """
        cat_clean = category.lower().strip()
        if cat_clean not in self.VALID_CATEGORIES:
            return False, f"Kategori tidak valid '{category}'. Kategori yang didukung: {', '.join(sorted(self.VALID_CATEGORIES))}."

        is_safe, error, clean_key, clean_val = MemorySanitizer.sanitize_fact(cat_clean, key, value)
        if not is_safe:
            return False, f"Penolakan keamanan memori: {error}"

        # If project category, verify and normalize path if possible
        if cat_clean == "project":
            clean_val = clean_val.replace("/", "\\")

        ok = self.store.set_fact(
            category=cat_clean,
            key=clean_key,
            value=clean_val,
            source=source,
        )
        if not ok:
            return False, "Gagal menyimpan fakta ke database memori lokal."

        return True, f"Berhasil mengingat [{cat_clean}] '{clean_key}' = '{clean_val}'."

    def recall(self, category: str, key: Optional[str] = None) -> Optional[str]:
        """Retrieve a stored fact value. Supports recall('cat', 'key') or recall('cat:key') or recall('key')."""
        if key is None:
            if ":" in category:
                cat_part, key_part = category.split(":", 1)
                cat_clean = cat_part.lower().strip()
                key_clean = key_part.lower().strip()
            else:
                cat_clean = "general"
                key_clean = category.lower().strip()
        else:
            cat_clean = category.lower().strip()
            key_clean = key.lower().strip()

        fact = self.store.get_fact(cat_clean, key_clean)
        if not fact and cat_clean == "general":
            for f in self.store.list_facts():
                if f["key"].lower() == key_clean:
                    return f["value"]
        return fact["value"] if fact else None

    def forget(self, category: str, key: Optional[str] = None) -> tuple[bool, str]:
        """Remove a stored fact. Supports forget('cat', 'key') or forget('cat:key') or forget('key')."""
        if key is None:
            if ":" in category:
                cat_part, key_part = category.split(":", 1)
                cat_clean = cat_part.lower().strip()
                key_clean = key_part.lower().strip()
            else:
                cat_clean = "general"
                key_clean = category.lower().strip()
        else:
            cat_clean = category.lower().strip()
            key_clean = key.lower().strip()

        ok = self.store.delete_fact(cat_clean, key_clean)
        if not ok and cat_clean == "general":
            # Search all categories if general wasn't found
            all_facts = self.store.list_facts()
            for f in all_facts:
                if f["key"].lower() == key_clean:
                    ok = self.store.delete_fact(f["category"], key_clean)
                    if ok:
                        cat_clean = f["category"]
                        break
        if ok:
            return True, f"Fakta [{cat_clean}] '{key_clean}' berhasil dihapus dari memori."
        return False, f"Fakta [{cat_clean}] '{key_clean}' tidak ditemukan di memori."

    def list_facts(self, category: Optional[str] = None) -> list[dict[str, Any]]:
        """List all facts or facts under category."""
        return self.store.list_facts(category)

    def clear(self, category: Optional[str] = None) -> tuple[bool, str]:
        """Clear all facts or facts in category."""
        count = self.store.clear_facts(category)
        if category:
            return True, f"{count} fakta dalam kategori '{category}' berhasil dibersihkan."
        return True, f"{count} seluruh fakta memori berhasil dibersihkan."

    # ──────────────────────────────────────────────────────────────────────────
    # Context Resolution for Queries
    # ──────────────────────────────────────────────────────────────────────────

    def resolve_context(self, query: str) -> dict[str, Any]:
        """Resolve project paths and application aliases mentioned in a user query.

        Example:
            User: "Buka project jarvis"
            Fact: [project] 'jarvis' = 'D:\project\jarvis'
            Returns: {
                "matched_projects": {"jarvis": "D:\\project\\jarvis"},
                "matched_aliases": {},
                "resolved_folder": "D:\\project\\jarvis"
            }
        """
        results: dict[str, Any] = {
            "matched_projects": {},
            "matched_aliases": {},
            "resolved_folder": None,
            "resolved_app": None,
        }

        query_clean = query.lower().strip()

        # 1. Check projects
        projects = self.store.list_facts(category="project")
        for p in projects:
            p_key = p["key"].lower()
            p_val = p["value"]
            # Check if project name is mentioned in query
            if p_key in query_clean:
                results["matched_projects"][p_key] = p_val
                if not results["resolved_folder"] and Path(p_val).is_dir():
                    results["resolved_folder"] = p_val

        # 2. Check aliases
        aliases = self.store.list_facts(category="alias")
        for a in aliases:
            a_key = a["key"].lower()
            a_val = a["value"]
            if a_key in query_clean:
                results["matched_aliases"][a_key] = a_val
                if not results["resolved_app"]:
                    results["resolved_app"] = a_val

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Natural Language Memory Parsing
    # ──────────────────────────────────────────────────────────────────────────

    def try_parse_memory_command(self, text: str) -> Optional[tuple[str, str, str, str]]:
        """Detect and parse explicit natural language commands to remember facts.

        Returns:
            (command_type, category, key, value) or None.
            command_type: 'remember' or 'forget'
        """
        t = text.strip()

        # 1. "project <name> (ada) di <path>"
        # e.g. "project jarvis ada di D:\project\jarvis" or "lokasi project jarvis di D:\jarvis"
        m_proj = re.search(r"(?:lokasi\s+)?project\s+([a-zA-Z0-9_\-]+)\s+(?:ada\s+)?di\s+([a-zA-Z]:\\[^\n\r]+|/[^\n\r]+)", t, re.IGNORECASE)
        if m_proj:
            return "remember", "project", m_proj.group(1).lower().strip(), m_proj.group(2).strip()

        # 2. "ingat project <name> di <path>"
        m_ingat_proj = re.search(r"ingat(?:kan)?\s+project\s+([a-zA-Z0-9_\-]+)\s+(?:ada\s+)?di\s+([a-zA-Z]:\\[^\n\r]+|/[^\n\r]+)", t, re.IGNORECASE)
        if m_ingat_proj:
            return "remember", "project", m_ingat_proj.group(1).lower().strip(), m_ingat_proj.group(2).strip()

        # 3. "ingat alias <alias> adalah/yaitu/= <target>"
        m_alias = re.search(r"ingat(?:kan)?\s+alias\s+([a-zA-Z0-9_\-]+)\s+(?:adalah|yaitu|=|ke)\s+([^\n\r]+)", t, re.IGNORECASE)
        if m_alias:
            return "remember", "alias", m_alias.group(1).lower().strip(), m_alias.group(2).strip()

        # 4. "ingat preferensi/preference <key> adalah/yaitu/= <value>" or "ingat preferensi/preference <key> <value>"
        m_pref = re.search(r"ingat(?:kan)?\s+(?:preferensi|preference)\s+([a-zA-Z0-9_\-]+)(?:\s+(?:adalah|yaitu|=)\s*|\s+)([^\n\r]+)", t, re.IGNORECASE)
        if m_pref:
            return "remember", "preference", m_pref.group(1).lower().strip(), m_pref.group(2).strip()

        # 5. "ingat [category]:[key] adalah/yaitu/= [value]"
        m_cat_key = re.search(r"ingat(?:kan)?(?: bahwa)?\s+([a-zA-Z0-9_\-]+):([a-zA-Z0-9_\-]+)\s+(?:adalah|yaitu|=)\s+([^\n\r]+)", t, re.IGNORECASE)
        if m_cat_key:
            return "remember", m_cat_key.group(1).lower().strip(), m_cat_key.group(2).lower().strip(), m_cat_key.group(3).strip()

        # 6. "ingat [key/phrase] adalah/yaitu/= [value]"
        m_gen = re.search(r"ingat(?:kan)?(?: bahwa)?\s+([a-zA-Z0-9_\-\s]+?)\s+(?:adalah|yaitu|=)\s+([^\n\r]+)", t, re.IGNORECASE)
        if m_gen:
            return "remember", "general", m_gen.group(1).lower().strip(), m_gen.group(2).strip()

        # 7. Forget commands:
        # a. "lupakan/hapus category:key"
        m_del_colon = re.search(r"(?:lupa(?:kan)?|hapus\s+memori)\s+([a-zA-Z0-9_\-]+):([a-zA-Z0-9_\-]+)", t, re.IGNORECASE)
        if m_del_colon:
            return "forget", m_del_colon.group(1).lower().strip(), m_del_colon.group(2).lower().strip(), ""

        # b. "lupakan/hapus category key"
        m_del = re.search(r"(?:lupa(?:kan)?|hapus\s+memori)\s+(project|alias|preference|general)\s+([a-zA-Z0-9_\-]+)", t, re.IGNORECASE)
        if m_del:
            return "forget", m_del.group(1).lower().strip(), m_del.group(2).lower().strip(), ""

        # c. "lupakan key"
        m_del_key = re.search(r"(?:lupa(?:kan)?|hapus\s+memori)\s+([a-zA-Z0-9_\-]+)", t, re.IGNORECASE)
        if m_del_key:
            return "forget", "general", m_del_key.group(1).lower().strip(), ""

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Conversation Context Tracking
    # ──────────────────────────────────────────────────────────────────────────

    def record_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list[dict[str, Any]]] = None,
    ) -> bool:
        """Record a conversation turn."""
        return self.store.add_conversation_turn(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
        )

    def get_conversation_history(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve recent conversation turns."""
        return self.store.get_conversation_turns(session_id=session_id, limit=limit)


# Global default MemoryManager instance
memory_manager = MemoryManager()

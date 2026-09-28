"""Memory Sanitizer & Security Boundary (Phase 12).

Strict Security & Privacy Rules:
1. NEVER store passwords, tokens, API keys, credentials, PINs, or CVVs.
2. NEVER store sensitive clipboard contents or raw microphone audio.
3. NEVER store content tagged with <untrusted_*> as automatic persistent facts.
4. Enforce strict character limits to prevent memory exhaustion attacks.
5. All stored facts and keys are sanitized and validated before persisting to SQLite.
"""

from __future__ import annotations

import re
from typing import Optional

# Prohibited sensitive keywords and patterns
FORBIDDEN_SENSITIVE_KEYWORDS = [
    "password",
    "passwd",
    "kata_sandi",
    "token",
    "api_key",
    "secret",
    "credential",
    "pin",
    "cvv",
    "credit_card",
    "private_key",
    "auth_bearer",
    "session_id",
]

SENSITIVE_PREFIXES = (
    "ghp_",
    "gho_",
    "glpat-",
    "sk-",
    "xoxb-",
    "xoxp-",
    "bearer ",
)

UNTRUSTED_TAG_PATTERNS = [
    re.compile(r"<untrusted_web_source>.*?</untrusted_web_source>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<untrusted_ui_content>.*?</untrusted_ui_content>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<untrusted_screen_content>.*?</untrusted_screen_content>", re.DOTALL | re.IGNORECASE),
]

MAX_KEY_LENGTH = 120
MAX_VALUE_LENGTH = 4000


class MemorySecurityError(ValueError):
    """Raised when memory content violates security or privacy rules."""
    pass


class MemorySanitizer:
    """Validates and sanitizes memory entries before database persistence."""

    @classmethod
    def check_sensitive_content(cls, text: str) -> Optional[str]:
        """Check text for secrets, tokens, passwords, or credentials.

        Returns:
            Reason string if sensitive, None if safe.
        """
        text_lower = text.lower().strip()
        text_norm = re.sub(r"[_\-\s]+", " ", text_lower)
        text_nospace = re.sub(r"[_\-\s]+", "", text_lower)

        # Check sensitive prefixes
        for pref in SENSITIVE_PREFIXES:
            if pref in text_lower or pref in text_nospace:
                return f"Contains sensitive token prefix '{pref}'"

        # Check sensitive keywords with word-boundary matching for short words
        for kw in FORBIDDEN_SENSITIVE_KEYWORDS:
            if len(kw) <= 4:
                if re.search(r"\b" + re.escape(kw) + r"\b", text_norm):
                    return f"Contains sensitive keyword '{kw}'"
            else:
                if kw in text_lower or kw in text_norm or kw in text_nospace:
                    return f"Contains sensitive keyword '{kw}'"

        return None

    @classmethod
    def contains_untrusted_tags(cls, text: str) -> bool:
        """Check if text contains untrusted content wrappers."""
        for pat in UNTRUSTED_TAG_PATTERNS:
            if pat.search(text):
                return True
        return "<untrusted_" in text.lower()

    @classmethod
    def sanitize_fact(
        cls,
        category: str,
        key: str,
        value: str,
    ) -> tuple[bool, str, str, str]:
        """Validate and sanitize a proposed memory fact.

        Returns:
            (is_safe, error_or_reason, clean_key, clean_val)
        """
        clean_cat = category.strip().lower()
        clean_key = key.strip().lower()
        clean_val = value.strip()

        if not clean_cat:
            return False, "Category cannot be empty", clean_key, clean_val
        if not clean_key:
            return False, "Key cannot be empty", clean_key, clean_val
        if not clean_val:
            return False, "Value cannot be empty", clean_key, clean_val

        # Length validation
        if len(clean_key) > MAX_KEY_LENGTH:
            return False, f"Key exceeds maximum length of {MAX_KEY_LENGTH} characters", clean_key, clean_val
        if len(clean_val) > MAX_VALUE_LENGTH:
            return False, f"Value exceeds maximum length of {MAX_VALUE_LENGTH} characters", clean_key, clean_val

        # Check for untrusted injection tags
        if cls.contains_untrusted_tags(clean_key) or cls.contains_untrusted_tags(clean_val):
            return (
                False,
                "Untrusted external content (<untrusted_*>) cannot be stored directly into memory",
                clean_key,
                clean_val,
            )

        # Check key and value for sensitive content
        key_sensitive = cls.check_sensitive_content(clean_key)
        if key_sensitive:
            return False, f"Memory key rejected: {key_sensitive}", clean_key, clean_val

        val_sensitive = cls.check_sensitive_content(clean_val)
        if val_sensitive:
            return False, f"Memory value rejected: {val_sensitive}", clean_key, clean_val

        return True, "", clean_key, clean_val

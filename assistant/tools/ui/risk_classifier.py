"""Risk classification for Windows UI Automation interactive actions (Phase 10B).

Enforces PolicyEngine L0–L3 boundaries based on:
- Control Name, AutomationId, ControlType, localized type
- Surrounding context metadata
- Action semantics (Focus, Invoke, SetValue, Toggle)

Policy Rules:
- ui.focus:
    Default: L2 (LOW_ACTION).
    L0 (FORBIDDEN): Secure desktop, UAC prompt, credential dialog, Windows Security.
- ui.invoke:
    Default: L2 (LOW_ACTION) for ordinary buttons, tabs, navigation, safe menus.
    L3 (CONFIRM): Destructive actions (Delete, Remove, Uninstall, Format, Reset),
    transactional/submission actions (Submit, Order, Purchase, Pay, Publish),
    or high-impact Apply settings.
- ui.set_value:
    Default: L2 (LOW_ACTION) for search boxes, filters, ordinary text fields.
    L0 (FORBIDDEN): Password, PIN, token, API key, credential, card/CVV data.
    Ambiguous security/auth fields escalate to L0 block (never silently assume safe).
- ui.toggle:
    Default: L2 (LOW_ACTION) for ordinary settings, preferences, feature toggles.
    L3 (CONFIRM): Firewall, Windows Defender, antivirus, tamper protection,
    remote desktop, security/system protection settings.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple
from assistant.tools.base import Risk

# ──────────────────────────────────────────────────────────────────────────────
# Keyword matchers
# ──────────────────────────────────────────────────────────────────────────────

# Sensitive credentials & passwords (L0 BLOCK TOTAL)
SENSITIVE_FIELD_KEYWORDS = [
    "password",
    "passwd",
    "pwd",
    "pin",
    "token",
    "api_key",
    "apikey",
    "secret",
    "credential",
    "cvv",
    "cvc",
    "card_number",
    "credit_card",
    "debit_card",
    "rekening",
    "no_kartu",
    "otp",
    "passphrase",
    "auth_token",
    "private_key",
    "access_key",
    "master_key",
    "security_code",
    "recovery_code",
    "secret_key",
]

# Protected system dialogs / secure desktop (L0 BLOCK)
PROTECTED_UI_NAMES = [
    "consent.exe",
    "logonui.exe",
    "credentialuibroker.exe",
    "securityhealthsystray.exe",
    "windows security",
    "user account control",
    "credential prompt",
    "lockapp.exe",
]

# Destructive & transactional invoke actions (L3 CONFIRM)
DESTRUCTIVE_KEYWORDS = [
    "delete",
    "remove",
    "uninstall",
    "format",
    "wipe",
    "erase",
    "purge",
    "destroy",
    "drop",
    "reset",
    "clear all",
    "factory reset",
    "submit",
    "order",
    "purchase",
    "pay",
    "checkout",
    "publish",
    "deploy",
    "buy now",
    "place order",
    "send money",
    "transfer funds",
    "apply changes",
    "commit changes",
    "overwrite",
]

# Safe ordinary button names that should NOT trigger L3 despite partial substring matches
SAFE_ORDINARY_BUTTONS = [
    "ok",
    "cancel",
    "close",
    "back",
    "next",
    "finish",
    "browse",
    "search",
    "open",
    "view",
    "help",
    "refresh",
    "select",
    "tab",
    "menu",
    "settings",
    "apply filter",
    "find",
]

# Security & system protection toggle settings (L3 CONFIRM)
SECURITY_TOGGLE_KEYWORDS = [
    "firewall",
    "windows defender",
    "antivirus",
    "tamper protection",
    "real-time protection",
    "realtime protection",
    "developer mode",
    "remote desktop",
    "user account control",
    "credential guard",
    "secure boot",
    "system protection",
    "root access",
    "disable protection",
    "turn off protection",
]


def _match_any_keyword(text: str, keywords: list[str]) -> Optional[str]:
    """Check if normalized text contains any keyword as word or substring."""
    if not text:
        return None
    text_lower = text.lower().strip()
    norm_space = re.sub(r"[_\-\s]+", " ", text_lower)
    norm_nospace = re.sub(r"[_\-\s]+", "", text_lower)
    for kw in keywords:
        kw_lower = kw.lower().strip()
        # For short whole-word keywords (<= 4 chars like pin, otp, cvv, pwd), require word boundaries
        if len(kw_lower) <= 4 and not any(kw_lower.endswith(c) for c in ("-", "_", "=")):
            if re.search(r"\b" + re.escape(kw_lower) + r"\b", norm_space):
                return kw
            continue
        kw_space = re.sub(r"[_\-\s]+", " ", kw_lower)
        kw_nospace = re.sub(r"[_\-\s]+", "", kw_lower)
        if kw_space in norm_space or kw_nospace in norm_nospace or kw_lower in text_lower:
            return kw
    return None


def is_protected_security_window(props: dict[str, Any], extra_text: str = "") -> bool:
    """Detect if the target control belongs to a protected system security window."""
    corpus = " ".join([
        str(props.get("name", "")),
        str(props.get("class_name", "")),
        str(props.get("automation_id", "")),
        str(extra_text),
    ]).lower()

    for item in PROTECTED_UI_NAMES:
        if item in corpus:
            return True
    return False


def is_credential_field(props: dict[str, Any], selector_text: str = "") -> Tuple[bool, str]:
    """Determine if a control is a sensitive password or credential field (L0).

    Returns:
        (is_sensitive, reason)
    """
    # Native UIA flag
    if props.get("is_password") is True:
        return True, "Element has native IsPassword=True flag"

    corpus = " ".join([
        str(props.get("name", "")),
        str(props.get("automation_id", "")),
        str(props.get("class_name", "")),
        str(props.get("localized_type", "")),
        str(selector_text),
    ]).lower()

    matched_kw = _match_any_keyword(corpus, SENSITIVE_FIELD_KEYWORDS)
    if matched_kw:
        return True, f"Control identifier matches sensitive keyword '{matched_kw}'"

    return False, ""


def is_destructive_invoke(props: dict[str, Any], selector_text: str = "") -> Tuple[bool, str]:
    """Determine if an invoke action has destructive or high-impact consequences (L3).

    Returns:
        (is_destructive, reason)
    """
    name = str(props.get("name", "")).strip().lower()
    auto_id = str(props.get("automation_id", "")).strip().lower()
    selector = str(selector_text).strip().lower()

    # If the control name is explicitly an ordinary safe button, keep it L2
    if name in SAFE_ORDINARY_BUTTONS:
        return False, ""

    corpus = f"{name} {auto_id} {selector}"
    matched_kw = _match_any_keyword(corpus, DESTRUCTIVE_KEYWORDS)
    if matched_kw:
        return True, f"Control indicates high-impact/destructive action ('{matched_kw}')"

    return False, ""


def is_security_toggle(props: dict[str, Any], selector_text: str = "") -> Tuple[bool, str]:
    """Determine if a toggle/checkbox affects security or system protection (L3).

    Returns:
        (is_security, reason)
    """
    corpus = " ".join([
        str(props.get("name", "")),
        str(props.get("automation_id", "")),
        str(props.get("class_name", "")),
        str(selector_text),
    ]).lower()

    matched_kw = _match_any_keyword(corpus, SECURITY_TOGGLE_KEYWORDS)
    if matched_kw:
        return True, f"Toggle controls security/system protection setting ('{matched_kw}')"

    return False, ""


def classify_ui_action(
    action: str,
    props: dict[str, Any],
    selector_text: str = "",
    value: Optional[str] = None,
) -> Tuple[Risk, str]:
    """Classify the risk level of an interactive UI action given live element properties.

    Args:
        action: One of 'focus', 'invoke', 'set_value', 'toggle'.
        props: Element properties dict from read_element_properties.
        selector_text: Search or selector query used to locate the element.
        value: Text value being typed (for set_value).

    Returns:
        (Risk, explanation_reason)
    """
    # Check protected security dialogs first for all actions
    if is_protected_security_window(props, selector_text):
        return Risk.FORBIDDEN, "Interaction with secure desktop or credential dialog is blocked (L0)."

    action_norm = action.lower().replace("ui.", "")

    if action_norm == "focus":
        return Risk.LOW_ACTION, "Focus ordinary UI control (L2)."

    elif action_norm == "invoke":
        destructive, reason = is_destructive_invoke(props, selector_text)
        if destructive:
            return Risk.CONFIRM, reason
        return Risk.LOW_ACTION, "Invoke ordinary UI navigation/button control (L2)."

    elif action_norm == "set_value":
        sensitive, reason = is_credential_field(props, selector_text)
        if sensitive:
            return Risk.FORBIDDEN, f"Sensitive/credential field entry blocked (L0): {reason}."

        # Also check value being typed if provided
        if value:
            val_match = _match_any_keyword(
                str(value),
                SENSITIVE_FIELD_KEYWORDS + ["sk-", "ghp_", "secret="]
            )
            if val_match:
                return Risk.FORBIDDEN, f"Input value matches credential token pattern '{val_match}' (L0)."

        return Risk.LOW_ACTION, "Input text into ordinary non-sensitive field (L2)."

    elif action_norm == "toggle":
        sec_toggle, reason = is_security_toggle(props, selector_text)
        if sec_toggle:
            return Risk.CONFIRM, reason
        return Risk.LOW_ACTION, "Toggle ordinary preference or setting (L2)."

    elif action_norm in ("close_window", "window.close", "window_close", "close"):
        title = str(props.get("title") or props.get("name") or "")
        pname = str(props.get("process_name") or "")
        from assistant.tools.ui.window_manager import is_consequential_window, is_protected_process_window
        meta = {"title": title, "process_name": pname}
        is_prot, prot_reason = is_protected_process_window(meta)
        if is_prot:
            return Risk.FORBIDDEN, prot_reason
        is_conseq, conseq_reason = is_consequential_window(meta)
        if is_conseq:
            return Risk.CONFIRM, conseq_reason
        return Risk.LOW_ACTION, "Safe ordinary window close (L2)."

    elif action_norm in ("activate_window", "window.activate", "window_activate", "activate"):
        title = str(props.get("title") or props.get("name") or "")
        pname = str(props.get("process_name") or "")
        from assistant.tools.ui.window_manager import is_protected_process_window
        is_prot, prot_reason = is_protected_process_window({"title": title, "process_name": pname})
        if is_prot:
            return Risk.FORBIDDEN, prot_reason
        return Risk.LOW_ACTION, "Safe window activation (L2)."

    elif action_norm in ("click_at", "click"):
        return Risk.LOW_ACTION, "Safe bounded coordinate click (L2)."

    elif action_norm in ("send_keys", "press_key"):
        combo = str(selector_text or "").lower()
        if any(d in combo for d in ("shift+del", "shift+delete", "format", "wipe")):
            return Risk.CONFIRM, "Destructive keyboard shortcut requires explicit confirmation (L3)."
        if any(u in combo for u in ("alt+y", "ctrl+alt+del")):
            return Risk.FORBIDDEN, "Automated confirmation on secure dialogs is forbidden (L0)."
        return Risk.LOW_ACTION, "Safe keyboard shortcut / key press (L2)."

    elif action_norm in ("type_text", "type"):
        sensitive, reason = is_credential_field(props, selector_text)
        if sensitive:
            return Risk.FORBIDDEN, f"Sensitive/credential field entry blocked (L0): {reason}."
        if value:
            val_match = _match_any_keyword(
                str(value),
                SENSITIVE_FIELD_KEYWORDS + ["sk-", "ghp_", "secret="]
            )
            if val_match:
                return Risk.FORBIDDEN, f"Input value matches credential token pattern '{val_match}' (L0)."
        return Risk.LOW_ACTION, "Input text into ordinary non-sensitive field (L2)."

    return Risk.LOW_ACTION, "Default UI action (L2)."


def classify_ui_action_from_args(tool_name: str, args: dict[str, Any]) -> Tuple[Risk, str]:
    """Classify risk dynamically from tool call arguments for PolicyEngine integration.

    Used by PolicyEngine before tool execution starts.
    """
    title = str(args.get("title") or args.get("name") or "")
    process_name = str(args.get("process_name") or "")
    keys = str(args.get("keys") or "")
    text_val = str(args.get("text") or args.get("value") or "") if ("text" in args or "value" in args) else None

    corpus_parts = [
        title,
        process_name,
        keys,
        str(args.get("automation_id") or ""),
        str(args.get("path") or ""),
        str(args.get("control_type") or ""),
    ]
    corpus = " ".join([p for p in corpus_parts if p])

    props_hint = {
        "title": title,
        "name": title,
        "process_name": process_name,
        "automation_id": str(args.get("automation_id") or ""),
        "control_type": str(args.get("control_type") or ""),
        "is_password": False,
    }

    selector = keys if keys else corpus

    return classify_ui_action(
        action=tool_name,
        props=props_hint,
        selector_text=selector,
        value=text_val,
    )


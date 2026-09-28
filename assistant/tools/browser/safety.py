"""Browser Safety, Sensitivity Classifier, and Prompt Injection Defense (Phase 9B & 9C)."""

from __future__ import annotations

import re
from typing import Any, Optional
from assistant.tools.base import Risk


# Patterns that are strictly L0 (FORBIDDEN) - passwords, payment, credentials, CAPTCHA
SENSITIVE_FIELD_PATTERNS = [
    r"pass(word|phrase|code)?",
    r"pwd",
    r"secret",
    r"token",
    r"api[_-]?key",
    r"credit[_-]?card",
    r"card[_-]?num(ber)?",
    r"cvv|cvc|cid",
    r"expir(y|ation)",
    r"pin\b",
    r"otp\b",
    r"auth[_-]?code",
    r"ssn\b",
    r"social[_-]?security",
    r"bank[_-]?acc(ount)?",
    r"routing[_-]?num(ber)?",
    r"captcha",
    r"recaptcha",
    r"hcaptcha",
]

SENSITIVE_INPUT_TYPES = {
    "password",
    "hidden",  # Often contains anti-CSRF or auth tokens
}

# Patterns that indicate L3 actions (CONFIRM) - submission, purchase, delete, publish, execute
CONFIRM_ACTION_PATTERNS = [
    r"\bsubmit\b",
    r"\bsend\b",
    r"\bbuy\b",
    r"\border\b",
    r"\bpurchase\b",
    r"\bcheckout\b",
    r"\bpay(ment)?\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bdestroy\b",
    r"\bcancel\b",
    r"\bpublish\b",
    r"\bpost\b",
    r"\bconfirm\b",
    r"\btransfer\b",
    r"\bapply\b",
    r"\bcheckout\b",
    r"\bcheckout-button\b",
    r"\bplace-order\b",
]

# Patterns that are typically safe navigational L2 actions
NAVIGATIONAL_ROLES = {"link", "tab", "menuitem", "button"}
NAVIGATIONAL_TAGS = {"a", "nav"}


def is_sensitive_field(
    selector: str = "",
    tag: str = "",
    input_type: str = "",
    name: str = "",
    elem_id: str = "",
    placeholder: str = "",
    aria_label: str = "",
    autocomplete: str = "",
    surrounding_text: str = "",
) -> tuple[bool, str]:
    """Check if an input field or element is security-sensitive (L0 FORBIDDEN).

    Returns (is_sensitive, reason).
    """
    # 1. Check input type
    if input_type.lower() in SENSITIVE_INPUT_TYPES:
        return True, f"Input type '{input_type}' is security-sensitive (L0)."

    # 2. Check autocomplete attribute
    autocomplete_lower = autocomplete.lower()
    for sensitive in ["current-password", "new-password", "cc-number", "cc-csc", "cc-exp", "one-time-code"]:
        if sensitive in autocomplete_lower:
            return True, f"Autocomplete attribute '{autocomplete}' indicates sensitive credential/payment data (L0)."

    # 3. Check combined text representation against sensitive patterns
    combined = " ".join([selector, tag, name, elem_id, placeholder, aria_label, surrounding_text]).lower()
    for pattern in SENSITIVE_FIELD_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return True, f"Target matches sensitive security pattern '{pattern}' (L0)."

    return False, ""


def classify_action_risk(
    action: str,  # 'click' or 'type'
    selector: str = "",
    text: str = "",
    role: str = "",
    tag: str = "",
    input_type: str = "",
    name: str = "",
    elem_id: str = "",
    placeholder: str = "",
    aria_label: str = "",
    autocomplete: str = "",
    href: str = "",
    surrounding_text: str = "",
) -> tuple[Risk, str]:
    """Classify the risk level of a browser action based on element properties and context.

    Returns:
        (Risk, explanation)
    """
    # 1. Check L0 (Sensitive credential, payment, CAPTCHA, or auth fields)
    sensitive, reason = is_sensitive_field(
        selector=selector,
        tag=tag,
        input_type=input_type,
        name=name,
        elem_id=elem_id,
        placeholder=placeholder,
        aria_label=aria_label,
        autocomplete=autocomplete,
        surrounding_text=surrounding_text,
    )
    if sensitive:
        return Risk.FORBIDDEN, reason

    # Check for login/captcha in text or selector
    combined_desc = " ".join([selector, text, name, elem_id, aria_label, surrounding_text]).lower()
    if re.search(r"\b(login|sign[_-]?in|captcha)\b", combined_desc, re.IGNORECASE):
        # If it's a typing action into a login/sign-in related element -> L0
        if action == "type":
            return Risk.FORBIDDEN, "Automated credential entry or CAPTCHA solving is strictly forbidden (L0)."

    # 2. Check L3 (Submit, purchase, delete, publish, payment, high-risk confirm)
    if action == "click":
        # Check if button or input is a submit type
        if input_type.lower() == "submit":
            return Risk.CONFIRM, "Submit button triggers form action / data transmission (L3 confirmation required)."

        for pattern in CONFIRM_ACTION_PATTERNS:
            if re.search(pattern, combined_desc, re.IGNORECASE):
                return Risk.CONFIRM, f"Action matches high-risk pattern '{pattern}' (L3 confirmation required)."

    elif action == "type":
        # If target field is associated with a high-impact submit or ambiguous control
        for pattern in CONFIRM_ACTION_PATTERNS:
            if re.search(pattern, selector.lower(), re.IGNORECASE):
                return Risk.CONFIRM, f"Input field matches sensitive action pattern '{pattern}' (L3 confirmation required)."

    # 3. Check L2 (Navigational click, ordinary text input)
    if action == "click":
        # Navigation links or tabs
        if tag.lower() in NAVIGATIONAL_TAGS or role.lower() in NAVIGATIONAL_ROLES or href:
            return Risk.LOW_ACTION, "Navigational link or UI element click (L2)."
        # Non-destructive button without confirm patterns
        return Risk.LOW_ACTION, "Ordinary non-destructive click (L2)."

    elif action == "type":
        # Ordinary non-sensitive input (search, filter, text)
        return Risk.LOW_ACTION, "Ordinary non-sensitive text input (L2)."

    # Fallback to L3 for ambiguous actions
    return Risk.CONFIRM, "Ambiguous browser action (defaulting to L3 confirmation)."


def wrap_untrusted_content(text: str, source_type: str = "web") -> str:
    """Wrap untrusted web/DOM content in explicit safety tags to prevent prompt injection."""
    header = f"<untrusted_{source_type}_content>"
    footer = f"</untrusted_{source_type}_content>"
    
    # Clean text of potential tag breakout attempts
    clean_text = text.replace(header, "").replace(footer, "")
    
    return f"{header}\n{clean_text}\n{footer}"

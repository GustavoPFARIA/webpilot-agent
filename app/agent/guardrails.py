"""Deterministic security layer around the model (defense in depth).

The model can be tricked; these checks run in code, after the model decides
and before the browser acts, so a manipulated model still cannot:
  - navigate outside the allow-list (blocks data exfiltration via URLs),
  - see or type raw credentials (secrets travel as {{secret:NAME}} placeholders),
  - pay, buy or delete anything without a human approving it.
Prompt-injection text on pages is also detected and flagged to the model.
Maps to OWASP LLM Top 10 (2025): LLM01 prompt injection, LLM02 sensitive
information disclosure, LLM06 excessive agency.
"""

import re
from urllib.parse import urlparse

from app.browser.page_state import Element

INJECTION_PATTERNS = {
    "asks to ignore instructions": r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all)\b.{0,20}"
    r"\binstructions?\b",
    "claims to be a system message": r"\b(system (prompt|message|override)|you are now|new instructions?)\b",
    "asks for credentials or data": r"\b(send|share|post|reveal|exfiltrate|paste)\b.{0,40}"
    r"\b(password|credentials?|cookies?|tokens?|api key|secret)s?\b",
    "addresses the AI directly": r"\b(ai|assistant|agent|llm|chatbot)s?\b.{0,20}\b(must|should|need to)\b",
}

SENSITIVE_ACTIONS = (
    "place order",
    "pay",
    "buy now",
    "purchase",
    "confirm order",
    "delete",
    "remove account",
    "transfer",
    "unsubscribe",
)
CARD_FIELDS = ("card", "cvv", "cvc", "iban", "cc-number")

SECRET_RE = re.compile(r"\{\{secret:([a-zA-Z0-9_]+)\}\}")


def detect_injection(text: str) -> list[str]:
    low = text.lower()
    return [label for label, pattern in INJECTION_PATTERNS.items() if re.search(pattern, low)]


def check_url(url: str, allowed_domains: list[str]) -> str | None:
    """Return an error message if the agent may not open this URL, else None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Blocked: only http(s) URLs are allowed, got '{parsed.scheme or url}'."
    host = (parsed.hostname or "").lower()
    if any(host == d or host.endswith("." + d) for d in allowed_domains):
        return None
    return f"Blocked: '{host}' is not in the allowed domains ({', '.join(allowed_domains)})."


def approval_reason(action: str, element: Element | None) -> str | None:
    """Why this action needs a human's OK before running (None = safe to run)."""
    if element is None:
        return None
    words = f"{element.text} {element.label} {element.name}".lower()
    if action == "click" and any(w in words for w in SENSITIVE_ACTIONS):
        return f"Clicking '{element.text or element.label}' can spend money or change data."
    if action == "type_text" and any(w in words for w in CARD_FIELDS):
        return "Typing into a payment field."
    return None


def check_typing(element: Element | None, text: str) -> str | None:
    """Passwords may only be typed through a secret placeholder, never as literal text."""
    if element is not None and element.type == "password" and not SECRET_RE.fullmatch(text.strip()):
        return "Blocked: type passwords only as {{secret:NAME}} placeholders."
    return None


def resolve_secrets(text: str, secrets: dict[str, str]) -> str:
    """Swap placeholders for real values right before the browser types them."""

    def sub(m: re.Match) -> str:
        if m.group(1) not in secrets:
            raise KeyError(m.group(1))
        return secrets[m.group(1)]

    return SECRET_RE.sub(sub, text)


def redact(text: str, secrets: dict[str, str]) -> str:
    """Hide secret values if a page echoes them back, before the model sees it."""
    for name, value in secrets.items():
        if value:
            text = text.replace(value, "{{secret:" + name + "}}")
    return text

"""Deterministic security layer around the model (defense in depth).

The model can be tricked; these checks run in code, after the model decides
and before the browser acts, so a manipulated model still cannot:
  - load anything outside the allow-list, by typing a URL, clicking a link,
    submitting a form or following a redirect (enforced on every network
    request, so it also blocks data exfiltration and SSRF),
  - see or type raw credentials (secrets travel as {{secret:NAME}} placeholders),
  - pay, buy or delete anything without a human approving it.
Prompt-injection text on pages is also detected and flagged to the model.
Maps to OWASP LLM Top 10 (2025): LLM01 prompt injection, LLM02 sensitive
information disclosure, LLM06 excessive agency.
"""

import ipaddress
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


def _normalize_host(host: str) -> str:
    host = host.lower().rstrip(".")
    try:
        return host.encode("idna").decode("ascii")  # IDN lookalikes compare as punycode
    except UnicodeError:
        return host


INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
# Special-use TLDs (RFC 2606 / RFC 6761) never exist on the public internet, so no
# legitimate task needs them: they are what attack demos and tests use.
RESERVED_TLDS = (".example", ".invalid", ".test")


def _looks_internal(host: str, ip: object) -> bool:
    """Names that point inside the network, and numeric hosts written in forms a
    browser turns into IPs (http://2130706433/ is 127.0.0.1)."""
    if host == "localhost" or host.endswith(INTERNAL_SUFFIXES) or "." not in host:
        return True
    return ip is None and (re.fullmatch(r"[0-9.]+", host) is not None or host.startswith("0x"))


def check_url(
    url: str,
    allowed_domains: list[str],
    denied_paths: tuple[str, ...] | list[str] = (),
    own_hosts: tuple[str, ...] | list[str] = (),
) -> str | None:
    """Return an error message if the browser may not load this URL, else None.

    Fail-closed: only http(s), only allow-listed hosts (or their subdomains),
    never private/link-local IPs unless listed exactly (SSRF, e.g. cloud metadata
    at 169.254.169.254), and never the app's own internal endpoints.

    "*" in the allow-list is open-web mode: any public site may be opened, but the
    SSRF, scheme and internal-path protections above still apply."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Blocked: only http(s) URLs are allowed, got '{parsed.scheme or url}'."
    host = _normalize_host(parsed.hostname or "")
    allowed = [_normalize_host(d) for d in allowed_domains]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if (
        ip is not None
        and host not in allowed
        and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified)
    ):
        return f"Blocked: '{host}' is a private or internal network address."
    if host not in allowed and _looks_internal(host, ip):
        return f"Blocked: '{host}' is a private or internal network address."
    if host not in allowed and host.endswith(RESERVED_TLDS):
        return f"Blocked: '{host}' is a reserved, non-public domain."
    if "*" not in allowed and not any(host == d or host.endswith("." + d) for d in allowed):
        return f"Blocked: '{host}' is not in the allowed domains ({', '.join(allowed_domains)})."
    # Internal paths belong to THIS app: they apply to its own hosts (loopback and
    # its public address), not to every site on the web that happens to have /api/.
    path = parsed.path or "/"
    own = host in {"localhost", "127.0.0.1", "::1"} or host in {_normalize_host(h) for h in own_hosts}
    if own and any(path.startswith(p) for p in denied_paths):
        return f"Blocked: '{path}' is an internal endpoint the agent may not access."
    return None


def url_policy(allowed_domains: list[str], denied_paths: list[str], public_url: str | None = None):
    """The URL check as a callable, for the browser's network guard."""
    own_hosts = [urlparse(public_url).hostname or ""] if public_url else []
    return lambda url: check_url(url, allowed_domains, denied_paths, own_hosts)


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

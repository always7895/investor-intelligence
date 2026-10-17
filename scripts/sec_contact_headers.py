"""Shared SEC contact/identity header construction (stdlib only, pure).

Reads environment variables ONLY when called, never at import time.
All failures raise SecContactError with fixed messages that never echo
contact, User-Agent or product label values.
"""
from __future__ import annotations

import os
import re

__all__ = [
    "CONTACT_RE",
    "CONTROL_CHARS_RE",
    "SecContactError",
    "sec_identity_headers",
]

CONTACT_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# C0 (incl. NUL/CR/LF), DEL and C1 control characters.
CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Printable ASCII x20-x7e: the real urllib/http.client transport serializes
# header values with a fixed-width codec, so values outside this range can
# never be sent; they are admitted/denied here, before any opener exists.
_PRINTABLE_ASCII_RE = re.compile(r"^[\x20-\x7e]+$")

DEFAULT_PRODUCT = "Investor Intelligence/2.1"

_MISSING_CONTACT_MESSAGE = (
    "SEC_CONTACT_EMAIL must be configured locally as a valid contact address"
)
_OVERRIDE_MESSAGE = "SEC_USER_AGENT must include SEC_CONTACT_EMAIL"
_CONTROL_MESSAGE = "SEC contact or User-Agent must not contain control characters"
_PRODUCT_MESSAGE = "product label must be a non-empty visible label"
_UNADMITTED_MESSAGE = "SEC_IDENTITY_HEADERS_UNADMITTED"


class SecContactError(RuntimeError):
    """Fail-closed SEC contact/header configuration error (no value echo)."""


def _contains_control(value: str) -> bool:
    return CONTROL_CHARS_RE.search(value) is not None


def _transport_admitted(value: str) -> bool:
    """True iff the value is serializable by the real transport: printable
    ASCII x20-x7e with length 1..512, aligning with the existing
    v21._public_request_headers admission."""
    return (1 <= len(value) <= 512
            and _PRINTABLE_ASCII_RE.fullmatch(value) is not None)


def sec_identity_headers(product: str = DEFAULT_PRODUCT) -> dict[str, str]:
    """Return ONLY {'User-Agent', 'From'} from locally configured values.

    Control-character checks run on the RAW values BEFORE any stripping:
    raw contact/override controls raise the fixed CONTROL_MESSAGE, raw
    product controls raise the fixed PRODUCT_MESSAGE; no value is echoed.

    - SEC_CONTACT_EMAIL: raw value must be control-free (NUL/CR/LF/DEL
      rejected without echoing); the stripped value must fullmatch
      CONTACT_RE.
    - SEC_USER_AGENT: optional override; raw value must be control-free,
      then stripped, and must contain the exact contact. Absent override
      uses '<product> <contact>'.
    - product: optional label (default DEFAULT_PRODUCT); raw value must be
      control-free and the stripped value non-empty. Supports a future H6B
      label without changing callers.
    """
    raw_contact = os.getenv("SEC_CONTACT_EMAIL", "")
    if _contains_control(raw_contact):
        raise SecContactError(_CONTROL_MESSAGE)
    contact = raw_contact.strip()
    if not CONTACT_RE.fullmatch(contact):
        raise SecContactError(_MISSING_CONTACT_MESSAGE)
    if _contains_control(product):
        raise SecContactError(_PRODUCT_MESSAGE)
    label = product.strip()
    if not label:
        raise SecContactError(_PRODUCT_MESSAGE)
    raw_override = os.getenv("SEC_USER_AGENT", None)
    if raw_override is not None and _contains_control(raw_override):
        raise SecContactError(_CONTROL_MESSAGE)
    value = f"{label} {contact}" if raw_override is None else raw_override.strip()
    if _contains_control(value):
        raise SecContactError(_CONTROL_MESSAGE)
    if contact not in value:
        raise SecContactError(_OVERRIDE_MESSAGE)
    # Transport-safety admission runs LAST so the raw-control-first,
    # missing, override and product rules above keep their exact messages.
    # Fixed message; nothing is echoed.
    if (not _transport_admitted(contact)
            or not _transport_admitted(value)):
        raise SecContactError(_UNADMITTED_MESSAGE)
    return {"User-Agent": value, "From": contact}

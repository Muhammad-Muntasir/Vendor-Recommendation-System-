"""
PII redaction service for the AI Vendor Recommendation System.

Scans dicts (recursively) for known PII field names and value patterns,
replacing them with ``"[REDACTED]"``.  Always returns a deep copy of the
input so the original dict is preserved for the unmasked S3 write.

PII field name patterns (case-insensitive substring match):
  - ``email``
  - ``phone``
  - ``address``
  - ``name``

PII value regex patterns:
  - Email addresses  (RFC 5321-ish)
  - Phone numbers    (common North-American and international formats)

Requirements: 6.4, 6.8
"""

from __future__ import annotations

import copy
import re
from typing import Any

# ---------------------------------------------------------------------------
# PII detection configuration
# ---------------------------------------------------------------------------

# Field name substrings that indicate PII (case-insensitive)
_PII_FIELD_SUBSTRINGS: tuple[str, ...] = (
    "email",
    "phone",
    "address",
    "name",
)

# Compiled regex patterns for detecting PII in string values
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_PHONE_RE = re.compile(
    r"""
    (?:
        \+?1[\s.\-]?          # optional country code +1
    )?
    (?:
        \(?\d{3}\)?           # area code (optional parens)
        [\s.\-]?
    )
    \d{3}                     # exchange
    [\s.\-]?
    \d{4}                     # subscriber
    """,
    re.VERBOSE,
)

_REDACTED = "[REDACTED]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mask(data: dict[str, Any]) -> dict[str, Any]:
    """
    Return a deep copy of *data* with PII values replaced by ``"[REDACTED]"``.

    The original dict is **not** modified — callers should use the original
    for the unmasked S3 write and the returned copy for DynamoDB.

    Masking rules applied recursively:
    1. If a dict key contains a known PII substring (case-insensitive), its
       value is replaced with ``"[REDACTED]"`` regardless of the value type.
    2. If a string value matches an email or phone number regex pattern, the
       matching portion is replaced with ``"[REDACTED]"``.

    Args:
        data: Input dict (may contain nested dicts, lists, and scalars).

    Returns:
        A new dict with PII values redacted.
    """
    cloned = copy.deepcopy(data)
    return _mask_dict(cloned)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_pii_field(key: str) -> bool:
    """Return True if *key* contains a known PII field name substring."""
    lower = key.lower()
    return any(sub in lower for sub in _PII_FIELD_SUBSTRINGS)


def _mask_value(value: Any) -> Any:
    """Redact PII patterns within a scalar value (strings only)."""
    if not isinstance(value, str):
        return value
    # Replace email addresses first, then phone numbers
    value = _EMAIL_RE.sub(_REDACTED, value)
    value = _PHONE_RE.sub(_REDACTED, value)
    return value


def _mask_dict(obj: Any) -> Any:
    """Recursively walk *obj* and apply PII masking in-place."""
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            if _is_pii_field(str(key)):
                obj[key] = _REDACTED
            else:
                obj[key] = _mask_dict(obj[key])
        return obj
    elif isinstance(obj, list):
        return [_mask_dict(item) for item in obj]
    else:
        return _mask_value(obj)

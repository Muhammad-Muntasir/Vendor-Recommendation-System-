"""
Input validation helpers for the AI Vendor Recommendation System.

Provides three public validation functions:

  - validate_job_event(event: dict) -> JobEvent
  - validate_vendor_profile(profile: dict) -> VendorProfile
  - validate_override_request(body: dict) -> OverrideRequest

Each function raises :class:`ValidationError` with field-level detail when
the supplied dict is missing required fields or contains invalid values.

``JobEvent`` and ``VendorProfile`` live in ``backend/lambda/models/``.
Because ``lambda`` is a Python reserved keyword the package cannot be
imported with a plain ``import`` statement; ``importlib.import_module`` is
used instead.

Requirements: 4.7, 5.3, 5.4, 18.1, 18.2
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Lazy model imports (lambda is a reserved keyword — use importlib)
# ---------------------------------------------------------------------------

_job_mod = importlib.import_module("backend.lambda.models.job")
JobEvent = _job_mod.JobEvent

_vendor_mod = importlib.import_module("backend.lambda.models.vendor")
VendorProfile = _vendor_mod.VendorProfile


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """
    Raised when a validation function detects one or more invalid fields.

    Attributes:
        fields: Mapping of field name → human-readable error description.
    """

    def __init__(self, fields: dict[str, str]) -> None:
        self.fields: dict[str, str] = fields
        # Build a readable summary for the exception message
        detail = "; ".join(f"{k}: {v}" for k, v in fields.items())
        super().__init__(f"Validation failed — {detail}")


# ---------------------------------------------------------------------------
# OverrideRequest dataclass
# ---------------------------------------------------------------------------


@dataclass
class OverrideRequest:
    """Validated override request payload."""

    jobId: str
    vendorId: str
    overrideReason: str
    userId: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_OVERRIDE_REASON_MIN = 10
_OVERRIDE_REASON_MAX = 500


def _collect_missing(data: dict[str, Any], required_fields: list[str]) -> dict[str, str]:
    """Return a dict of field → error message for any missing/null required fields."""
    errors: dict[str, str] = {}
    for field in required_fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            errors[field] = "required field is missing or null"
    return errors


# ---------------------------------------------------------------------------
# Public validation functions
# ---------------------------------------------------------------------------


def validate_job_event(event: dict[str, Any]) -> "JobEvent":
    """
    Validate a raw event dict and return a :class:`JobEvent` instance.

    All required fields must be present and non-null.  The ``urgency`` and
    ``status`` values are validated by the :class:`JobEvent` dataclass itself.

    Args:
        event: Raw dict (e.g. parsed from an SQS message body).

    Returns:
        A fully-populated :class:`JobEvent` instance.

    Raises:
        ValidationError: If any required field is absent, null, or invalid.
    """
    required = ["jobId", "type", "location", "urgency", "slaDeadline", "description", "createdAt"]
    errors = _collect_missing(event, required)
    if errors:
        raise ValidationError(errors)

    # Attempt to construct the dataclass; it performs additional validation
    # (urgency enum, status enum).
    try:
        return JobEvent(
            jobId=event["jobId"],
            type=event["type"],
            location=event["location"],
            urgency=event["urgency"],
            slaDeadline=event["slaDeadline"],
            description=event["description"],
            createdAt=event["createdAt"],
            schemaVersion=event.get("schemaVersion", "1.0"),
            status=event.get("status", "Pending"),
        )
    except ValueError as exc:
        # Map dataclass ValueError back to ValidationError
        raise ValidationError({"_model": str(exc)}) from exc


def validate_vendor_profile(profile: dict[str, Any]) -> "VendorProfile":
    """
    Validate a raw profile dict and return a :class:`VendorProfile` instance.

    All required fields must be present and non-null.  Range and enum
    constraints are enforced by the :class:`VendorProfile` dataclass.

    Args:
        profile: Raw dict (e.g. a DynamoDB item).

    Returns:
        A fully-populated :class:`VendorProfile` instance.

    Raises:
        ValidationError: If any required field is absent, null, or invalid.
    """
    required = [
        "vendorId",
        "name",
        "completionRate",
        "availability",
        "reworkRate",
        "location",
        "specializations",
        "avgResponseTime",
        "slaBreachCount",
        "activeJobs",
    ]
    errors = _collect_missing(profile, required)
    if errors:
        raise ValidationError(errors)

    try:
        return VendorProfile(
            vendorId=profile["vendorId"],
            name=profile["name"],
            completionRate=float(profile["completionRate"]),
            availability=profile["availability"],
            reworkRate=float(profile["reworkRate"]),
            location=profile["location"],
            specializations=list(profile["specializations"]),
            avgResponseTime=float(profile["avgResponseTime"]),
            slaBreachCount=int(profile["slaBreachCount"]),
            activeJobs=int(profile["activeJobs"]),
        )
    except (ValueError, TypeError) as exc:
        raise ValidationError({"_model": str(exc)}) from exc


def validate_override_request(body: dict[str, Any]) -> OverrideRequest:
    """
    Validate a raw override request body and return an :class:`OverrideRequest`.

    Validates:
      - ``jobId``          — required, non-null
      - ``vendorId``       — required, non-null
      - ``overrideReason`` — required, 10–500 characters
      - ``userId``         — required, non-null

    Args:
        body: Raw dict from the HTTP request body.

    Returns:
        A fully-populated :class:`OverrideRequest` instance.

    Raises:
        ValidationError: If any field is absent, null, or fails length validation.
    """
    required = ["jobId", "vendorId", "overrideReason", "userId"]
    errors = _collect_missing(body, required)

    # Additional length validation for overrideReason (only when present)
    reason: Any = body.get("overrideReason")
    if reason is not None and isinstance(reason, str) and reason.strip():
        reason_len = len(reason)
        if reason_len < _OVERRIDE_REASON_MIN:
            errors["overrideReason"] = (
                f"must be at least {_OVERRIDE_REASON_MIN} characters "
                f"(got {reason_len})"
            )
        elif reason_len > _OVERRIDE_REASON_MAX:
            errors["overrideReason"] = (
                f"must be at most {_OVERRIDE_REASON_MAX} characters "
                f"(got {reason_len})"
            )

    if errors:
        raise ValidationError(errors)

    return OverrideRequest(
        jobId=str(body["jobId"]),
        vendorId=str(body["vendorId"]),
        overrideReason=str(body["overrideReason"]),
        userId=str(body["userId"]),
    )

"""
Auth handler for the AI Vendor Recommendation System.

Handles Cognito PostConfirmation_ConfirmSignUp trigger events.

Requirements: 7.6
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Internal imports via importlib (``lambda`` is a Python reserved keyword)
# ---------------------------------------------------------------------------

_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)

_dynamodb_mod = importlib.import_module("backend.lambda.services.dynamodb")

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

_USERS_TABLE_ENV = "USERS_TABLE"


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------


def handle(event: dict, context) -> dict:
    """
    Handle Cognito PostConfirmation_ConfirmSignUp trigger.

    Creates a User record in DynamoDB USERS_TABLE with:
      - userId  (from event["request"]["userAttributes"]["sub"])
      - email   (from event["request"]["userAttributes"]["email"])
      - createdAt (ISO 8601 UTC)

    Uses put_item with overwrite=False so the write is idempotent —
    if the record already exists the error is swallowed and the event
    is returned unchanged.

    Returns the Cognito event dict unchanged (required by Cognito trigger
    contract).
    """
    try:
        user_attributes = event.get("request", {}).get("userAttributes", {})
        user_id = user_attributes.get("sub", "")
        email = user_attributes.get("email", "")
        created_at = datetime.now(timezone.utc).isoformat()

        users_table = os.environ.get(_USERS_TABLE_ENV, "Users")

        user_record = {
            "userId": user_id,
            "email": email,
            "createdAt": created_at,
        }

        try:
            _dynamodb_mod.put_item(users_table, user_record, overwrite=False)
            _logger.info("Created user record for userId='%s'", user_id)
        except _dynamodb_mod.DynamoDBWriteError as exc:
            # Item already exists — idempotent, skip silently
            _logger.info(
                "User record for userId='%s' already exists (skipping): %s",
                user_id,
                exc,
            )

    except Exception as exc:  # noqa: BLE001
        # Log but do not raise — Cognito requires the event to be returned
        _logger.error(
            "Unexpected error in auth handler for event '%s': %s",
            event.get("triggerSource"),
            exc,
        )

    # Always return the event unchanged (Cognito trigger contract)
    return event

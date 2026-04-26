"""
Lambda event router — inspects incoming events and dispatches to the right handler.

This is the central dispatch table for the single-Lambda architecture.
All event sources (API Gateway, SQS, Cognito, EventBridge) arrive at
handler.lambda_handler() and are immediately forwarded here.

Routing logic (checked in priority order):
  1. Cognito trigger  → triggerSource == "PostConfirmation_ConfirmSignUp"
                        → handlers/auth.py (creates User record in DynamoDB)

  2. API Gateway      → httpMethod field is present
                        → POST /override → handlers/override.py
                        → all other paths → handlers/query.py

  3. SQS              → Records[0].eventSource == "aws:sqs"
                        → handlers/job_created.py (scoring pipeline)

  4. EventBridge      → source field is present
                        → logged and ignored (events are handled via SQS)

  5. Unknown          → logged as warning, returns empty dict

All handler modules are imported lazily via importlib (not at module level)
because ``lambda`` is a Python reserved keyword and cannot appear in a
standard import path.

Requirements: 4.1
"""

from __future__ import annotations

import importlib
import json

# ── Logger setup ──────────────────────────────────────────────────────────────
# Use importlib because "backend.lambda.utils.logger" contains the reserved
# keyword "lambda" in the package path
_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)


# ── Helper ────────────────────────────────────────────────────────────────────

def _api_response(status_code: int, body_dict: dict) -> dict:
    """
    Build a standard API Gateway proxy response dict.

    All HTTP responses from this Lambda must follow this format for API Gateway
    to correctly forward them to the client.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            # CORS header — allows the React frontend to call the API
            # In production, API Gateway enforces the explicit allowed_cors_origin
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body_dict),
    }


# ── Public router ─────────────────────────────────────────────────────────────

def route(event: dict, context) -> dict:
    """
    Inspect the event structure and dispatch to the correct handler module.

    Args:
        event:   Raw Lambda event dict from AWS.
        context: Lambda context object (passed through to handlers).

    Returns:
        API Gateway response dict for HTTP events; plain dict for async events.
    """
    try:
        # ── 1. Cognito Post-Confirmation trigger ──────────────────────────────
        # Cognito calls Lambda after a user confirms their email address.
        # The handler creates a User record in DynamoDB and returns the event
        # unchanged (required by the Cognito trigger contract).
        if event.get("triggerSource") == "PostConfirmation_ConfirmSignUp":
            _logger.info("router: dispatching to auth handler (Cognito trigger)")
            _auth_mod = importlib.import_module("backend.lambda.handlers.auth")
            return _auth_mod.handle(event, context)

        # ── 2. API Gateway HTTP event ─────────────────────────────────────────
        # API Gateway proxy integration sends all HTTP requests here.
        # The httpMethod field distinguishes HTTP events from other sources.
        if event.get("httpMethod"):
            path = event.get("path", "")
            http_method = event.get("httpMethod", "").upper()
            _logger.info("router: API Gateway %s %s", http_method, path)

            # POST /override has its own dedicated handler for clarity
            if http_method == "POST" and path == "/override":
                _override_mod = importlib.import_module("backend.lambda.handlers.override")
                return _override_mod.handle(event, context)

            # All other HTTP routes (GET /jobs, POST /jobs, GET /recommendations, etc.)
            # are handled by the query handler which dispatches by path
            _query_mod = importlib.import_module("backend.lambda.handlers.query")
            return _query_mod.handle(event, context)

        # ── 3. SQS event ──────────────────────────────────────────────────────
        # EventBridge routes JobCreated_Event → SQS → Lambda.
        # The SQS trigger sends a batch of records (batch_size=1 in Terraform).
        records = event.get("Records")
        if records and isinstance(records, list) and len(records) > 0:
            first_record = records[0]
            if first_record.get("eventSource") == "aws:sqs":
                _logger.info("router: SQS event → job_created handler")
                _job_created_mod = importlib.import_module(
                    "backend.lambda.handlers.job_created"
                )
                return _job_created_mod.handle(event, context)

        # ── 4. EventBridge direct event ───────────────────────────────────────
        # Some EventBridge rules target Lambda directly (not via SQS).
        # These are logged for observability but not processed — the scoring
        # pipeline is triggered exclusively via SQS for reliability.
        if event.get("source"):
            _logger.info(
                "router: EventBridge event source='%s' detail-type='%s' — no action",
                event.get("source"),
                event.get("detail-type"),
            )
            return {}

        # ── 5. Unknown event type ─────────────────────────────────────────────
        # Log the event keys to help diagnose unexpected invocations
        _logger.warning(
            "router: unrecognised event structure — keys: %s",
            list(event.keys()),
        )
        return {}

    except Exception as exc:  # noqa: BLE001
        # Catch-all: return HTTP 500 for API Gateway events, empty dict for others
        _logger.error("router: unhandled exception: %s", exc)
        return _api_response(500, {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
            }
        })

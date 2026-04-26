"""
AWS Secrets Manager cache for the AI Vendor Recommendation System.

Fetches the Gemini API key from Secrets Manager on the first call and caches
it in a module-level variable for the lifetime of the Lambda invocation
(warm-start reuse).

The secret name is read from the ``GEMINI_SECRET_NAME`` environment variable
(default: ``"ai-vrs/gemini-api-key"``).

Requirements: 15.4
"""

from __future__ import annotations

import importlib
import os
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# ``lambda`` is a Python reserved keyword — use importlib for internal imports
_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class SecretFetchError(Exception):
    """Raised when the Gemini API key cannot be retrieved from Secrets Manager."""


# ---------------------------------------------------------------------------
# Module-level cache — populated on first call, reused on warm invocations
# ---------------------------------------------------------------------------

_cached_api_key: Optional[str] = None

_DEFAULT_SECRET_NAME = "ai-vrs/gemini-api-key"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_gemini_api_key() -> str:
    """
    Return the Gemini API key, fetching it from Secrets Manager if needed.

    On the first call within a Lambda invocation the key is fetched from
    AWS Secrets Manager using the secret name in ``GEMINI_SECRET_NAME``
    (default: ``"ai-vrs/gemini-api-key"``).  Subsequent calls within the
    same invocation return the cached value without making an API request.

    Returns:
        The Gemini API key string.

    Raises:
        SecretFetchError: If the secret cannot be retrieved for any reason.
    """
    global _cached_api_key

    if _cached_api_key is not None:
        return _cached_api_key

    _cached_api_key = _fetch_secret()
    return _cached_api_key


def _fetch_secret() -> str:
    """Fetch the secret value from AWS Secrets Manager."""
    secret_name = os.environ.get("GEMINI_SECRET_NAME", _DEFAULT_SECRET_NAME)

    try:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        _logger.error(
            "Failed to fetch secret '%s' from Secrets Manager (code=%s): %s",
            secret_name,
            error_code,
            exc,
        )
        raise SecretFetchError(
            f"Could not retrieve secret '{secret_name}': {error_code}"
        ) from exc
    except BotoCoreError as exc:
        _logger.error(
            "BotoCoreError while fetching secret '%s': %s", secret_name, exc
        )
        raise SecretFetchError(
            f"Could not retrieve secret '{secret_name}': {exc}"
        ) from exc

    # Secrets Manager returns either SecretString or SecretBinary
    secret_value: Optional[str] = response.get("SecretString")
    if not secret_value:
        raise SecretFetchError(
            f"Secret '{secret_name}' exists but contains no SecretString value"
        )

    return secret_value.strip()


def _reset_cache() -> None:
    """
    Reset the module-level cache.

    Intended for use in tests only — allows each test to exercise the
    cold-start fetch path without module reload.
    """
    global _cached_api_key
    _cached_api_key = None

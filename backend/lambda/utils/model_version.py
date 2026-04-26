"""
S3-backed model version cache for the AI Vendor Recommendation System.

Reads ``model-version.txt`` from the Lambda zip S3 bucket on the first call
and caches the result in a module-level variable for the lifetime of the
Lambda invocation (warm-start reuse).

The S3 bucket name is read from the ``LAMBDA_ZIP_BUCKET`` environment
variable.  The S3 key is always ``model-version.txt``.

Fallback behaviour:
  - If the S3 read fails for any reason, ``"0.0.0"`` is returned and a
    warning is logged.
  - If the version string does not match semantic versioning format
    (``MAJOR.MINOR.PATCH``), ``"0.0.0"`` is returned and a warning is
    logged.

Requirements: 14.1, 14.3, 14.4
"""

from __future__ import annotations

import importlib
import os
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# ``lambda`` is a Python reserved keyword so ``backend.lambda`` cannot be
# imported with a plain ``import`` statement; use importlib instead.
_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache — populated on first call, reused on warm invocations
# ---------------------------------------------------------------------------
_cached_version: str | None = None

# Semantic versioning pattern: MAJOR.MINOR.PATCH (integers only)
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

_FALLBACK_VERSION = "0.0.0"
_S3_KEY = "model-version.txt"


def get_model_version() -> str:
    """
    Return the current model version string.

    On the first call within a Lambda invocation the version is read from
    ``s3://<LAMBDA_ZIP_BUCKET>/model-version.txt`` and cached.  Subsequent
    calls within the same invocation return the cached value without making
    an S3 request.

    Returns:
        A semantic version string in ``MAJOR.MINOR.PATCH`` format, or
        ``"0.0.0"`` if the S3 read fails or the stored value is invalid.
    """
    global _cached_version

    if _cached_version is not None:
        return _cached_version

    _cached_version = _read_version_from_s3()
    return _cached_version


def _read_version_from_s3() -> str:
    """Fetch and validate the version string from S3."""
    bucket = os.environ.get("LAMBDA_ZIP_BUCKET", "")
    if not bucket:
        _logger.warning(
            "LAMBDA_ZIP_BUCKET environment variable is not set; "
            "falling back to model version '%s'",
            _FALLBACK_VERSION,
        )
        return _FALLBACK_VERSION

    try:
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=bucket, Key=_S3_KEY)
        raw: str = response["Body"].read().decode("utf-8").strip()
    except (ClientError, BotoCoreError, Exception) as exc:  # noqa: BLE001
        _logger.warning(
            "Failed to read model version from s3://%s/%s: %s; "
            "falling back to '%s'",
            bucket,
            _S3_KEY,
            exc,
            _FALLBACK_VERSION,
        )
        return _FALLBACK_VERSION

    return _validate_semver(raw, bucket)


def _validate_semver(version: str, bucket: str) -> str:
    """Return *version* if it matches MAJOR.MINOR.PATCH, else the fallback."""
    if _SEMVER_RE.match(version):
        return version

    _logger.warning(
        "Model version '%s' read from s3://%s/%s does not match "
        "semantic versioning format (MAJOR.MINOR.PATCH); "
        "falling back to '%s'",
        version,
        bucket,
        _S3_KEY,
        _FALLBACK_VERSION,
    )
    return _FALLBACK_VERSION


def _reset_cache() -> None:
    """
    Reset the module-level cache.

    Intended for use in tests only — allows each test to exercise the
    cold-start S3 read path without module reload.
    """
    global _cached_version
    _cached_version = None

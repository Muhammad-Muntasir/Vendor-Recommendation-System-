"""
S3 wrapper service for the AI Vendor Recommendation System.

Provides typed helpers around the boto3 S3 client for reading and writing
objects.  All writes use SSE-S3 server-side encryption by default.

Used for:
  - Model version reads (``model-version.txt``)
  - Audit log writes (unmasked, SSE-S3 encrypted)
  - Override feedback writes

Requirements: 6.5, 6.8, 14.1, 17.1
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# ``lambda`` is a Python reserved keyword — use importlib for internal imports
_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level client (reused across warm invocations)
# ---------------------------------------------------------------------------

_s3_client = None


def _get_client():
    """Return (and lazily create) the module-level S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def read_object(bucket: str, key: str) -> str:
    """
    Read a text object from S3 and return its content as a string.

    Args:
        bucket: S3 bucket name.
        key:    S3 object key.

    Returns:
        The object body decoded as UTF-8.

    Raises:
        ClientError: If the object does not exist or access is denied.
        BotoCoreError: On low-level AWS SDK errors.
    """
    try:
        response = _get_client().get_object(Bucket=bucket, Key=key)
        return response["Body"].read().decode("utf-8")
    except (ClientError, BotoCoreError) as exc:
        _logger.error("S3 read_object failed for s3://%s/%s: %s", bucket, key, exc)
        raise


def write_object(bucket: str, key: str, body: str) -> None:
    """
    Write a UTF-8 string to S3 with SSE-S3 server-side encryption.

    Args:
        bucket: S3 bucket name.
        key:    S3 object key.
        body:   String content to write.

    Raises:
        ClientError: On S3 API errors.
        BotoCoreError: On low-level AWS SDK errors.
    """
    try:
        _get_client().put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ServerSideEncryption="AES256",
            ContentType="text/plain; charset=utf-8",
        )
    except (ClientError, BotoCoreError) as exc:
        _logger.error("S3 write_object failed for s3://%s/%s: %s", bucket, key, exc)
        raise


def write_json_object(bucket: str, key: str, data: dict[str, Any]) -> None:
    """
    Serialise *data* as JSON and write it to S3 with SSE-S3 encryption.

    Args:
        bucket: S3 bucket name.
        key:    S3 object key.
        data:   Dict to serialise and write.

    Raises:
        ClientError: On S3 API errors.
        BotoCoreError: On low-level AWS SDK errors.
    """
    try:
        body = json.dumps(data, default=str)
        _get_client().put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ServerSideEncryption="AES256",
            ContentType="application/json",
        )
    except (ClientError, BotoCoreError) as exc:
        _logger.error("S3 write_json_object failed for s3://%s/%s: %s", bucket, key, exc)
        raise

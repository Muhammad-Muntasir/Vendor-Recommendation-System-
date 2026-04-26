"""
Dual-write audit logger for the AI Vendor Recommendation System.

Every AI decision and human override is recorded to:
  1. DynamoDB AuditLog table  — PII-masked, with retry (3x, exponential backoff)
  2. S3 logs bucket           — unmasked, SSE-S3 encrypted

CloudWatch metric ``RecommendationConfidenceDistribution`` is emitted after
each AI recommendation log.

Environment variables:
  - ``AUDIT_LOG_TABLE``  — DynamoDB table name for audit records
  - ``LOGS_BUCKET``      — S3 bucket name for unmasked audit records

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 17.2
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# ---------------------------------------------------------------------------
# Internal imports via importlib (``lambda`` is a reserved keyword)
# ---------------------------------------------------------------------------

_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)

_audit_log_mod = importlib.import_module("backend.lambda.models.audit_log")
AuditLog = _audit_log_mod.AuditLog

_score_mod = importlib.import_module("backend.lambda.models.score")
ScoreFactors = _score_mod.ScoreFactors
Recommendation = _score_mod.Recommendation

_job_mod = importlib.import_module("backend.lambda.models.job")
JobEvent = _job_mod.JobEvent

_pii_masker_mod = importlib.import_module("backend.lambda.services.pii_masker")
_dynamodb_mod = importlib.import_module("backend.lambda.services.dynamodb")
_s3_mod = importlib.import_module("backend.lambda.services.s3")

DynamoDBWriteError = _dynamodb_mod.DynamoDBWriteError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_AUDIT_LOG_TABLE_ENV = "AUDIT_LOG_TABLE"
_LOGS_BUCKET_ENV = "LOGS_BUCKET"
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5  # seconds; actual wait = _BACKOFF_BASE * 2^attempt

# CloudWatch namespace for custom metrics
_CW_NAMESPACE = "AI-VRS"
_CW_METRIC_CONFIDENCE = "RecommendationConfidenceDistribution"


# ---------------------------------------------------------------------------
# Module-level CloudWatch client (reused across warm invocations)
# ---------------------------------------------------------------------------

_cw_client = None


def _get_cw_client():
    global _cw_client
    if _cw_client is None:
        _cw_client = boto3.client("cloudwatch")
    return _cw_client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_recommendation(
    job: "JobEvent",
    ranked_vendors: list["ScoreFactors"],
    model_version: str,
    ai_unavailable: bool,
) -> str:
    """
    Assemble and persist an audit record for a vendor recommendation event.

    Args:
        job:             The originating ``JobEvent``.
        ranked_vendors:  Ranked list of ``ScoreFactors`` (top 5).
        model_version:   Model version string used for this recommendation.
        ai_unavailable:  ``True`` when the Gemini API was unavailable and the
                         fallback scorer was used.

    Returns:
        The ``logId`` UUID string of the created record.
    """
    action = "FALLBACK_RECOMMENDATION" if ai_unavailable else "AI_RECOMMENDATION"
    top_vendor_id = ranked_vendors[0].vendorId if ranked_vendors else ""
    confidence = ranked_vendors[0].confidence if ranked_vendors else "Low"

    input_data: dict[str, Any] = {
        "job": dataclasses.asdict(job),
        "vendorCount": len(ranked_vendors),
    }
    output_data: dict[str, Any] = {
        "rankedVendors": [dataclasses.asdict(sf) for sf in ranked_vendors],
        "confidence": confidence,
        "aiUnavailable": ai_unavailable,
    }

    log_id = _write_audit_log(
        job_id=job.jobId,
        vendor_id=top_vendor_id,
        action=action,
        input_data=input_data,
        output_data=output_data,
        override_reason=None,
        model_version=model_version,
        ai_unavailable=ai_unavailable,
    )

    # Emit CloudWatch metric for confidence distribution
    if not ai_unavailable:
        _emit_confidence_metric(confidence)

    return log_id


def log_override(
    job: "JobEvent",
    original_recommendation: list["ScoreFactors"],
    selected_vendor_id: str,
    reason: str,
    user_id: str,
    model_version: str,
) -> str:
    """
    Assemble and persist an audit record for an admin override event.

    Args:
        job:                     The originating ``JobEvent``.
        original_recommendation: The original ranked ``ScoreFactors`` list.
        selected_vendor_id:      The vendor ID chosen by the admin.
        reason:                  Override reason text (10–500 chars).
        user_id:                 Cognito user ID of the admin.
        model_version:           Model version string.

    Returns:
        The ``logId`` UUID string of the created record.
    """
    input_data: dict[str, Any] = {
        "job": dataclasses.asdict(job),
        "originalRankedVendors": [dataclasses.asdict(sf) for sf in original_recommendation],
        "userId": user_id,
    }
    output_data: dict[str, Any] = {
        "selectedVendorId": selected_vendor_id,
        "overrideReason": reason,
    }

    return _write_audit_log(
        job_id=job.jobId,
        vendor_id=selected_vendor_id,
        action="ADMIN_OVERRIDE",
        input_data=input_data,
        output_data=output_data,
        override_reason=reason,
        model_version=model_version,
        ai_unavailable=None,
    )


def log_acceptance(
    job: "JobEvent",
    recommendation: "Recommendation",
    model_version: str,
) -> str:
    """
    Assemble and persist an audit record for an AI recommendation acceptance.

    Args:
        job:             The originating ``JobEvent``.
        recommendation:  The accepted ``Recommendation`` record.
        model_version:   Model version string.

    Returns:
        The ``logId`` UUID string of the created record.
    """
    input_data: dict[str, Any] = {
        "job": dataclasses.asdict(job),
    }
    output_data: dict[str, Any] = {
        "acceptedVendorId": recommendation.vendorId,
        "rank": recommendation.rank,
        "confidence": recommendation.confidence,
        "rationale": recommendation.rationale,
        "isAIGenerated": recommendation.isAIGenerated,
    }

    return _write_audit_log(
        job_id=job.jobId,
        vendor_id=recommendation.vendorId,
        action="AI_RECOMMENDATION_ACCEPTED",
        input_data=input_data,
        output_data=output_data,
        override_reason=None,
        model_version=model_version,
        ai_unavailable=None,
    )


def log_dlq_failure(
    job_id: str,
    reason: str,
    timestamp: str,
) -> str:
    """
    Assemble and persist an audit record for a DLQ failure event.

    Args:
        job_id:    The job ID from the failed message (may be empty string
                   if the message was malformed).
        reason:    Human-readable failure reason.
        timestamp: ISO 8601 timestamp of the failure.

    Returns:
        The ``logId`` UUID string of the created record.
    """
    input_data: dict[str, Any] = {
        "jobId": job_id,
        "failureTimestamp": timestamp,
    }
    output_data: dict[str, Any] = {
        "reason": reason,
    }

    return _write_audit_log(
        job_id=job_id,
        vendor_id="",
        action="DLQ_FAILURE",
        input_data=input_data,
        output_data=output_data,
        override_reason=None,
        model_version="0.0.0",
        ai_unavailable=None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_audit_log(
    *,
    job_id: str,
    vendor_id: str,
    action: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    override_reason: Optional[str],
    model_version: str,
    ai_unavailable: Optional[bool],
) -> str:
    """
    Assemble an ``AuditLog`` record, mask PII, and persist to DynamoDB + S3.

    Returns the ``logId`` of the created record.
    """
    log_id = str(uuid.uuid4())
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    # Build the unmasked record (used for S3 write)
    unmasked_input = input_data
    unmasked_output = output_data

    # Mask PII for DynamoDB write
    masked_input = _pii_masker_mod.mask(unmasked_input)
    masked_output = _pii_masker_mod.mask(unmasked_output)

    audit_log = AuditLog(
        logId=log_id,
        jobId=job_id,
        vendorId=vendor_id,
        action=action,
        input=masked_input,
        output=masked_output,
        overrideReason=override_reason,
        modelVersion=model_version,
        piiMasked=True,
        timestamp=timestamp,
        aiUnavailable=ai_unavailable,
    )

    # Persist to DynamoDB with retry
    _write_to_dynamodb_with_retry(audit_log)

    # Persist unmasked record to S3
    _write_to_s3(
        log_id=log_id,
        job_id=job_id,
        action=action,
        timestamp=timestamp,
        unmasked_input=unmasked_input,
        unmasked_output=unmasked_output,
        override_reason=override_reason,
        model_version=model_version,
        ai_unavailable=ai_unavailable,
    )

    return log_id


def _write_to_dynamodb_with_retry(audit_log: "AuditLog") -> None:
    """Write *audit_log* to DynamoDB, retrying up to ``_MAX_RETRIES`` times."""
    table = os.environ.get(_AUDIT_LOG_TABLE_ENV, "")
    if not table:
        _logger.warning(
            "AUDIT_LOG_TABLE env var not set; skipping DynamoDB write for logId=%s",
            audit_log.logId,
        )
        return

    item = dataclasses.asdict(audit_log)

    # DynamoDB requires Decimal for float values — convert recursively
    from decimal import Decimal

    def _to_decimal(obj):
        if isinstance(obj, float):
            return Decimal(str(round(obj, 6)))
        if isinstance(obj, dict):
            return {k: _to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_to_decimal(i) for i in obj]
        return obj

    item = _to_decimal(item)

    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            _dynamodb_mod.put_item(table, item, overwrite=True)
            return
        except DynamoDBWriteError as exc:
            last_exc = exc
            wait = _BACKOFF_BASE * (2 ** attempt)
            _logger.warning(
                "DynamoDB write failed for logId=%s (attempt %d/%d): %s; "
                "retrying in %.1fs",
                audit_log.logId,
                attempt + 1,
                _MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)

    # All retries exhausted — log to CloudWatch and continue
    _logger.error(
        "DynamoDB write exhausted all %d retries for logId=%s: %s",
        _MAX_RETRIES,
        audit_log.logId,
        last_exc,
    )


def _write_to_s3(
    *,
    log_id: str,
    job_id: str,
    action: str,
    timestamp: str,
    unmasked_input: dict[str, Any],
    unmasked_output: dict[str, Any],
    override_reason: Optional[str],
    model_version: str,
    ai_unavailable: Optional[bool],
) -> None:
    """Write the unmasked audit record to S3 with SSE-S3 encryption."""
    bucket = os.environ.get(_LOGS_BUCKET_ENV, "")
    if not bucket:
        _logger.warning(
            "LOGS_BUCKET env var not set; skipping S3 write for logId=%s", log_id
        )
        return

    # Partition by date: year/month/day/action/logId.json
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    key = (
        f"audit-logs/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/"
        f"{action}/{log_id}.json"
    )

    record: dict[str, Any] = {
        "logId": log_id,
        "jobId": job_id,
        "action": action,
        "timestamp": timestamp,
        "modelVersion": model_version,
        "piiMasked": False,
        "input": unmasked_input,
        "output": unmasked_output,
        "overrideReason": override_reason,
        "aiUnavailable": ai_unavailable,
    }

    try:
        _s3_mod.write_json_object(bucket, key, record)
    except (ClientError, BotoCoreError, Exception) as exc:  # noqa: BLE001
        _logger.error(
            "S3 write failed for logId=%s at s3://%s/%s: %s",
            log_id,
            bucket,
            key,
            exc,
        )


def _emit_confidence_metric(confidence: str) -> None:
    """Emit the ``RecommendationConfidenceDistribution`` CloudWatch metric."""
    try:
        _get_cw_client().put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": _CW_METRIC_CONFIDENCE,
                    "Dimensions": [
                        {"Name": "ConfidenceLevel", "Value": confidence},
                    ],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except (ClientError, BotoCoreError, Exception) as exc:  # noqa: BLE001
        _logger.warning(
            "Failed to emit CloudWatch metric '%s': %s",
            _CW_METRIC_CONFIDENCE,
            exc,
        )

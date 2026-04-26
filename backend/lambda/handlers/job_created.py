"""
Job-created event handler for the AI Vendor Recommendation System.

Handles SQS-delivered JobCreated_Event messages routed from router.py.

Requirements: 1.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 18.5, 19.5, 19.7
"""

from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone

import boto3

# ---------------------------------------------------------------------------
# Internal imports via importlib (``lambda`` is a Python reserved keyword)
# ---------------------------------------------------------------------------

_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)

_validator_mod = importlib.import_module("backend.lambda.utils.validator")
_vendor_scoring_mod = importlib.import_module("backend.lambda.handlers.vendor_scoring")
_recommendation_mod = importlib.import_module("backend.lambda.handlers.recommendation")
_audit_logger_mod = importlib.import_module("backend.lambda.services.audit_logger")

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

_EVENTBRIDGE_BUS_NAME_ENV = "EVENTBRIDGE_BUS_NAME"


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------


def handle(event: dict, context) -> dict:
    """
    Handle SQS-delivered JobCreated_Event messages.

    For each SQS record:
      1. Parse the message body and extract the ``detail`` field as the JobEvent.
      2. Validate via validator.validate_job_event(); on failure call
         audit_logger.log_dlq_failure() then re-raise (SQS routes to DLQ).
      3. Orchestrate the scoring pipeline:
         a. vendor_scoring.score_vendors(job) → (ranked_score_factors, confidence)
         b. If no eligible vendors: publish NoEligibleVendors_Event and return.
         c. recommendation.build_recommendations(job, ranked_score_factors, confidence)
         d. audit_logger.log_recommendation(job, ranked_score_factors, model_version, ai_unavailable)
         e. Publish VendorRecommendationGenerated_Event to EventBridge.

    Returns an empty dict (async event — no HTTP response needed).
    """
    records = event.get("Records", [])
    for record in records:
        _process_record(record)
    return {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _process_record(record: dict) -> None:
    """Process a single SQS record."""
    timestamp = datetime.now(timezone.utc).isoformat()
    job_id = ""

    try:
        # ------------------------------------------------------------------
        # 1. Parse SQS message body
        # ------------------------------------------------------------------
        body_str = record.get("body", "{}")
        try:
            body = json.loads(body_str)
        except (json.JSONDecodeError, TypeError) as exc:
            _logger.error("Failed to parse SQS message body: %s", exc)
            _audit_logger_mod.log_dlq_failure(
                job_id="",
                reason=f"Invalid JSON in SQS message body: {exc}",
                timestamp=timestamp,
            )
            raise

        # EventBridge wraps the payload in a ``detail`` field
        detail = body.get("detail", body)
        job_id = detail.get("jobId", "")

        # ------------------------------------------------------------------
        # 2. Validate the JobEvent payload
        # ------------------------------------------------------------------
        try:
            job = _validator_mod.validate_job_event(detail)
        except _validator_mod.ValidationError as exc:
            _logger.error(
                "JobEvent validation failed for job '%s': %s", job_id, exc
            )
            _audit_logger_mod.log_dlq_failure(
                job_id=job_id,
                reason=f"JobEvent validation failed: {exc}",
                timestamp=timestamp,
            )
            raise

        # ------------------------------------------------------------------
        # 3a. Score vendors
        # ------------------------------------------------------------------
        ranked_score_factors, confidence = _vendor_scoring_mod.score_vendors(job)

        # ------------------------------------------------------------------
        # 3b. Handle no eligible vendors
        # ------------------------------------------------------------------
        if not ranked_score_factors:
            _logger.warning(
                "No eligible vendors found for job '%s'; publishing NoEligibleVendors_Event",
                job.jobId,
            )
            _publish_no_eligible_vendors(job.jobId, timestamp)
            return

        # ------------------------------------------------------------------
        # 3c. Build recommendations
        # ------------------------------------------------------------------
        recommendations = _recommendation_mod.build_recommendations(
            job, ranked_score_factors, confidence
        )

        # ------------------------------------------------------------------
        # 3d. Log recommendation to audit log
        # ------------------------------------------------------------------
        model_version = ranked_score_factors[0].modelVersion if ranked_score_factors else "0.0.0"
        is_fallback = any(not rec.isAIGenerated for rec in recommendations)

        try:
            _audit_logger_mod.log_recommendation(
                job=job,
                ranked_vendors=ranked_score_factors,
                model_version=model_version,
                ai_unavailable=is_fallback,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "Failed to write audit log for job '%s': %s", job.jobId, exc
            )
            # Non-fatal — continue

        # ------------------------------------------------------------------
        # 3e. Publish VendorRecommendationGenerated_Event
        # ------------------------------------------------------------------
        _publish_recommendation_generated(
            job_id=job.jobId,
            model_version=model_version,
            is_fallback=is_fallback,
            recommendations=recommendations,
            timestamp=timestamp,
        )

    except Exception as exc:  # noqa: BLE001
        _logger.error(
            "Unhandled error processing SQS record for job '%s': %s", job_id, exc
        )
        raise


def _publish_no_eligible_vendors(job_id: str, timestamp: str) -> None:
    """Publish NoEligibleVendors_Event to EventBridge."""
    bus_name = os.environ.get(_EVENTBRIDGE_BUS_NAME_ENV, "")
    if not bus_name:
        _logger.warning(
            "EVENTBRIDGE_BUS_NAME not set; skipping NoEligibleVendors event for job '%s'",
            job_id,
        )
        return

    try:
        eb_client = boto3.client("events")
        eb_client.put_events(
            Entries=[
                {
                    "Source": "retailfixit.ai-vrs",
                    "DetailType": "NoEligibleVendors",
                    "Detail": json.dumps({"jobId": job_id, "timestamp": timestamp}),
                    "EventBusName": bus_name,
                }
            ]
        )
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            "Failed to publish NoEligibleVendors event for job '%s': %s", job_id, exc
        )


def _publish_recommendation_generated(
    job_id: str,
    model_version: str,
    is_fallback: bool,
    recommendations: list,
    timestamp: str,
) -> None:
    """Publish VendorRecommendationGenerated_Event to EventBridge."""
    bus_name = os.environ.get(_EVENTBRIDGE_BUS_NAME_ENV, "")
    if not bus_name:
        _logger.warning(
            "EVENTBRIDGE_BUS_NAME not set; skipping VendorRecommendationGenerated event "
            "for job '%s'",
            job_id,
        )
        return

    rec_list = [
        {
            "rank": rec.rank,
            "vendorId": rec.vendorId,
            "totalScore": rec.totalScore,
            "confidence": rec.confidence,
        }
        for rec in recommendations
    ]

    try:
        eb_client = boto3.client("events")
        eb_client.put_events(
            Entries=[
                {
                    "Source": "retailfixit.ai-vrs",
                    "DetailType": "VendorRecommendationGenerated",
                    "Detail": json.dumps({
                        "jobId": job_id,
                        "modelVersion": model_version,
                        "isFallback": is_fallback,
                        "recommendations": rec_list,
                        "timestamp": timestamp,
                        "schemaVersion": "1.0",
                    }),
                    "EventBusName": bus_name,
                }
            ]
        )
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            "Failed to publish VendorRecommendationGenerated event for job '%s': %s",
            job_id,
            exc,
        )

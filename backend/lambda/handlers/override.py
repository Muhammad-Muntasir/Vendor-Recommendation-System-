"""
Override handler for the AI Vendor Recommendation System.

Handles POST /override HTTP requests routed from router.py.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 17.1, 17.5
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
ValidationError = _validator_mod.ValidationError

_dynamodb_mod = importlib.import_module("backend.lambda.services.dynamodb")
_s3_mod = importlib.import_module("backend.lambda.services.s3")
_audit_logger_mod = importlib.import_module("backend.lambda.services.audit_logger")

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

_JOBS_TABLE_ENV = "JOBS_TABLE"
_RECOMMENDATIONS_TABLE_ENV = "RECOMMENDATIONS_TABLE"
_OVERRIDE_FEEDBACK_BUCKET_ENV = "OVERRIDE_FEEDBACK_BUCKET"
_EVENTBRIDGE_BUS_NAME_ENV = "EVENTBRIDGE_BUS_NAME"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _api_response(status_code: int, body_dict: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body_dict),
    }


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------


def handle(event: dict, context) -> dict:
    """
    Handle POST /override requests.

    Steps:
      1. Parse and validate the request body.
      2. Check job eligibility (not already Assigned or Override).
      3. Write AuditLog record via audit_logger.log_override().
      4. Write S3 override feedback record.
      5. Publish VendorOverrideRecorded_Event to EventBridge.
      6. Update job status to "Override" in DynamoDB.
      7. Return HTTP 200 on success.
    """
    # ------------------------------------------------------------------
    # 1. Parse and validate request body
    # ------------------------------------------------------------------
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _api_response(400, {
            "error": {
                "code": "INVALID_JSON",
                "message": "Request body must be valid JSON.",
            }
        })

    try:
        override_req = _validator_mod.validate_override_request(body)
    except ValidationError as exc:
        return _api_response(400, {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": str(exc),
                "details": exc.fields,
            }
        })

    job_id = override_req.jobId
    vendor_id = override_req.vendorId
    override_reason = override_req.overrideReason
    user_id = override_req.userId

    # ------------------------------------------------------------------
    # 2. Check job eligibility
    # ------------------------------------------------------------------
    jobs_table = os.environ.get(_JOBS_TABLE_ENV, "Jobs")
    try:
        job_item = _dynamodb_mod.get_item(jobs_table, {"jobId": job_id})
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to fetch job '%s': %s", job_id, exc)
        return _api_response(500, {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Failed to retrieve job record.",
            }
        })

    if job_item is None:
        return _api_response(404, {
            "error": {
                "code": "NOT_FOUND",
                "message": f"Job '{job_id}' not found.",
            }
        })

    job_status = job_item.get("status", "")
    if job_status in ("Assigned", "Override"):
        return _api_response(409, {
            "error": {
                "code": "CONFLICT",
                "message": f"Job '{job_id}' has status '{job_status}' and cannot be overridden.",
            }
        })

    # ------------------------------------------------------------------
    # 3. Fetch original ranked list from Recommendations table
    # ------------------------------------------------------------------
    recommendations_table = os.environ.get(_RECOMMENDATIONS_TABLE_ENV, "Recommendations")
    original_ranked_list: list = []
    try:
        from boto3.dynamodb.conditions import Key
        result = _dynamodb_mod.query(
            recommendations_table,
            Key("jobId").eq(job_id),
        )
        original_ranked_list = result.get("Items", [])
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "Could not fetch recommendations for job '%s': %s", job_id, exc
        )
        # Non-fatal — proceed with empty list

    # ------------------------------------------------------------------
    # 4. Write AuditLog record
    # ------------------------------------------------------------------
    timestamp = datetime.now(timezone.utc).isoformat()
    model_version = "0.0.0"
    if original_ranked_list:
        model_version = original_ranked_list[0].get("modelVersion", "0.0.0")

    try:
        _audit_logger_mod.log_override(
            job=_build_job_event(job_item),
            original_recommendation=[],  # ScoreFactors list — pass empty; raw list stored in S3
            selected_vendor_id=vendor_id,
            reason=override_reason,
            user_id=user_id,
            model_version=model_version,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to write audit log for override on job '%s': %s", job_id, exc)
        # Non-fatal — continue

    # ------------------------------------------------------------------
    # 5. Write S3 override feedback record
    # ------------------------------------------------------------------
    override_feedback_bucket = os.environ.get(_OVERRIDE_FEEDBACK_BUCKET_ENV, "")
    if override_feedback_bucket:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            s3_key = (
                f"year={dt.year:04d}/month={dt.month:02d}/day={dt.day:02d}/"
                f"{job_id}_{timestamp}.json"
            )
            feedback_record = {
                "jobId": job_id,
                "selectedVendorId": vendor_id,
                "overrideReason": override_reason,
                "userId": user_id,
                "timestamp": timestamp,
                "originalRankedList": original_ranked_list,
            }
            _s3_mod.write_json_object(override_feedback_bucket, s3_key, feedback_record)
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "Failed to write S3 override feedback for job '%s': %s", job_id, exc
            )
            # Non-fatal — continue
    else:
        _logger.warning(
            "OVERRIDE_FEEDBACK_BUCKET not set; skipping S3 write for job '%s'", job_id
        )

    # ------------------------------------------------------------------
    # 6. Publish VendorOverrideRecorded_Event to EventBridge
    # ------------------------------------------------------------------
    bus_name = os.environ.get(_EVENTBRIDGE_BUS_NAME_ENV, "")
    if bus_name:
        try:
            eb_client = boto3.client("events")
            eb_client.put_events(
                Entries=[
                    {
                        "Source": "retailfixit.ai-vrs",
                        "DetailType": "VendorOverrideRecorded",
                        "Detail": json.dumps({
                            "jobId": job_id,
                            "selectedVendorId": vendor_id,
                            "timestamp": timestamp,
                        }),
                        "EventBusName": bus_name,
                    }
                ]
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "Failed to publish VendorOverrideRecorded event for job '%s': %s",
                job_id,
                exc,
            )
            # Non-fatal — continue
    else:
        _logger.warning(
            "EVENTBRIDGE_BUS_NAME not set; skipping EventBridge publish for job '%s'",
            job_id,
        )

    # ------------------------------------------------------------------
    # 7. Update job status to "Override"
    # ------------------------------------------------------------------
    try:
        _dynamodb_mod.update_item(
            jobs_table,
            key={"jobId": job_id},
            update_expression="SET #s = :status",
            expression_attribute_values={":status": "Override"},
            expression_attribute_names={"#s": "status"},
        )
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            "Failed to update job status to Override for job '%s': %s", job_id, exc
        )
        return _api_response(500, {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Override recorded but failed to update job status.",
            }
        })

    return _api_response(200, {"message": "Override recorded", "jobId": job_id})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_job_event(job_item: dict):
    """Build a JobEvent-like object from a raw DynamoDB item dict."""
    _job_mod = importlib.import_module("backend.lambda.models.job")
    JobEvent = _job_mod.JobEvent
    return JobEvent(
        jobId=job_item.get("jobId", ""),
        type=job_item.get("type", ""),
        location=job_item.get("location", ""),
        urgency=job_item.get("urgency", "Low"),
        slaDeadline=job_item.get("slaDeadline", ""),
        description=job_item.get("description", ""),
        createdAt=job_item.get("createdAt", ""),
        schemaVersion=job_item.get("schemaVersion", "1.0"),
        status=job_item.get("status", "Pending"),
    )

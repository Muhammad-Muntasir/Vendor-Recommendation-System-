"""
Query handler for the AI Vendor Recommendation System.

Handles all HTTP read/write endpoints routed from router.py.

Requirements: 10.1, 10.2, 10.4, 10.5, 11.6, 13.1, 13.3, 13.4, 16.5
"""

from __future__ import annotations

import importlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key

# ---------------------------------------------------------------------------
# Internal imports via importlib (``lambda`` is a Python reserved keyword)
# ---------------------------------------------------------------------------

_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)

_dynamodb_mod = importlib.import_module("backend.lambda.services.dynamodb")
_audit_logger_mod = importlib.import_module("backend.lambda.services.audit_logger")

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

_JOBS_TABLE_ENV = "JOBS_TABLE"
_RECOMMENDATIONS_TABLE_ENV = "RECOMMENDATIONS_TABLE"
_AUDIT_LOG_TABLE_ENV = "AUDIT_LOG_TABLE"
_EVENTBRIDGE_BUS_NAME_ENV = "EVENTBRIDGE_BUS_NAME"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


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
        "body": json.dumps(body_dict, default=str),
    }


def _parse_limit(params: dict, default: int = _DEFAULT_LIMIT, max_val: int = _MAX_LIMIT) -> int:
    try:
        limit = int(params.get("limit", default))
        return min(max(1, limit), max_val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------


def handle(event: dict, context) -> dict:
    """
    Dispatch HTTP requests to the appropriate sub-handler based on
    httpMethod and path.
    """
    http_method = event.get("httpMethod", "").upper()
    path = event.get("path", "")
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}

    _logger.info("query.handle: %s %s", http_method, path)

    # POST /jobs
    if http_method == "POST" and path == "/jobs":
        return _create_job(event)

    # GET /jobs
    if http_method == "GET" and path == "/jobs":
        return _list_jobs(query_params)

    # GET /jobs/{jobId}
    if http_method == "GET" and re.fullmatch(r"/jobs/[^/]+", path):
        job_id = path_params.get("jobId") or path.split("/")[-1]
        return _get_job(job_id)

    # GET /recommendations/{jobId}
    if http_method == "GET" and re.fullmatch(r"/recommendations/[^/]+", path):
        job_id = path_params.get("jobId") or path.split("/")[-1]
        return _get_recommendations(job_id)

    # POST /recommendations/{jobId}/accept
    if http_method == "POST" and re.fullmatch(r"/recommendations/[^/]+/accept", path):
        parts = path.split("/")
        job_id = path_params.get("jobId") or (parts[2] if len(parts) > 2 else "")
        return _accept_recommendation(job_id)

    # GET /audit-logs
    if http_method == "GET" and path == "/audit-logs":
        return _list_audit_logs(query_params)

    # GET /audit-logs/{logId}
    if http_method == "GET" and re.fullmatch(r"/audit-logs/[^/]+", path):
        log_id = path_params.get("logId") or path.split("/")[-1]
        return _get_audit_log(log_id)

    # GET /dashboard/metrics
    if http_method == "GET" and path == "/dashboard/metrics":
        return _get_dashboard_metrics()

    return _api_response(404, {
        "error": {
            "code": "NOT_FOUND",
            "message": f"Route {http_method} {path} not found.",
        }
    })


# ---------------------------------------------------------------------------
# POST /jobs
# ---------------------------------------------------------------------------


def _create_job(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _api_response(400, {
            "error": {"code": "INVALID_JSON", "message": "Request body must be valid JSON."}
        })

    required_fields = ["type", "location", "urgency", "slaDeadline", "description"]
    missing = [f for f in required_fields if not body.get(f)]
    if missing:
        return _api_response(400, {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Missing required fields.",
                "details": {f: "required field is missing or null" for f in missing},
            }
        })

    job_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    job = {
        "jobId": job_id,
        "type": body["type"],
        "location": body["location"],
        "urgency": body["urgency"],
        "slaDeadline": body["slaDeadline"],
        "description": body["description"],
        "status": "Pending",
        "createdAt": created_at,
        "schemaVersion": "1.0",
    }

    jobs_table = os.environ.get(_JOBS_TABLE_ENV, "Jobs")
    try:
        _dynamodb_mod.put_item(jobs_table, job, overwrite=True)
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to write job '%s': %s", job_id, exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to create job."}
        })

    # Publish JobCreated_Event to EventBridge
    bus_name = os.environ.get(_EVENTBRIDGE_BUS_NAME_ENV, "")
    if bus_name:
        try:
            eb_client = boto3.client("events")
            eb_client.put_events(
                Entries=[
                    {
                        "Source": "retailfixit.jobs",
                        "DetailType": "JobCreated",
                        "Detail": json.dumps(job),
                        "EventBusName": bus_name,
                    }
                ]
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error("Failed to publish JobCreated event for job '%s': %s", job_id, exc)

    return _api_response(201, job)


# ---------------------------------------------------------------------------
# GET /jobs
# ---------------------------------------------------------------------------


def _list_jobs(params: dict) -> dict:
    jobs_table = os.environ.get(_JOBS_TABLE_ENV, "Jobs")
    limit = _parse_limit(params)
    next_token = params.get("nextToken")
    status_filter = params.get("status")
    from_date = params.get("from")
    to_date = params.get("to")

    filter_expr = None

    if status_filter:
        filter_expr = Attr("status").eq(status_filter)

    if from_date:
        date_filter = Attr("createdAt").gte(from_date)
        filter_expr = date_filter if filter_expr is None else filter_expr & date_filter

    if to_date:
        date_filter = Attr("createdAt").lte(to_date)
        filter_expr = date_filter if filter_expr is None else filter_expr & date_filter

    try:
        # Use scan with optional filter; paginate manually
        kwargs: dict[str, Any] = {}
        if filter_expr is not None:
            kwargs["FilterExpression"] = filter_expr
        if next_token:
            kwargs["ExclusiveStartKey"] = json.loads(next_token)
        kwargs["Limit"] = limit

        tbl = _dynamodb_mod._get_table(jobs_table)
        response = tbl.scan(**kwargs)
        items = response.get("Items", [])
        last_key = response.get("LastEvaluatedKey")
        result_next_token = json.dumps(last_key) if last_key else None

        return _api_response(200, {"items": items, "nextToken": result_next_token})
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to list jobs: %s", exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to list jobs."}
        })


# ---------------------------------------------------------------------------
# GET /jobs/{jobId}
# ---------------------------------------------------------------------------


def _get_job(job_id: str) -> dict:
    jobs_table = os.environ.get(_JOBS_TABLE_ENV, "Jobs")
    try:
        item = _dynamodb_mod.get_item(jobs_table, {"jobId": job_id})
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to fetch job '%s': %s", job_id, exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to retrieve job."}
        })

    if item is None:
        return _api_response(404, {
            "error": {"code": "NOT_FOUND", "message": f"Job '{job_id}' not found."}
        })

    return _api_response(200, item)


# ---------------------------------------------------------------------------
# GET /recommendations/{jobId}
# ---------------------------------------------------------------------------


def _get_recommendations(job_id: str) -> dict:
    recommendations_table = os.environ.get(_RECOMMENDATIONS_TABLE_ENV, "Recommendations")
    try:
        result = _dynamodb_mod.query(
            recommendations_table,
            Key("jobId").eq(job_id),
        )
        items = result.get("Items", [])
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to fetch recommendations for job '%s': %s", job_id, exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to retrieve recommendations."}
        })

    if not items:
        return _api_response(404, {
            "error": {
                "code": "NOT_FOUND",
                "message": f"No recommendations found for job '{job_id}'.",
            }
        })

    is_fallback = any(not item.get("isAIGenerated", True) for item in items)

    return _api_response(200, {
        "jobId": job_id,
        "isFallback": is_fallback,
        "recommendations": items,
    })


# ---------------------------------------------------------------------------
# POST /recommendations/{jobId}/accept
# ---------------------------------------------------------------------------


def _accept_recommendation(job_id: str) -> dict:
    jobs_table = os.environ.get(_JOBS_TABLE_ENV, "Jobs")

    # Check job exists
    try:
        job_item = _dynamodb_mod.get_item(jobs_table, {"jobId": job_id})
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to fetch job '%s': %s", job_id, exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to retrieve job."}
        })

    if job_item is None:
        return _api_response(404, {
            "error": {"code": "NOT_FOUND", "message": f"Job '{job_id}' not found."}
        })

    if job_item.get("status") == "Assigned":
        return _api_response(409, {
            "error": {
                "code": "CONFLICT",
                "message": f"Job '{job_id}' is already assigned.",
            }
        })

    # Write AuditLog
    timestamp = datetime.now(timezone.utc).isoformat()
    log_id = ""
    try:
        _job_mod = importlib.import_module("backend.lambda.models.job")
        JobEvent = _job_mod.JobEvent
        job_event = JobEvent(
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

        # Fetch top recommendation to build Recommendation object
        recommendations_table = os.environ.get(_RECOMMENDATIONS_TABLE_ENV, "Recommendations")
        rec_result = _dynamodb_mod.query(
            recommendations_table,
            Key("jobId").eq(job_id),
        )
        rec_items = rec_result.get("Items", [])
        # Sort by rank and pick rank=1
        rec_items_sorted = sorted(rec_items, key=lambda r: r.get("rank", 999))
        top_rec_item = rec_items_sorted[0] if rec_items_sorted else {}

        _score_mod = importlib.import_module("backend.lambda.models.score")
        Recommendation = _score_mod.Recommendation
        ScoreFactors = _score_mod.ScoreFactors

        # Build a minimal ScoreFactors for the accepted recommendation
        sf_data = top_rec_item.get("scoreFactors", {})
        score_factors = ScoreFactors(
            vendorId=sf_data.get("vendorId", top_rec_item.get("vendorId", "")),
            jobId=job_id,
            completionScore=float(sf_data.get("completionScore", 0.0)),
            availabilityScore=float(sf_data.get("availabilityScore", 0.0)),
            reworkScore=float(sf_data.get("reworkScore", 0.0)),
            locationScore=float(sf_data.get("locationScore", 0.0)),
            specializationScore=float(sf_data.get("specializationScore", 0.0)),
            responseTimeScore=float(sf_data.get("responseTimeScore", 0.0)),
            slaBreachScore=float(sf_data.get("slaBreachScore", 0.0)),
            activeJobsScore=float(sf_data.get("activeJobsScore", 0.0)),
            totalScore=float(top_rec_item.get("totalScore", 0.0)),
            confidence=top_rec_item.get("confidence", "Low"),
            modelVersion=top_rec_item.get("modelVersion", "0.0.0"),
            isAIGenerated=bool(top_rec_item.get("isAIGenerated", False)),
        )

        recommendation = Recommendation(
            jobId=job_id,
            rank=int(top_rec_item.get("rank", 1)),
            vendorId=top_rec_item.get("vendorId", ""),
            totalScore=float(top_rec_item.get("totalScore", 0.0)),
            scoreFactors=score_factors,
            rationale=top_rec_item.get("rationale", ""),
            confidence=top_rec_item.get("confidence", "Low"),
            modelVersion=top_rec_item.get("modelVersion", "0.0.0"),
            timestamp=top_rec_item.get("timestamp", timestamp),
            isAIGenerated=bool(top_rec_item.get("isAIGenerated", False)),
        )

        log_id = _audit_logger_mod.log_acceptance(
            job=job_event,
            recommendation=recommendation,
            model_version=top_rec_item.get("modelVersion", "0.0.0"),
        )
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to write acceptance audit log for job '%s': %s", job_id, exc)
        # Non-fatal — continue

    # Update job status to "Assigned"
    try:
        _dynamodb_mod.update_item(
            jobs_table,
            key={"jobId": job_id},
            update_expression="SET #s = :status",
            expression_attribute_values={":status": "Assigned"},
            expression_attribute_names={"#s": "status"},
        )
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to update job status to Assigned for job '%s': %s", job_id, exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to update job status."}
        })

    return _api_response(200, {"logId": log_id, "timestamp": timestamp})


# ---------------------------------------------------------------------------
# GET /audit-logs
# ---------------------------------------------------------------------------


def _list_audit_logs(params: dict) -> dict:
    audit_log_table = os.environ.get(_AUDIT_LOG_TABLE_ENV, "AuditLog")
    limit = _parse_limit(params)
    next_token = params.get("nextToken")
    action_filter = params.get("action")
    from_date = params.get("from")
    to_date = params.get("to")
    job_id_filter = params.get("jobId")
    vendor_id_filter = params.get("vendorId")

    filter_expr = None

    def _and(existing, new_expr):
        return new_expr if existing is None else existing & new_expr

    if action_filter:
        filter_expr = _and(filter_expr, Attr("action").eq(action_filter))
    if from_date:
        filter_expr = _and(filter_expr, Attr("timestamp").gte(from_date))
    if to_date:
        filter_expr = _and(filter_expr, Attr("timestamp").lte(to_date))
    if job_id_filter:
        filter_expr = _and(filter_expr, Attr("jobId").eq(job_id_filter))
    if vendor_id_filter:
        filter_expr = _and(filter_expr, Attr("vendorId").eq(vendor_id_filter))

    try:
        kwargs: dict[str, Any] = {}
        if filter_expr is not None:
            kwargs["FilterExpression"] = filter_expr
        if next_token:
            kwargs["ExclusiveStartKey"] = json.loads(next_token)
        kwargs["Limit"] = limit

        tbl = _dynamodb_mod._get_table(audit_log_table)
        response = tbl.scan(**kwargs)
        items = response.get("Items", [])
        last_key = response.get("LastEvaluatedKey")
        result_next_token = json.dumps(last_key) if last_key else None

        return _api_response(200, {"items": items, "nextToken": result_next_token})
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to list audit logs: %s", exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to list audit logs."}
        })


# ---------------------------------------------------------------------------
# GET /audit-logs/{logId}
# ---------------------------------------------------------------------------


def _get_audit_log(log_id: str) -> dict:
    audit_log_table = os.environ.get(_AUDIT_LOG_TABLE_ENV, "AuditLog")
    try:
        item = _dynamodb_mod.get_item(audit_log_table, {"logId": log_id})
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to fetch audit log '%s': %s", log_id, exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to retrieve audit log."}
        })

    if item is None:
        return _api_response(404, {
            "error": {"code": "NOT_FOUND", "message": f"Audit log '{log_id}' not found."}
        })

    return _api_response(200, item)


# ---------------------------------------------------------------------------
# GET /dashboard/metrics
# ---------------------------------------------------------------------------


def _get_dashboard_metrics() -> dict:
    jobs_table = os.environ.get(_JOBS_TABLE_ENV, "Jobs")
    audit_log_table = os.environ.get(_AUDIT_LOG_TABLE_ENV, "AuditLog")
    recommendations_table = os.environ.get(_RECOMMENDATIONS_TABLE_ENV, "Recommendations")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        # Scan jobs created today
        jobs_today = _dynamodb_mod.scan(
            jobs_table,
            filter_expression=Attr("createdAt").begins_with(today),
        )

        # Scan audit logs for today
        audit_logs_today = _dynamodb_mod.scan(
            audit_log_table,
            filter_expression=Attr("timestamp").begins_with(today),
        )

        # Scan recommendations for today
        recs_today = _dynamodb_mod.scan(
            recommendations_table,
            filter_expression=Attr("timestamp").begins_with(today),
        )
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to fetch dashboard metrics: %s", exc)
        return _api_response(500, {
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to retrieve dashboard metrics."}
        })

    total_jobs_today = len(jobs_today)
    total_recommendations_today = len(recs_today)

    # Count overrides from audit logs
    total_overrides_today = sum(
        1 for log in audit_logs_today if log.get("action") == "ADMIN_OVERRIDE"
    )

    # Fallback activations: recommendations where isAIGenerated=False
    fallback_activations_today = sum(
        1 for rec in recs_today if not rec.get("isAIGenerated", True)
    )

    # AI service status: "Fallback" if any recommendation today used fallback
    ai_service_status = "Fallback" if fallback_activations_today > 0 else "Active"

    # Low confidence rate: proportion of recommendations with confidence="Low"
    low_confidence_count = sum(
        1 for rec in recs_today if rec.get("confidence") == "Low"
    )
    low_confidence_rate_today = (
        low_confidence_count / total_recommendations_today
        if total_recommendations_today > 0
        else 0.0
    )

    return _api_response(200, {
        "date": today,
        "totalJobsToday": total_jobs_today,
        "totalRecommendationsToday": total_recommendations_today,
        "totalOverridesToday": total_overrides_today,
        "aiServiceStatus": ai_service_status,
        "fallbackActivationsToday": fallback_activations_today,
        "lowConfidenceRateToday": low_confidence_rate_today,
    })

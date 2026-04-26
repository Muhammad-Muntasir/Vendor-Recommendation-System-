"""
Unit tests for handlers/override.py

Requirements: 5.3, 5.4, 5.7
"""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

_override_mod = importlib.import_module("backend.lambda.handlers.override")
handle = _override_mod.handle


def _make_event(body: dict) -> dict:
    return {"body": json.dumps(body), "httpMethod": "POST", "path": "/override"}


def _valid_body(**overrides) -> dict:
    base = {
        "jobId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "vendorId": "11111111-1111-1111-1111-111111111111",
        "overrideReason": "Vendor has better local knowledge for this specific area.",
        "userId": "admin@retailfixit.com",
    }
    base.update(overrides)
    return base


def _mock_job(status: str = "Recommended") -> dict:
    return {
        "jobId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "type": "plumbing",
        "location": "Austin, TX",
        "urgency": "High",
        "slaDeadline": "2025-12-31T23:59:59Z",
        "description": "Test job.",
        "createdAt": "2025-07-28T10:00:00Z",
        "schemaVersion": "1.0",
        "status": status,
    }


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("JOBS_TABLE", "ai-vrs-jobs")
    monkeypatch.setenv("RECOMMENDATIONS_TABLE", "ai-vrs-recommendations")
    monkeypatch.setenv("OVERRIDE_FEEDBACK_BUCKET", "ai-vrs-override-feedback")
    monkeypatch.setenv("AUDIT_LOG_TABLE", "ai-vrs-audit-log")
    monkeypatch.setenv("LOGS_BUCKET", "ai-vrs-logs")
    monkeypatch.setenv("EVENTBRIDGE_BUS_NAME", "default")


class TestOverrideValidation:
    def test_missing_override_reason_returns_400(self):
        body = _valid_body()
        del body["overrideReason"]
        response = handle(_make_event(body), None)
        assert response["statusCode"] == 400
        error = json.loads(response["body"])["error"]
        assert error["code"] == "VALIDATION_ERROR"

    def test_override_reason_too_short_returns_400(self):
        body = _valid_body(overrideReason="short")
        response = handle(_make_event(body), None)
        assert response["statusCode"] == 400

    def test_override_reason_too_long_returns_400(self):
        body = _valid_body(overrideReason="x" * 501)
        response = handle(_make_event(body), None)
        assert response["statusCode"] == 400

    def test_override_reason_exactly_10_chars_is_valid(self):
        """10-char reason should pass validation (job fetch may fail but not validation)."""
        body = _valid_body(overrideReason="1234567890")
        with patch("backend.lambda.services.dynamodb.get_item", return_value=_mock_job()):
            with patch("backend.lambda.services.dynamodb.query", return_value={"Items": []}):
                with patch("backend.lambda.services.dynamodb.update_item", return_value={}):
                    with patch("backend.lambda.services.audit_logger.log_override", return_value="log-id"):
                        with patch("backend.lambda.services.s3.write_json_object"):
                            with patch("boto3.client"):
                                response = handle(_make_event(body), None)
        assert response["statusCode"] == 200

    def test_missing_job_id_returns_400(self):
        body = _valid_body()
        del body["jobId"]
        response = handle(_make_event(body), None)
        assert response["statusCode"] == 400

    def test_missing_vendor_id_returns_400(self):
        body = _valid_body()
        del body["vendorId"]
        response = handle(_make_event(body), None)
        assert response["statusCode"] == 400


class TestOverrideEligibility:
    def test_already_assigned_job_returns_409(self):
        body = _valid_body()
        with patch("backend.lambda.services.dynamodb.get_item", return_value=_mock_job(status="Assigned")):
            response = handle(_make_event(body), None)
        assert response["statusCode"] == 409
        error = json.loads(response["body"])["error"]
        assert error["code"] == "CONFLICT"

    def test_already_overridden_job_returns_409(self):
        body = _valid_body()
        with patch("backend.lambda.services.dynamodb.get_item", return_value=_mock_job(status="Override")):
            response = handle(_make_event(body), None)
        assert response["statusCode"] == 409

    def test_job_not_found_returns_404(self):
        body = _valid_body()
        with patch("backend.lambda.services.dynamodb.get_item", return_value=None):
            response = handle(_make_event(body), None)
        assert response["statusCode"] == 404


class TestValidOverride:
    def test_valid_override_returns_200(self):
        body = _valid_body()
        with patch("backend.lambda.services.dynamodb.get_item", return_value=_mock_job()):
            with patch("backend.lambda.services.dynamodb.query", return_value={"Items": []}):
                with patch("backend.lambda.services.dynamodb.update_item", return_value={}):
                    with patch("backend.lambda.services.audit_logger.log_override", return_value="log-id"):
                        with patch("backend.lambda.services.s3.write_json_object"):
                            with patch("boto3.client"):
                                response = handle(_make_event(body), None)
        assert response["statusCode"] == 200
        result = json.loads(response["body"])
        assert result["jobId"] == body["jobId"]
        assert "message" in result

"""
Unit tests for services/audit_logger.py

Requirements: 6.6, 6.7
"""

from __future__ import annotations

import importlib
import re
import uuid
from unittest.mock import MagicMock, call, patch

import pytest

_audit_logger_mod = importlib.import_module("backend.lambda.services.audit_logger")
_dynamodb_mod = importlib.import_module("backend.lambda.services.dynamodb")
_job_mod = importlib.import_module("backend.lambda.models.job")

log_recommendation = _audit_logger_mod.log_recommendation
log_override = _audit_logger_mod.log_override
log_acceptance = _audit_logger_mod.log_acceptance
log_dlq_failure = _audit_logger_mod.log_dlq_failure
DynamoDBWriteError = _dynamodb_mod.DynamoDBWriteError
JobEvent = _job_mod.JobEvent

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _make_job():
    return JobEvent(
        jobId="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        type="plumbing", location="Austin, TX", urgency="High",
        slaDeadline="2025-12-31T23:59:59Z",
        description="Test job.", createdAt="2025-07-28T10:00:00Z",
        schemaVersion="1.0", status="Pending",
    )


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_TABLE", "ai-vrs-audit-log")
    monkeypatch.setenv("LOGS_BUCKET", "ai-vrs-logs")


@pytest.fixture(autouse=True)
def mock_cw():
    with patch("boto3.client") as mock_client:
        mock_cw = MagicMock()
        mock_client.return_value = mock_cw
        yield mock_cw


class TestPiiMasked:
    def test_pii_masked_true_on_dynamodb_record(self):
        """piiMasked must always be True on DynamoDB records."""
        written_items = []

        def capture_put(table, item, **kwargs):
            written_items.append(item)

        with patch("backend.lambda.services.dynamodb.put_item", side_effect=capture_put):
            with patch("backend.lambda.services.s3.write_json_object"):
                log_recommendation(_make_job(), [], "1.0.0", False)

        assert len(written_items) == 1
        assert written_items[0]["piiMasked"] is True


class TestDynamoDBRetry:
    def test_retry_fires_up_to_3_times_on_write_error(self):
        """DynamoDB write should retry up to 3 times on DynamoDBWriteError."""
        call_count = 0

        def failing_put(table, item, **kwargs):
            nonlocal call_count
            call_count += 1
            raise DynamoDBWriteError("simulated failure")

        with patch("backend.lambda.services.dynamodb.put_item", side_effect=failing_put):
            with patch("backend.lambda.services.s3.write_json_object"):
                with patch("time.sleep"):  # speed up backoff
                    log_recommendation(_make_job(), [], "1.0.0", False)

        assert call_count == 3, f"Expected 3 retry attempts, got {call_count}"


class TestLogId:
    def test_log_id_is_valid_uuid_v4(self):
        """logId must be a valid UUID v4 string."""
        written_items = []

        def capture_put(table, item, **kwargs):
            written_items.append(item)

        with patch("backend.lambda.services.dynamodb.put_item", side_effect=capture_put):
            with patch("backend.lambda.services.s3.write_json_object"):
                log_recommendation(_make_job(), [], "1.0.0", False)

        assert len(written_items) == 1
        log_id = written_items[0]["logId"]
        assert UUID_V4_RE.match(log_id), f"logId '{log_id}' is not a valid UUID v4"

    def test_log_dlq_failure_writes_dlq_action(self):
        """log_dlq_failure must write a record with action='DLQ_FAILURE'."""
        written_items = []

        def capture_put(table, item, **kwargs):
            written_items.append(item)

        with patch("backend.lambda.services.dynamodb.put_item", side_effect=capture_put):
            with patch("backend.lambda.services.s3.write_json_object"):
                log_dlq_failure("job-123", "Validation failed", "2025-07-28T10:00:00Z")

        assert len(written_items) == 1
        assert written_items[0]["action"] == "DLQ_FAILURE"
        assert UUID_V4_RE.match(written_items[0]["logId"])

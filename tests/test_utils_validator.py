"""
Unit tests for backend/lambda/utils/validator.py

Requirements: 4.7, 5.3, 5.4, 18.1, 18.2
"""

from __future__ import annotations

import importlib

import pytest

# ``lambda`` is a Python reserved keyword — use importlib to import from
# the ``backend.lambda`` package.
_validator_mod = importlib.import_module("backend.lambda.utils.validator")
ValidationError = _validator_mod.ValidationError
OverrideRequest = _validator_mod.OverrideRequest
validate_job_event = _validator_mod.validate_job_event
validate_vendor_profile = _validator_mod.validate_vendor_profile
validate_override_request = _validator_mod.validate_override_request


# ---------------------------------------------------------------------------
# Helpers — minimal valid dicts
# ---------------------------------------------------------------------------

def _valid_job_dict(**overrides) -> dict:
    base = {
        "jobId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "type": "plumbing",
        "location": "Austin, TX",
        "urgency": "High",
        "slaDeadline": "2025-12-31T23:59:59Z",
        "description": "Burst pipe in commercial kitchen.",
        "createdAt": "2025-07-28T10:00:00Z",
        "schemaVersion": "1.0",
        "status": "Pending",
    }
    base.update(overrides)
    return base


def _valid_vendor_dict(**overrides) -> dict:
    base = {
        "vendorId": "11111111-1111-1111-1111-111111111111",
        "name": "Acme Plumbing Co.",
        "completionRate": 0.92,
        "availability": "available",
        "reworkRate": 0.05,
        "location": "Austin, TX",
        "specializations": ["plumbing", "drainage"],
        "avgResponseTime": 2.5,
        "slaBreachCount": 1,
        "activeJobs": 3,
    }
    base.update(overrides)
    return base


def _valid_override_dict(**overrides) -> dict:
    base = {
        "jobId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "vendorId": "11111111-1111-1111-1111-111111111111",
        "overrideReason": "Vendor has better local knowledge for this area.",
        "userId": "user-001",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

class TestValidationError:
    def test_has_fields_attribute(self):
        err = ValidationError({"foo": "bar"})
        assert err.fields == {"foo": "bar"}

    def test_str_contains_field_info(self):
        err = ValidationError({"jobId": "required field is missing or null"})
        assert "jobId" in str(err)

    def test_multiple_fields(self):
        err = ValidationError({"a": "err1", "b": "err2"})
        assert len(err.fields) == 2


# ---------------------------------------------------------------------------
# validate_job_event
# ---------------------------------------------------------------------------

class TestValidateJobEvent:
    def test_valid_dict_returns_job_event(self):
        _job_mod = importlib.import_module("backend.lambda.models.job")
        JobEvent = _job_mod.JobEvent
        result = validate_job_event(_valid_job_dict())
        assert isinstance(result, JobEvent)

    def test_all_fields_mapped_correctly(self):
        d = _valid_job_dict()
        result = validate_job_event(d)
        assert result.jobId == d["jobId"]
        assert result.type == d["type"]
        assert result.location == d["location"]
        assert result.urgency == d["urgency"]
        assert result.slaDeadline == d["slaDeadline"]
        assert result.description == d["description"]
        assert result.createdAt == d["createdAt"]

    def test_missing_job_id_raises(self):
        d = _valid_job_dict()
        del d["jobId"]
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event(d)
        assert "jobId" in exc_info.value.fields

    def test_missing_type_raises(self):
        d = _valid_job_dict()
        del d["type"]
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event(d)
        assert "type" in exc_info.value.fields

    def test_missing_location_raises(self):
        d = _valid_job_dict()
        del d["location"]
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event(d)
        assert "location" in exc_info.value.fields

    def test_missing_urgency_raises(self):
        d = _valid_job_dict()
        del d["urgency"]
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event(d)
        assert "urgency" in exc_info.value.fields

    def test_missing_sla_deadline_raises(self):
        d = _valid_job_dict()
        del d["slaDeadline"]
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event(d)
        assert "slaDeadline" in exc_info.value.fields

    def test_missing_description_raises(self):
        d = _valid_job_dict()
        del d["description"]
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event(d)
        assert "description" in exc_info.value.fields

    def test_missing_created_at_raises(self):
        d = _valid_job_dict()
        del d["createdAt"]
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event(d)
        assert "createdAt" in exc_info.value.fields

    def test_null_field_raises(self):
        d = _valid_job_dict(jobId=None)
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event(d)
        assert "jobId" in exc_info.value.fields

    def test_multiple_missing_fields_reported(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_job_event({})
        assert len(exc_info.value.fields) > 1

    def test_invalid_urgency_raises(self):
        d = _valid_job_dict(urgency="Extreme")
        with pytest.raises(ValidationError):
            validate_job_event(d)

    def test_schema_version_defaults_to_1_0(self):
        d = _valid_job_dict()
        d.pop("schemaVersion", None)
        result = validate_job_event(d)
        assert result.schemaVersion == "1.0"

    def test_status_defaults_to_pending(self):
        d = _valid_job_dict()
        d.pop("status", None)
        result = validate_job_event(d)
        assert result.status == "Pending"


# ---------------------------------------------------------------------------
# validate_vendor_profile
# ---------------------------------------------------------------------------

class TestValidateVendorProfile:
    def test_valid_dict_returns_vendor_profile(self):
        _vendor_mod = importlib.import_module("backend.lambda.models.vendor")
        VendorProfile = _vendor_mod.VendorProfile
        result = validate_vendor_profile(_valid_vendor_dict())
        assert isinstance(result, VendorProfile)

    def test_all_fields_mapped_correctly(self):
        d = _valid_vendor_dict()
        result = validate_vendor_profile(d)
        assert result.vendorId == d["vendorId"]
        assert result.name == d["name"]
        assert result.completionRate == d["completionRate"]
        assert result.availability == d["availability"]
        assert result.reworkRate == d["reworkRate"]
        assert result.location == d["location"]
        assert result.specializations == d["specializations"]
        assert result.avgResponseTime == d["avgResponseTime"]
        assert result.slaBreachCount == d["slaBreachCount"]
        assert result.activeJobs == d["activeJobs"]

    @pytest.mark.parametrize("field", [
        "vendorId", "name", "completionRate", "availability",
        "reworkRate", "location", "specializations",
        "avgResponseTime", "slaBreachCount", "activeJobs",
    ])
    def test_missing_required_field_raises(self, field):
        d = _valid_vendor_dict()
        del d[field]
        with pytest.raises(ValidationError) as exc_info:
            validate_vendor_profile(d)
        assert field in exc_info.value.fields

    def test_null_field_raises(self):
        d = _valid_vendor_dict(vendorId=None)
        with pytest.raises(ValidationError) as exc_info:
            validate_vendor_profile(d)
        assert "vendorId" in exc_info.value.fields

    def test_invalid_availability_raises(self):
        d = _valid_vendor_dict(availability="on_vacation")
        with pytest.raises(ValidationError):
            validate_vendor_profile(d)

    def test_completion_rate_out_of_range_raises(self):
        d = _valid_vendor_dict(completionRate=1.5)
        with pytest.raises(ValidationError):
            validate_vendor_profile(d)

    def test_rework_rate_out_of_range_raises(self):
        d = _valid_vendor_dict(reworkRate=-0.1)
        with pytest.raises(ValidationError):
            validate_vendor_profile(d)

    def test_numeric_strings_are_coerced(self):
        """Validator should coerce string numbers to the correct types."""
        d = _valid_vendor_dict(completionRate="0.85", reworkRate="0.10",
                               avgResponseTime="3.0", slaBreachCount="2", activeJobs="5")
        result = validate_vendor_profile(d)
        assert result.completionRate == 0.85
        assert result.slaBreachCount == 2


# ---------------------------------------------------------------------------
# validate_override_request
# ---------------------------------------------------------------------------

class TestValidateOverrideRequest:
    def test_valid_dict_returns_override_request(self):
        result = validate_override_request(_valid_override_dict())
        assert isinstance(result, OverrideRequest)

    def test_all_fields_mapped_correctly(self):
        d = _valid_override_dict()
        result = validate_override_request(d)
        assert result.jobId == d["jobId"]
        assert result.vendorId == d["vendorId"]
        assert result.overrideReason == d["overrideReason"]
        assert result.userId == d["userId"]

    def test_missing_job_id_raises(self):
        d = _valid_override_dict()
        del d["jobId"]
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "jobId" in exc_info.value.fields

    def test_missing_vendor_id_raises(self):
        d = _valid_override_dict()
        del d["vendorId"]
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "vendorId" in exc_info.value.fields

    def test_missing_override_reason_raises(self):
        d = _valid_override_dict()
        del d["overrideReason"]
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "overrideReason" in exc_info.value.fields

    def test_missing_user_id_raises(self):
        d = _valid_override_dict()
        del d["userId"]
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "userId" in exc_info.value.fields

    def test_reason_too_short_raises(self):
        d = _valid_override_dict(overrideReason="short")
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "overrideReason" in exc_info.value.fields

    def test_reason_exactly_10_chars_is_valid(self):
        d = _valid_override_dict(overrideReason="1234567890")
        result = validate_override_request(d)
        assert result.overrideReason == "1234567890"

    def test_reason_exactly_500_chars_is_valid(self):
        d = _valid_override_dict(overrideReason="x" * 500)
        result = validate_override_request(d)
        assert len(result.overrideReason) == 500

    def test_reason_501_chars_raises(self):
        d = _valid_override_dict(overrideReason="x" * 501)
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "overrideReason" in exc_info.value.fields

    def test_reason_9_chars_raises(self):
        d = _valid_override_dict(overrideReason="123456789")
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "overrideReason" in exc_info.value.fields

    def test_null_reason_raises(self):
        d = _valid_override_dict(overrideReason=None)
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "overrideReason" in exc_info.value.fields

    def test_empty_string_reason_raises(self):
        d = _valid_override_dict(overrideReason="")
        with pytest.raises(ValidationError) as exc_info:
            validate_override_request(d)
        assert "overrideReason" in exc_info.value.fields

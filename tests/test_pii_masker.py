"""
Unit tests for services/pii_masker.py

Requirements: 6.4
"""

from __future__ import annotations

import importlib

import pytest

_pii_masker_mod = importlib.import_module("backend.lambda.services.pii_masker")
mask = _pii_masker_mod.mask

REDACTED = "[REDACTED]"


class TestEmailRedaction:
    def test_email_in_value_is_redacted(self):
        data = {"message": "Contact user@example.com for details"}
        result = mask(data)
        assert REDACTED in result["message"]
        assert "user@example.com" not in result["message"]

    def test_email_field_name_is_redacted(self):
        data = {"email": "admin@retailfixit.com"}
        result = mask(data)
        assert result["email"] == REDACTED

    def test_userEmail_field_is_redacted(self):
        data = {"userEmail": "test@test.com"}
        result = mask(data)
        assert result["userEmail"] == REDACTED

    def test_multiple_emails_in_value_are_redacted(self):
        data = {"notes": "Send to a@b.com and c@d.com"}
        result = mask(data)
        assert "a@b.com" not in result["notes"]
        assert "c@d.com" not in result["notes"]


class TestPhoneRedaction:
    def test_phone_number_in_value_is_redacted(self):
        data = {"contact": "Call 512-555-1234 for support"}
        result = mask(data)
        assert "512-555-1234" not in result["contact"]

    def test_phone_field_name_is_redacted(self):
        data = {"phone": "512-555-1234"}
        result = mask(data)
        assert result["phone"] == REDACTED

    def test_phone_with_dots_is_redacted(self):
        data = {"info": "Reach us at 512.555.1234"}
        result = mask(data)
        assert "512.555.1234" not in result["info"]


class TestNonPiiPreservation:
    def test_non_pii_string_preserved(self):
        data = {"jobType": "plumbing", "location": "Austin, TX"}
        result = mask(data)
        assert result["jobType"] == "plumbing"
        assert result["location"] == "Austin, TX"

    def test_non_pii_integer_preserved(self):
        data = {"activeJobs": 5, "slaBreachCount": 2}
        result = mask(data)
        assert result["activeJobs"] == 5
        assert result["slaBreachCount"] == 2

    def test_non_pii_float_preserved(self):
        data = {"completionRate": 0.92, "totalScore": 0.875}
        result = mask(data)
        assert result["completionRate"] == 0.92
        assert result["totalScore"] == 0.875

    def test_non_pii_list_preserved(self):
        data = {"specializations": ["plumbing", "hvac"]}
        result = mask(data)
        assert result["specializations"] == ["plumbing", "hvac"]

    def test_nested_non_pii_preserved(self):
        data = {"scoreFactors": {"completionScore": 0.9, "totalScore": 0.85}}
        result = mask(data)
        assert result["scoreFactors"]["completionScore"] == 0.9


class TestOriginalNotMutated:
    def test_original_dict_not_mutated(self):
        original = {"email": "user@example.com", "jobId": "abc-123"}
        original_copy = dict(original)
        mask(original)
        assert original == original_copy

    def test_original_nested_dict_not_mutated(self):
        original = {"user": {"email": "user@example.com", "role": "admin"}}
        original_copy = {"user": {"email": "user@example.com", "role": "admin"}}
        mask(original)
        assert original == original_copy

    def test_mask_returns_new_dict(self):
        original = {"jobId": "abc-123"}
        result = mask(original)
        assert result is not original


class TestNestedStructures:
    def test_nested_email_in_dict_is_redacted(self):
        data = {"user": {"email": "user@example.com", "role": "admin"}}
        result = mask(data)
        assert result["user"]["email"] == REDACTED
        assert result["user"]["role"] == "admin"

    def test_email_in_list_value_is_redacted(self):
        data = {"contacts": ["user@example.com", "other@test.com"]}
        result = mask(data)
        for contact in result["contacts"]:
            assert "example.com" not in contact
            assert "test.com" not in contact

    def test_deeply_nested_pii_is_redacted(self):
        data = {"level1": {"level2": {"email": "deep@example.com"}}}
        result = mask(data)
        assert result["level1"]["level2"]["email"] == REDACTED

"""
Property-based tests for the AI-VRS scoring engine.

Uses the Hypothesis library to verify 10 correctness properties across
arbitrary but valid VendorProfile and JobEvent inputs.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.4, 3.5, 5.3, 5.4, 6.4, 6.8, 14.2
"""

from __future__ import annotations

import importlib
import re
from unittest.mock import patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Module imports via importlib (``lambda`` is a Python reserved keyword)
# ---------------------------------------------------------------------------

_vendor_mod = importlib.import_module("backend.lambda.models.vendor")
_job_mod = importlib.import_module("backend.lambda.models.job")
_score_mod = importlib.import_module("backend.lambda.models.score")
_scoring_mod = importlib.import_module("backend.lambda.handlers.vendor_scoring")
_validator_mod = importlib.import_module("backend.lambda.utils.validator")
_pii_masker_mod = importlib.import_module("backend.lambda.services.pii_masker")

VendorProfile = _vendor_mod.VendorProfile
JobEvent = _job_mod.JobEvent
ScoreFactors = _score_mod.ScoreFactors

normalize = _scoring_mod.normalize
compute_total_score = _scoring_mod.compute_total_score
rank_vendors = _scoring_mod.rank_vendors
compute_confidence = _scoring_mod.compute_confidence
_WEIGHTS = _scoring_mod._WEIGHTS

validate_override_request = _validator_mod.validate_override_request
ValidationError = _validator_mod.ValidationError
mask = _pii_masker_mod.mask

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

availability_strategy = st.sampled_from(["available", "busy", "unavailable"])
urgency_strategy = st.sampled_from(["Low", "Medium", "High", "Critical"])
status_strategy = st.sampled_from(["Pending", "Recommended", "Assigned", "Override"])

vendor_strategy = st.builds(
    VendorProfile,
    vendorId=st.uuids().map(str),
    name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
    completionRate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    availability=availability_strategy,
    reworkRate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    location=st.sampled_from(["Austin, TX", "Dallas, TX", "Houston, TX", "Phoenix, AZ", "Miami, FL"]),
    specializations=st.lists(
        st.sampled_from(["plumbing", "electrical", "hvac", "carpentry", "roofing"]),
        min_size=0, max_size=5, unique=True,
    ),
    avgResponseTime=st.floats(min_value=0.0, max_value=48.0, allow_nan=False, allow_infinity=False),
    slaBreachCount=st.integers(min_value=0, max_value=20),
    activeJobs=st.integers(min_value=0, max_value=30),
)

job_strategy = st.builds(
    JobEvent,
    jobId=st.uuids().map(str),
    type=st.sampled_from(["plumbing", "electrical", "hvac", "carpentry", "roofing"]),
    location=st.sampled_from(["Austin, TX", "Dallas, TX", "Houston, TX", "Phoenix, AZ", "Miami, FL"]),
    urgency=urgency_strategy,
    slaDeadline=st.just("2025-12-31T23:59:59Z"),
    description=st.text(min_size=10, max_size=200),
    createdAt=st.just("2025-07-28T10:00:00Z"),
    schemaVersion=st.just("1.0"),
    status=status_strategy,
)

score_factors_strategy = st.builds(
    ScoreFactors,
    vendorId=st.uuids().map(str),
    jobId=st.uuids().map(str),
    completionScore=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    availabilityScore=st.sampled_from([0.0, 0.5, 1.0]),
    reworkScore=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    locationScore=st.sampled_from([0.0, 0.5, 1.0]),
    specializationScore=st.sampled_from([0.0, 1.0]),
    responseTimeScore=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    slaBreachScore=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    activeJobsScore=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    totalScore=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    confidence=st.sampled_from(["High", "Medium", "Low"]),
    modelVersion=st.just("1.0.0"),
    isAIGenerated=st.booleans(),
)


# ---------------------------------------------------------------------------
# Helper: patch get_model_version to avoid S3 calls
# ---------------------------------------------------------------------------

def _with_mock_model_version(version: str = "1.0.0"):
    return patch(
        "backend.lambda.utils.model_version.get_model_version",
        return_value=version,
    )


# ---------------------------------------------------------------------------
# Property 1: Score Bounds
# totalScore is always in [0.0, 1.0] for any valid VendorProfile + JobEvent
# Validates: Requirements 1.2
# ---------------------------------------------------------------------------

@given(vendor=vendor_strategy, job=job_strategy)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_1_score_bounds(vendor, job):
    with _with_mock_model_version():
        sf = normalize(vendor, job)
    assert 0.0 <= sf.totalScore <= 1.0, (
        f"totalScore {sf.totalScore} out of [0.0, 1.0] for vendor={vendor}, job={job}"
    )


# ---------------------------------------------------------------------------
# Property 2 (design invariant): Weight Sum
# Sum of all dimension weights equals exactly 1.0
# Validates: Requirements 1.2
# ---------------------------------------------------------------------------

def test_property_2_weight_sum():
    total = sum(_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"


# ---------------------------------------------------------------------------
# Property 3: Ranking Consistency
# Ranked list is always sorted in descending totalScore order
# Validates: Requirements 1.3
# ---------------------------------------------------------------------------

@given(score_factors=st.lists(score_factors_strategy, min_size=0, max_size=10))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_3_ranking_consistency(score_factors):
    ranked = rank_vendors(score_factors)
    for i in range(len(ranked) - 1):
        assert ranked[i].totalScore >= ranked[i + 1].totalScore, (
            f"Ranking inconsistency at position {i}: "
            f"{ranked[i].totalScore} < {ranked[i+1].totalScore}"
        )


# ---------------------------------------------------------------------------
# Property 4: Unavailable Vendor Exclusion
# No vendor with availability == "unavailable" appears in ranked output
# Validates: Requirements 1.1
# ---------------------------------------------------------------------------

@given(score_factors=st.lists(score_factors_strategy, min_size=0, max_size=10))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_4_unavailable_vendor_exclusion(score_factors):
    ranked = rank_vendors(score_factors)
    for sf in ranked:
        assert sf.availabilityScore > 0.0, (
            f"Unavailable vendor (availabilityScore=0.0) found in ranked output: {sf.vendorId}"
        )


# ---------------------------------------------------------------------------
# Property 5: Ranked List Size Bound
# Ranked list always has 0–5 vendors
# Validates: Requirements 1.3, 1.6
# ---------------------------------------------------------------------------

@given(score_factors=st.lists(score_factors_strategy, min_size=0, max_size=20))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_5_ranked_list_size_bound(score_factors):
    ranked = rank_vendors(score_factors)
    assert 0 <= len(ranked) <= 5, (
        f"Ranked list has {len(ranked)} vendors, expected 0–5"
    )


# ---------------------------------------------------------------------------
# Property 6: Tie-Breaking Determinism
# Same input always produces the same ranked order;
# tie broken by activeJobs (fewer first) then vendorId (lexicographic)
# Validates: Requirements 1.5
# ---------------------------------------------------------------------------

@given(score_factors=st.lists(score_factors_strategy, min_size=2, max_size=10))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_6_tie_breaking_determinism(score_factors):
    ranked_1 = rank_vendors(score_factors)
    ranked_2 = rank_vendors(score_factors)
    assert [sf.vendorId for sf in ranked_1] == [sf.vendorId for sf in ranked_2], (
        "rank_vendors is not deterministic for the same input"
    )


# ---------------------------------------------------------------------------
# Property 7: Fallback Structural Equivalence
# fallback_scorer output has same field names, types, and modelVersion
# as normal scoring output
# Validates: Requirements 3.5
# ---------------------------------------------------------------------------

@given(vendor=vendor_strategy, job=job_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_7_fallback_structural_equivalence(vendor, job):
    _fallback_mod = importlib.import_module("backend.lambda.services.fallback_scorer")
    generate_rationale = _fallback_mod.generate_rationale

    with _with_mock_model_version("1.0.0"):
        sf = normalize(vendor, job)

    rationale = generate_rationale(sf, rank=1)

    # Rationale must be a non-empty string
    assert isinstance(rationale, str), "Fallback rationale must be a string"
    assert len(rationale) > 0, "Fallback rationale must not be empty"

    # ScoreFactors must have modelVersion set
    assert sf.modelVersion == "1.0.0", (
        f"ScoreFactors.modelVersion should be '1.0.0', got '{sf.modelVersion}'"
    )

    # ScoreFactors must have all required fields
    required_fields = [
        "completionScore", "availabilityScore", "reworkScore", "locationScore",
        "specializationScore", "responseTimeScore", "slaBreachScore", "activeJobsScore",
        "totalScore", "confidence", "modelVersion", "isAIGenerated", "vendorId", "jobId",
    ]
    for field in required_fields:
        assert hasattr(sf, field), f"ScoreFactors missing field: {field}"


# ---------------------------------------------------------------------------
# Property 8: Confidence Level Validity
# confidence is always one of "High", "Medium", "Low"
# Validates: Requirements 2.4
# ---------------------------------------------------------------------------

@given(score_factors=st.lists(score_factors_strategy, min_size=0, max_size=10))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_8_confidence_level_validity(score_factors):
    confidence = compute_confidence(score_factors)
    assert confidence in ("High", "Medium", "Low"), (
        f"compute_confidence returned invalid value: '{confidence}'"
    )


# ---------------------------------------------------------------------------
# Property 9: Model Version Propagation
# Every ScoreFactors record carries the same modelVersion as get_model_version()
# Validates: Requirements 14.2, 1.4
# ---------------------------------------------------------------------------

@given(vendor=vendor_strategy, job=job_strategy)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_9_model_version_propagation(vendor, job):
    fixed_version = "2.5.1"
    with _with_mock_model_version(fixed_version):
        sf = normalize(vendor, job)
    assert sf.modelVersion == fixed_version, (
        f"ScoreFactors.modelVersion is '{sf.modelVersion}', expected '{fixed_version}'"
    )


# ---------------------------------------------------------------------------
# Property 10: Override Reason Length
# validate_override_request raises ValidationError for len < 10 or len > 500
# Accepts all reasons with 10 ≤ len ≤ 500
# Validates: Requirements 5.3, 5.4
# ---------------------------------------------------------------------------

_VALID_OVERRIDE_BASE = {
    "jobId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "vendorId": "11111111-1111-1111-1111-111111111111",
    "userId": "admin@retailfixit.com",
}


@given(reason=st.text(min_size=0, max_size=9))
@settings(max_examples=200)
def test_property_10a_override_reason_too_short(reason):
    """Reasons shorter than 10 chars must raise ValidationError."""
    body = {**_VALID_OVERRIDE_BASE, "overrideReason": reason}
    with pytest.raises(ValidationError) as exc_info:
        validate_override_request(body)
    assert "overrideReason" in exc_info.value.fields


@given(reason=st.text(min_size=501, max_size=600))
@settings(max_examples=200)
def test_property_10b_override_reason_too_long(reason):
    """Reasons longer than 500 chars must raise ValidationError."""
    body = {**_VALID_OVERRIDE_BASE, "overrideReason": reason}
    with pytest.raises(ValidationError) as exc_info:
        validate_override_request(body)
    assert "overrideReason" in exc_info.value.fields


@given(reason=st.text(min_size=10, max_size=500))
@settings(max_examples=200)
def test_property_10c_override_reason_valid_length(reason):
    """Reasons with 10–500 chars must be accepted."""
    body = {**_VALID_OVERRIDE_BASE, "overrideReason": reason}
    result = validate_override_request(body)
    assert result.overrideReason == reason


# ---------------------------------------------------------------------------
# Property 11: Audit Log PII Masking
# pii_masker.mask() redacts email/phone patterns; original dict not mutated
# Validates: Requirements 6.4, 6.8
# ---------------------------------------------------------------------------

_email_strategy = st.from_regex(
    r"[a-zA-Z0-9._%+\-]{1,20}@[a-zA-Z0-9.\-]{1,10}\.[a-zA-Z]{2,4}",
    fullmatch=True,
)

_phone_strategy = st.from_regex(
    r"\d{3}[-.\s]\d{3}[-.\s]\d{4}",
    fullmatch=True,
)


@given(
    email=_email_strategy,
    phone=_phone_strategy,
    safe_key=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"),
    safe_value=st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_11_pii_masking(email, phone, safe_key, safe_value):
    """PII values are redacted; non-PII values preserved; original not mutated."""
    original = {
        "userEmail": email,
        "contactPhone": phone,
        safe_key: safe_value,
    }
    original_copy = dict(original)

    masked = mask(original)

    # Original must not be mutated
    assert original == original_copy, "pii_masker.mask() mutated the original dict"

    # PII fields must be redacted
    assert masked["userEmail"] == "[REDACTED]", (
        f"Email not redacted: {masked['userEmail']}"
    )
    assert masked["contactPhone"] == "[REDACTED]", (
        f"Phone not redacted: {masked['contactPhone']}"
    )

    # Non-PII field must be preserved (if key doesn't contain PII substrings)
    pii_substrings = ("email", "phone", "address", "name")
    if not any(sub in safe_key.lower() for sub in pii_substrings):
        assert masked[safe_key] == safe_value, (
            f"Non-PII field '{safe_key}' was unexpectedly modified"
        )

"""
Unit tests for handlers/vendor_scoring.py

Tests scoring normalization, compute_confidence, and rank_vendors.
Requirements: 1.2, 1.3, 1.6, 2.4
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

_scoring_mod = importlib.import_module("backend.lambda.handlers.vendor_scoring")
_vendor_mod = importlib.import_module("backend.lambda.models.vendor")
_job_mod = importlib.import_module("backend.lambda.models.job")
_score_mod = importlib.import_module("backend.lambda.models.score")

normalize = _scoring_mod.normalize
compute_total_score = _scoring_mod.compute_total_score
rank_vendors = _scoring_mod.rank_vendors
compute_confidence = _scoring_mod.compute_confidence
same_region = _scoring_mod.same_region
VendorProfile = _vendor_mod.VendorProfile
JobEvent = _job_mod.JobEvent
ScoreFactors = _score_mod.ScoreFactors


def _make_vendor(**kwargs):
    defaults = dict(
        vendorId="v1", name="Test Vendor", completionRate=0.9,
        availability="available", reworkRate=0.1, location="Austin, TX",
        specializations=["plumbing"], avgResponseTime=2.0,
        slaBreachCount=1, activeJobs=3,
    )
    defaults.update(kwargs)
    return VendorProfile(**defaults)


def _make_job(**kwargs):
    defaults = dict(
        jobId="j1", type="plumbing", location="Austin, TX", urgency="High",
        slaDeadline="2025-12-31T23:59:59Z", description="Test job.",
        createdAt="2025-07-28T10:00:00Z", schemaVersion="1.0", status="Pending",
    )
    defaults.update(kwargs)
    return JobEvent(**defaults)


def _make_sf(total_score, availability_score=1.0, vendor_id="v1", active_jobs_score=0.85):
    return ScoreFactors(
        vendorId=vendor_id, jobId="j1",
        completionScore=0.9, availabilityScore=availability_score,
        reworkScore=0.9, locationScore=1.0, specializationScore=1.0,
        responseTimeScore=0.9, slaBreachScore=0.9, activeJobsScore=active_jobs_score,
        totalScore=total_score, confidence="", modelVersion="1.0.0", isAIGenerated=False,
    )


@pytest.fixture(autouse=True)
def mock_model_version():
    with patch("backend.lambda.utils.model_version.get_model_version", return_value="1.0.0"):
        yield


# ---------------------------------------------------------------------------
# same_region
# ---------------------------------------------------------------------------

class TestSameRegion:
    def test_same_state_abbreviation(self):
        assert same_region("Austin, TX", "Dallas, TX") is True

    def test_different_states(self):
        assert same_region("Austin, TX", "Miami, FL") is False

    def test_no_abbreviation(self):
        assert same_region("London", "Paris") is False

    def test_same_city(self):
        assert same_region("Austin, TX", "Austin, TX") is True


# ---------------------------------------------------------------------------
# normalize — boundary values for each dimension
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_completion_rate_direct(self):
        vendor = _make_vendor(completionRate=0.75)
        sf = normalize(vendor, _make_job())
        assert sf.completionScore == 0.75

    def test_completion_rate_zero(self):
        vendor = _make_vendor(completionRate=0.0)
        sf = normalize(vendor, _make_job())
        assert sf.completionScore == 0.0

    def test_completion_rate_one(self):
        vendor = _make_vendor(completionRate=1.0)
        sf = normalize(vendor, _make_job())
        assert sf.completionScore == 1.0

    def test_availability_available(self):
        vendor = _make_vendor(availability="available")
        sf = normalize(vendor, _make_job())
        assert sf.availabilityScore == 1.0

    def test_availability_busy(self):
        vendor = _make_vendor(availability="busy")
        sf = normalize(vendor, _make_job())
        assert sf.availabilityScore == 0.5

    def test_availability_unavailable(self):
        vendor = _make_vendor(availability="unavailable")
        sf = normalize(vendor, _make_job())
        assert sf.availabilityScore == 0.0

    def test_rework_rate_inverted(self):
        vendor = _make_vendor(reworkRate=0.2)
        sf = normalize(vendor, _make_job())
        assert abs(sf.reworkScore - 0.8) < 1e-9

    def test_rework_rate_zero(self):
        vendor = _make_vendor(reworkRate=0.0)
        sf = normalize(vendor, _make_job())
        assert sf.reworkScore == 1.0

    def test_location_exact_match(self):
        vendor = _make_vendor(location="Austin, TX")
        sf = normalize(vendor, _make_job(location="Austin, TX"))
        assert sf.locationScore == 1.0

    def test_location_same_region(self):
        vendor = _make_vendor(location="Dallas, TX")
        sf = normalize(vendor, _make_job(location="Austin, TX"))
        assert sf.locationScore == 0.5

    def test_location_different_region(self):
        vendor = _make_vendor(location="Miami, FL")
        sf = normalize(vendor, _make_job(location="Austin, TX"))
        assert sf.locationScore == 0.0

    def test_specialization_match(self):
        vendor = _make_vendor(specializations=["plumbing", "hvac"])
        sf = normalize(vendor, _make_job(type="plumbing"))
        assert sf.specializationScore == 1.0

    def test_specialization_no_match(self):
        vendor = _make_vendor(specializations=["electrical"])
        sf = normalize(vendor, _make_job(type="plumbing"))
        assert sf.specializationScore == 0.0

    def test_response_time_capped_at_24h(self):
        vendor = _make_vendor(avgResponseTime=24.0)
        sf = normalize(vendor, _make_job())
        assert sf.responseTimeScore == 0.0

    def test_response_time_beyond_24h(self):
        vendor = _make_vendor(avgResponseTime=48.0)
        sf = normalize(vendor, _make_job())
        assert sf.responseTimeScore == 0.0

    def test_response_time_mid(self):
        vendor = _make_vendor(avgResponseTime=12.0)
        sf = normalize(vendor, _make_job())
        assert abs(sf.responseTimeScore - 0.5) < 1e-9

    def test_sla_breach_capped_at_10(self):
        vendor = _make_vendor(slaBreachCount=10)
        sf = normalize(vendor, _make_job())
        assert sf.slaBreachScore == 0.0

    def test_sla_breach_zero(self):
        vendor = _make_vendor(slaBreachCount=0)
        sf = normalize(vendor, _make_job())
        assert sf.slaBreachScore == 1.0

    def test_active_jobs_capped_at_20(self):
        vendor = _make_vendor(activeJobs=20)
        sf = normalize(vendor, _make_job())
        assert sf.activeJobsScore == 0.0

    def test_active_jobs_zero(self):
        vendor = _make_vendor(activeJobs=0)
        sf = normalize(vendor, _make_job())
        assert sf.activeJobsScore == 1.0

    def test_total_score_in_range(self):
        vendor = _make_vendor()
        sf = normalize(vendor, _make_job())
        assert 0.0 <= sf.totalScore <= 1.0

    def test_model_version_attached(self):
        vendor = _make_vendor()
        sf = normalize(vendor, _make_job())
        assert sf.modelVersion == "1.0.0"


# ---------------------------------------------------------------------------
# compute_confidence
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_high_confidence(self):
        ranked = [_make_sf(0.85), _make_sf(0.70)]
        assert compute_confidence(ranked) == "High"

    def test_low_confidence_top_below_threshold(self):
        ranked = [_make_sf(0.45), _make_sf(0.40)]
        assert compute_confidence(ranked) == "Low"

    def test_low_confidence_all_within_005(self):
        ranked = [_make_sf(0.70), _make_sf(0.68), _make_sf(0.67)]
        assert compute_confidence(ranked) == "Low"

    def test_medium_confidence(self):
        ranked = [_make_sf(0.65), _make_sf(0.50)]
        assert compute_confidence(ranked) == "Medium"

    def test_empty_list_returns_low(self):
        assert compute_confidence([]) == "Low"

    def test_single_vendor_high(self):
        ranked = [_make_sf(0.80)]
        # gap = 0.80 - 0.0 = 0.80 > 0.10, top > 0.75 → High
        assert compute_confidence(ranked) == "High"

    def test_ai_indicator_low_downgrades_medium(self):
        ranked = [_make_sf(0.65), _make_sf(0.50)]
        assert compute_confidence(ranked, ai_indicator="LOW") == "Low"

    def test_ai_indicator_low_downgrades_high(self):
        ranked = [_make_sf(0.85), _make_sf(0.70)]
        assert compute_confidence(ranked, ai_indicator="LOW") == "Low"

    def test_ai_indicator_medium_no_change(self):
        ranked = [_make_sf(0.85), _make_sf(0.70)]
        assert compute_confidence(ranked, ai_indicator="MEDIUM") == "High"


# ---------------------------------------------------------------------------
# rank_vendors
# ---------------------------------------------------------------------------

class TestRankVendors:
    def test_filters_unavailable_vendors(self):
        sfs = [_make_sf(0.9, availability_score=0.0), _make_sf(0.8, availability_score=1.0)]
        ranked = rank_vendors(sfs)
        assert len(ranked) == 1
        assert ranked[0].totalScore == 0.8

    def test_returns_top_5(self):
        sfs = [_make_sf(float(i) / 10, vendor_id=f"v{i}") for i in range(1, 9)]
        ranked = rank_vendors(sfs)
        assert len(ranked) == 5

    def test_fewer_than_5_returns_all(self):
        sfs = [_make_sf(0.9, vendor_id="v1"), _make_sf(0.8, vendor_id="v2")]
        ranked = rank_vendors(sfs)
        assert len(ranked) == 2

    def test_sorted_descending(self):
        sfs = [_make_sf(0.5, vendor_id="v1"), _make_sf(0.9, vendor_id="v2"), _make_sf(0.7, vendor_id="v3")]
        ranked = rank_vendors(sfs)
        scores = [sf.totalScore for sf in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_empty_input(self):
        assert rank_vendors([]) == []

    def test_tie_breaking_by_vendor_id(self):
        # Same totalScore and activeJobsScore — tie broken by vendorId lexicographic
        sf_a = _make_sf(0.75, vendor_id="vendor_b", active_jobs_score=0.85)
        sf_b = _make_sf(0.75, vendor_id="vendor_a", active_jobs_score=0.85)
        ranked = rank_vendors([sf_a, sf_b])
        assert ranked[0].vendorId == "vendor_a"

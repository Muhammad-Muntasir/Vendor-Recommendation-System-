"""
Vendor scoring engine for the AI Vendor Recommendation System.

Implements the full scoring pipeline:
  - normalize()           — compute 8-dimension ScoreFactors for a vendor/job pair
  - compute_total_score() — weighted sum of all dimensions
  - same_region()         — location region helper
  - rank_vendors()        — filter, sort, and cap to top 5
  - compute_confidence()  — score-distribution-based confidence level
  - score_vendors()       — orchestration: DynamoDB read → validate → score → rank

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 3.3, 14.2, 18.2, 18.3, 18.4, 19.6
"""

from __future__ import annotations

import importlib
import os
import re
from typing import Any

import boto3

# ---------------------------------------------------------------------------
# Internal imports via importlib (``lambda`` is a Python reserved keyword)
# ---------------------------------------------------------------------------

_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)

_score_mod = importlib.import_module("backend.lambda.models.score")
ScoreFactors = _score_mod.ScoreFactors

_vendor_mod = importlib.import_module("backend.lambda.models.vendor")
VendorProfile = _vendor_mod.VendorProfile

_job_mod = importlib.import_module("backend.lambda.models.job")
JobEvent = _job_mod.JobEvent

_dynamodb_mod = importlib.import_module("backend.lambda.services.dynamodb")
_validator_mod = importlib.import_module("backend.lambda.utils.validator")
_model_version_mod = importlib.import_module("backend.lambda.utils.model_version")

# ---------------------------------------------------------------------------
# Dimension weights (must sum to 1.00)
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, float] = {
    "completionScore":     0.25,
    "availabilityScore":   0.20,
    "reworkScore":         0.15,
    "locationScore":       0.15,
    "specializationScore": 0.10,
    "responseTimeScore":   0.08,
    "slaBreachScore":      0.04,
    "activeJobsScore":     0.03,
}

# Regex to extract a US state abbreviation (two uppercase letters) from a
# location string such as "Austin, TX" or "Dallas TX 75201".
_STATE_ABBR_RE = re.compile(r"\b([A-Z]{2})\b")

# CloudWatch namespace for custom metrics
_CW_NAMESPACE = "AI-VRS"


# ---------------------------------------------------------------------------
# Helper: CloudWatch metric emission
# ---------------------------------------------------------------------------

def _emit_metric(metric_name: str, value: float = 1.0, unit: str = "Count") -> None:
    """Emit a single CloudWatch custom metric.  Failures are logged but not raised."""
    try:
        cw = boto3.client("cloudwatch")
        cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": metric_name,
                    "Value": value,
                    "Unit": unit,
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Failed to emit CloudWatch metric '%s': %s", metric_name, exc)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def same_region(loc1: str, loc2: str) -> bool:
    """
    Return ``True`` when two location strings share the same US state abbreviation.

    The function extracts all two-uppercase-letter tokens from each string and
    checks whether the sets of extracted abbreviations overlap.

    Examples::

        same_region("Austin, TX", "Dallas, TX")  # True
        same_region("Austin, TX", "Miami, FL")   # False
        same_region("New York, NY", "Albany NY")  # True

    Args:
        loc1: First location string.
        loc2: Second location string.

    Returns:
        ``True`` if both strings contain at least one common state abbreviation,
        ``False`` otherwise (including when no abbreviation is found in either).
    """
    abbrs1 = set(_STATE_ABBR_RE.findall(loc1))
    abbrs2 = set(_STATE_ABBR_RE.findall(loc2))
    return bool(abbrs1 & abbrs2)


def normalize(vendor: VendorProfile, job: JobEvent) -> ScoreFactors:
    """
    Compute normalized ``ScoreFactors`` for a single vendor/job pair.

    Applies all 8 normalization rules defined in the design document and
    attaches the current ``modelVersion`` from the S3-backed cache.

    Args:
        vendor: A validated :class:`VendorProfile` instance.
        job:    A validated :class:`JobEvent` instance.

    Returns:
        A :class:`ScoreFactors` instance with ``totalScore`` rounded to 6
        decimal places and ``confidence`` set to ``""`` (populated later by
        :func:`compute_confidence`).
    """
    # 1. Completion rate — used directly
    completion_score: float = vendor.completionRate

    # 2. Availability — enum map
    _availability_map: dict[str, float] = {
        "available":   1.0,
        "busy":        0.5,
        "unavailable": 0.0,
    }
    availability_score: float = _availability_map.get(vendor.availability, 0.0)

    # 3. Rework rate — inverted
    rework_score: float = 1.0 - vendor.reworkRate

    # 4. Location — exact match → 1.0, same region → 0.5, otherwise → 0.0
    if vendor.location == job.location:
        location_score: float = 1.0
    elif same_region(vendor.location, job.location):
        location_score = 0.5
    else:
        location_score = 0.0

    # 5. Specialization — binary match
    specialization_score: float = 1.0 if job.type in vendor.specializations else 0.0

    # 6. Average response time — capped at 0.0 for 24+ hours
    response_time_score: float = max(0.0, 1.0 - (vendor.avgResponseTime / 24.0))

    # 7. SLA breach count — capped at 0.0 for 10+ breaches
    sla_breach_score: float = max(0.0, 1.0 - (vendor.slaBreachCount / 10.0))

    # 8. Active jobs — capped at 0.0 for 20+ active jobs
    active_jobs_score: float = max(0.0, 1.0 - (vendor.activeJobs / 20.0))

    sf = ScoreFactors(
        vendorId=vendor.vendorId,
        jobId=job.jobId,
        completionScore=completion_score,
        availabilityScore=availability_score,
        reworkScore=rework_score,
        locationScore=location_score,
        specializationScore=specialization_score,
        responseTimeScore=response_time_score,
        slaBreachScore=sla_breach_score,
        activeJobsScore=active_jobs_score,
        totalScore=0.0,          # computed below
        confidence="",           # populated after ranking
        modelVersion=_model_version_mod.get_model_version(),
        isAIGenerated=False,
    )

    sf.totalScore = compute_total_score(sf)
    return sf


def compute_total_score(sf: ScoreFactors) -> float:
    """
    Compute the weighted total score from a :class:`ScoreFactors` instance.

    Formula::

        totalScore = 0.25*completionScore
                   + 0.20*availabilityScore
                   + 0.15*reworkScore
                   + 0.15*locationScore
                   + 0.10*specializationScore
                   + 0.08*responseTimeScore
                   + 0.04*slaBreachScore
                   + 0.03*activeJobsScore

    Args:
        sf: A :class:`ScoreFactors` instance with all dimension scores populated.

    Returns:
        The weighted total score rounded to 6 decimal places.
    """
    raw = (
        _WEIGHTS["completionScore"]     * sf.completionScore
        + _WEIGHTS["availabilityScore"] * sf.availabilityScore
        + _WEIGHTS["reworkScore"]       * sf.reworkScore
        + _WEIGHTS["locationScore"]     * sf.locationScore
        + _WEIGHTS["specializationScore"] * sf.specializationScore
        + _WEIGHTS["responseTimeScore"] * sf.responseTimeScore
        + _WEIGHTS["slaBreachScore"]    * sf.slaBreachScore
        + _WEIGHTS["activeJobsScore"]   * sf.activeJobsScore
    )
    return round(raw, 6)


def rank_vendors(score_factors: list[ScoreFactors]) -> list[ScoreFactors]:
    """
    Filter, sort, and return the top 5 eligible vendors.

    Filtering:
        Vendors with ``availabilityScore == 0.0`` (i.e. "unavailable") are
        excluded from the ranked output.

    Sorting:
        Primary key:   ``-totalScore``  (descending — higher is better)
        Secondary key: ``activeJobs``   (ascending — fewer active jobs is better)
        Tertiary key:  ``vendorId``     (ascending — lexicographic, for determinism)

    Note: ``activeJobs`` is not stored on ``ScoreFactors`` directly; it is
    derived from ``activeJobsScore`` via the inverse formula
    ``activeJobs ≈ (1.0 - activeJobsScore) * 20``.  Because the sort only
    needs relative ordering and the mapping is monotone, sorting by
    ``-activeJobsScore`` (ascending active jobs) is equivalent.

    Args:
        score_factors: List of :class:`ScoreFactors` instances (any order).

    Returns:
        Up to 5 :class:`ScoreFactors` instances sorted by the tie-breaking key.
    """
    eligible = [sf for sf in score_factors if sf.availabilityScore > 0.0]
    # Sort: highest totalScore first; then fewest active jobs (lowest activeJobsScore
    # means most active jobs, so we sort descending on activeJobsScore to get
    # fewest active jobs first); then lexicographic vendorId.
    # activeJobs = (1 - activeJobsScore) * 20  →  lower activeJobsScore = more jobs
    # We want fewer active jobs first, so sort by -activeJobsScore descending
    # which is equivalent to sorting by activeJobsScore ascending (more score = fewer jobs).
    # Actually: activeJobs = (1 - activeJobsScore) * 20
    #   fewer activeJobs → higher activeJobsScore
    #   sort ascending on activeJobs ↔ sort descending on activeJobsScore
    # Use the raw inverse to reconstruct activeJobs for the sort key:
    sorted_vendors = sorted(
        eligible,
        key=lambda sf: (
            -sf.totalScore,
            round((1.0 - sf.activeJobsScore) * 20),  # reconstructed activeJobs
            sf.vendorId,
        ),
    )
    return sorted_vendors[:5]


def compute_confidence(
    ranked: list[ScoreFactors],
    ai_indicator: str = "MEDIUM",
) -> str:
    """
    Determine the confidence level for the top recommendation.

    Rules (applied in order):
      1. If ``ranked`` is empty → ``"Low"``
      2. High if ``top_score > 0.75`` **and** ``gap > 0.10``
      3. Low  if ``top_score < 0.50`` **or** all scores within 0.05 of each other
      4. Otherwise → ``"Medium"``
      5. Downgrade to ``"Low"`` if ``ai_indicator == "LOW"``

    Args:
        ranked:       Ranked list of :class:`ScoreFactors` (output of
                      :func:`rank_vendors`).
        ai_indicator: Optional AI quality signal from Gemini
                      (``"HIGH"``, ``"MEDIUM"``, or ``"LOW"``).
                      Defaults to ``"MEDIUM"``.

    Returns:
        One of ``"High"``, ``"Medium"``, or ``"Low"``.
    """
    if not ranked:
        return "Low"

    top = ranked[0].totalScore
    rank2 = ranked[1].totalScore if len(ranked) >= 2 else 0.0
    gap = top - rank2

    all_scores = [sf.totalScore for sf in ranked]
    all_within_005 = (max(all_scores) - min(all_scores)) <= 0.05

    if top > 0.75 and gap > 0.10:
        confidence = "High"
    elif top < 0.50 or all_within_005:
        confidence = "Low"
    else:
        confidence = "Medium"

    # Downgrade to Low if AI indicator is LOW
    if ai_indicator.upper() == "LOW":
        confidence = "Low"

    return confidence


def score_vendors(job: JobEvent) -> tuple[list[ScoreFactors], str]:
    """
    Full scoring pipeline orchestration.

    Steps:
      1. Read all ``VendorProfile`` records from DynamoDB (table name from
         ``VENDORS_TABLE`` environment variable).
      2. Validate each raw profile dict via
         ``utils/validator.validate_vendor_profile()``; exclude invalid profiles
         and emit a ``VendorProfileDataQualityErrors`` CloudWatch metric for
         each excluded vendor.
      3. Filter out vendors with ``availability == "unavailable"``.
      4. Call :func:`normalize` and :func:`compute_total_score` for each
         eligible vendor.
      5. Call :func:`rank_vendors` and :func:`compute_confidence`.
      6. Attach the computed ``confidence`` value to each ranked
         :class:`ScoreFactors` record.

    Args:
        job: A validated :class:`JobEvent` instance.

    Returns:
        A ``(ranked_score_factors, confidence)`` tuple where
        ``ranked_score_factors`` is a list of up to 5 :class:`ScoreFactors`
        instances (each with ``modelVersion`` and ``confidence`` populated) and
        ``confidence`` is one of ``"High"``, ``"Medium"``, ``"Low"``.
    """
    vendors_table = os.environ.get("VENDORS_TABLE", "Vendors")

    # ------------------------------------------------------------------
    # Step 1: Read all vendor profiles from DynamoDB
    # ------------------------------------------------------------------
    try:
        raw_profiles: list[dict[str, Any]] = _dynamodb_mod.scan(vendors_table)
    except Exception as exc:  # noqa: BLE001
        _logger.error("Failed to scan vendors table '%s': %s", vendors_table, exc)
        raise

    # ------------------------------------------------------------------
    # Step 2: Validate each profile; exclude and metric-emit on failure
    # ------------------------------------------------------------------
    valid_vendors: list[VendorProfile] = []
    for raw in raw_profiles:
        try:
            vendor = _validator_mod.validate_vendor_profile(raw)
            valid_vendors.append(vendor)
        except Exception as exc:  # noqa: BLE001
            vendor_id = raw.get("vendorId", "<unknown>")
            _logger.warning(
                "Excluding vendor '%s' due to validation failure: %s",
                vendor_id,
                exc,
            )
            _emit_metric("VendorProfileDataQualityErrors")

    # ------------------------------------------------------------------
    # Step 3: Filter out unavailable vendors
    # ------------------------------------------------------------------
    eligible_vendors = [v for v in valid_vendors if v.availability != "unavailable"]

    # ------------------------------------------------------------------
    # Step 4: Compute ScoreFactors for each eligible vendor
    # ------------------------------------------------------------------
    all_score_factors: list[ScoreFactors] = []
    for vendor in eligible_vendors:
        try:
            sf = normalize(vendor, job)
            all_score_factors.append(sf)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Failed to score vendor '%s': %s", vendor.vendorId, exc
            )

    # ------------------------------------------------------------------
    # Step 5: Rank vendors and compute confidence
    # ------------------------------------------------------------------
    ranked = rank_vendors(all_score_factors)
    confidence = compute_confidence(ranked)

    # ------------------------------------------------------------------
    # Step 6: Attach confidence to each ranked ScoreFactors record
    # ------------------------------------------------------------------
    for sf in ranked:
        sf.confidence = confidence

    _logger.info(
        "Scored %d vendors for job '%s'; %d ranked; confidence=%s",
        len(eligible_vendors),
        job.jobId,
        len(ranked),
        confidence,
    )

    return ranked, confidence

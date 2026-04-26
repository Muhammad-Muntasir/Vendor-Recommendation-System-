"""
Rule-based rationale generator for the AI Vendor Recommendation System.

Produces plain-English rationale strings from ``ScoreFactors`` when the
Gemini API is unavailable.  The output is structurally identical to
AI-generated rationale — same field names, same ``modelVersion`` — so that
downstream consumers need no special-casing.

Requirements: 3.1, 3.5
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Avoid circular imports at runtime; ScoreFactors is imported lazily below
    pass

# ``lambda`` is a Python reserved keyword — use importlib for internal imports
_score_mod = importlib.import_module("backend.lambda.models.score")
ScoreFactors = _score_mod.ScoreFactors

# ---------------------------------------------------------------------------
# Dimension descriptors used to build the rationale sentence
# ---------------------------------------------------------------------------

# Each entry: (score_attribute, high_threshold, high_label, low_label)
_DIMENSIONS: list[tuple[str, float, str, str]] = [
    ("completionScore",    0.80, "high completion rate",        "low completion rate"),
    ("availabilityScore",  0.75, "strong availability",         "limited availability"),
    ("reworkScore",        0.80, "low rework rate",             "elevated rework rate"),
    ("locationScore",      0.75, "close location proximity",    "distant location"),
    ("specializationScore",0.90, "strong specialization match", "partial specialization match"),
    ("responseTimeScore",  0.70, "fast response time",          "slow response time"),
    ("slaBreachScore",     0.80, "clean SLA history",           "SLA breach history"),
    ("activeJobsScore",    0.70, "low current workload",        "high current workload"),
]

# Weights mirror the scoring engine (used to rank contributing dimensions)
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_rationale(score_factors: "ScoreFactors", rank: int) -> str:
    """
    Construct a plain-English rationale for a vendor's ranking.

    Describes the top contributing score dimensions in descending order of
    weighted contribution.  The output mirrors the structure expected from
    the Gemini API so that callers need no special-casing.

    Args:
        score_factors: The vendor's computed ``ScoreFactors`` record.
        rank:          The vendor's rank position (1-based).

    Returns:
        A human-readable rationale string, e.g.:
        ``"Vendor ranked #1 due to high completion rate (0.94), strong
        availability, and close location proximity."``
    """
    # Build (weighted_contribution, label, score_value) tuples for each dimension
    contributions: list[tuple[float, str, float]] = []
    for attr, high_threshold, high_label, low_label in _DIMENSIONS:
        score_val: float = getattr(score_factors, attr, 0.0)
        weight = _WEIGHTS.get(attr, 0.0)
        contribution = weight * score_val
        label = high_label if score_val >= high_threshold else low_label
        contributions.append((contribution, label, score_val))

    # Sort by weighted contribution descending; take top 3
    contributions.sort(key=lambda t: t[0], reverse=True)
    top = contributions[:3]

    # Build the rationale sentence
    ordinal = _ordinal(rank)
    parts: list[str] = []
    for i, (_, label, score_val) in enumerate(top):
        if i == 0:
            parts.append(f"{label} ({score_val:.2f})")
        else:
            parts.append(label)

    if len(parts) == 1:
        factors_str = parts[0]
    elif len(parts) == 2:
        factors_str = f"{parts[0]} and {parts[1]}"
    else:
        factors_str = f"{parts[0]}, {parts[1]}, and {parts[2]}"

    rationale = (
        f"Vendor ranked #{rank} ({ordinal}) due to {factors_str}. "
        f"Total score: {score_factors.totalScore:.3f}."
    )
    return rationale


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ordinal(n: int) -> str:
    """Return the ordinal suffix string for integer *n* (e.g. 1 → 'st')."""
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

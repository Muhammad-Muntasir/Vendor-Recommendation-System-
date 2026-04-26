"""
Recommendation handler for the AI Vendor Recommendation System.

Assembles ``Recommendation`` records for the top-5 ranked vendors by:
  1. Calling ``services/ai_client.get_rationale()`` for each vendor (8-second
     timeout is enforced inside ai_client).
  2. Falling back to ``services/fallback_scorer.generate_rationale()`` on
     ``GeminiUnavailableError`` or any other exception.
  3. Writing the assembled ``Recommendation`` records to DynamoDB.
  4. Emitting a ``FallbackScorerActivations`` CloudWatch metric when any
     vendor used the fallback path.

Requirements: 2.1, 2.3, 2.5, 2.6, 2.7, 3.1, 3.4, 19.6
"""

from __future__ import annotations

import dataclasses
import importlib
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import boto3

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Internal imports via importlib (``lambda`` is a Python reserved keyword)
# ---------------------------------------------------------------------------

_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)

_score_mod = importlib.import_module("backend.lambda.models.score")
ScoreFactors = _score_mod.ScoreFactors
Recommendation = _score_mod.Recommendation

_job_mod = importlib.import_module("backend.lambda.models.job")
JobEvent = _job_mod.JobEvent

_ai_client_mod = importlib.import_module("backend.lambda.services.ai_client")
GeminiUnavailableError = _ai_client_mod.GeminiUnavailableError

_fallback_mod = importlib.import_module("backend.lambda.services.fallback_scorer")
_dynamodb_mod = importlib.import_module("backend.lambda.services.dynamodb")

# ---------------------------------------------------------------------------
# CloudWatch configuration
# ---------------------------------------------------------------------------

_CW_NAMESPACE = "AI-VRS"


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
# Public API
# ---------------------------------------------------------------------------


def build_recommendations(
    job: "JobEvent",
    ranked_score_factors: list,
    confidence: str,
) -> list:
    """
    Assemble ``Recommendation`` records for the top-5 ranked vendors.

    For each vendor in *ranked_score_factors* (up to 5):
      - Calls ``services/ai_client.get_rationale(score_factors, job, rank)``
        with the 8-second timeout enforced inside ``ai_client``.
      - On ``GeminiUnavailableError`` or any other exception, falls back to
        ``services/fallback_scorer.generate_rationale(score_factors, rank)``
        and marks ``isAIGenerated=False``.

    After assembling all records:
      - Writes each ``Recommendation`` to the DynamoDB Recommendations table
        (table name from the ``RECOMMENDATIONS_TABLE`` environment variable).
      - Emits a ``FallbackScorerActivations`` CloudWatch metric (value=1) if
        **any** vendor used the fallback path.

    Args:
        job:                  The originating :class:`JobEvent`.
        ranked_score_factors: Ordered list of :class:`ScoreFactors` instances
                              (output of ``vendor_scoring.score_vendors``).
                              Only the first 5 are processed.
        confidence:           Confidence level string (``"High"``, ``"Medium"``,
                              or ``"Low"``) computed by the scoring engine.

    Returns:
        A list of :class:`Recommendation` instances (one per vendor, in rank
        order).  The ``isAIGenerated`` flag on each record indicates whether
        AI or fallback rationale was used.
    """
    recommendations: list[Recommendation] = []
    ai_unavailable = False

    # Process at most the top 5 vendors
    top_vendors = ranked_score_factors[:5]

    for rank_index, score_factors in enumerate(top_vendors):
        rank = rank_index + 1  # 1-based rank
        rationale: str
        is_ai_generated: bool

        # ------------------------------------------------------------------
        # Attempt AI-generated rationale
        # ------------------------------------------------------------------
        try:
            rationale_text, _ai_indicator = _ai_client_mod.get_rationale(
                score_factors, job, rank
            )
            rationale = rationale_text
            is_ai_generated = True
            _logger.info(
                "AI rationale obtained for vendor '%s' (rank %d, job '%s')",
                score_factors.vendorId,
                rank,
                job.jobId,
            )
        except GeminiUnavailableError as exc:
            _logger.warning(
                "GeminiUnavailableError for vendor '%s' (rank %d, job '%s'): %s; "
                "using fallback rationale",
                score_factors.vendorId,
                rank,
                job.jobId,
                exc,
            )
            rationale = _fallback_mod.generate_rationale(score_factors, rank)
            is_ai_generated = False
            ai_unavailable = True
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Unexpected error getting AI rationale for vendor '%s' "
                "(rank %d, job '%s'): %s; using fallback rationale",
                score_factors.vendorId,
                rank,
                job.jobId,
                exc,
            )
            rationale = _fallback_mod.generate_rationale(score_factors, rank)
            is_ai_generated = False
            ai_unavailable = True

        # ------------------------------------------------------------------
        # Assemble the Recommendation record
        # ------------------------------------------------------------------
        timestamp = datetime.now(timezone.utc).isoformat()

        rec = Recommendation(
            jobId=job.jobId,
            rank=rank,
            vendorId=score_factors.vendorId,
            totalScore=score_factors.totalScore,
            scoreFactors=score_factors,
            rationale=rationale,
            confidence=confidence,
            modelVersion=score_factors.modelVersion,
            timestamp=timestamp,
            isAIGenerated=is_ai_generated,
        )
        recommendations.append(rec)

    # ------------------------------------------------------------------
    # Write all Recommendation records to DynamoDB
    # ------------------------------------------------------------------
    recommendations_table = os.environ.get("RECOMMENDATIONS_TABLE", "Recommendations")
    for rec in recommendations:
        try:
            _dynamodb_mod.put_item(
                recommendations_table,
                _recommendation_to_dict(rec),
                overwrite=True,
            )
            _logger.info(
                "Wrote recommendation rank=%d vendorId='%s' jobId='%s' to DynamoDB",
                rec.rank,
                rec.vendorId,
                rec.jobId,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "Failed to write recommendation rank=%d vendorId='%s' jobId='%s': %s",
                rec.rank,
                rec.vendorId,
                rec.jobId,
                exc,
            )
            raise

    # ------------------------------------------------------------------
    # Emit CloudWatch metric if fallback was used for any vendor
    # ------------------------------------------------------------------
    if ai_unavailable:
        _emit_metric("FallbackScorerActivations")
        _logger.info(
            "FallbackScorerActivations metric emitted for job '%s'", job.jobId
        )

    return recommendations


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _recommendation_to_dict(rec: "Recommendation") -> dict:
    """
    Convert a Recommendation dataclass to a DynamoDB-compatible dict.
    Converts all float values to Decimal (DynamoDB requirement).
    """
    from decimal import Decimal

    def _convert(obj):
        if isinstance(obj, float):
            return Decimal(str(round(obj, 6)))
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(i) for i in obj]
        return obj

    return _convert(dataclasses.asdict(rec))

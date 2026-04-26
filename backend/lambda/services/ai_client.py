"""
Gemini 2.5 Flash API client for the AI Vendor Recommendation System.

Fetches the Gemini API key from ``services/secrets.py`` at cold start and
caches it in a module-level variable.  Builds a structured prompt from
``ScoreFactors`` + job context, sends an HTTP POST to the Gemini API with an
8-second timeout, and parses the response to extract the rationale text and
confidence indicator.

Retry logic:
  - 2 retries on HTTP 5xx with exponential backoff
  - 0 retries on HTTP 4xx (except 429)
  - Respects ``Retry-After`` header on HTTP 429 (max 30-second wait)

Raises ``GeminiUnavailableError`` on exhausted retries or timeout.

Gemini API endpoint:
  https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}

Requirements: 2.1, 2.2, 2.6, 19.1, 19.2, 19.3
"""

from __future__ import annotations

import importlib
import time
from typing import Optional, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Internal imports via importlib (``lambda`` is a reserved keyword)
# ---------------------------------------------------------------------------

_logger_mod = importlib.import_module("backend.lambda.utils.logger")
_logger = _logger_mod.get_logger(__name__)

_secrets_mod = importlib.import_module("backend.lambda.services.secrets")
_score_mod = importlib.import_module("backend.lambda.models.score")
_job_mod = importlib.import_module("backend.lambda.models.job")

ScoreFactors = _score_mod.ScoreFactors
JobEvent = _job_mod.JobEvent

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class GeminiUnavailableError(Exception):
    """Raised when the Gemini API is unreachable or exhausts all retries."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent?key={api_key}"
)
_REQUEST_TIMEOUT = 5   # seconds — reduced to fit within Lambda timeout
_MAX_5XX_RETRIES = 1   # only 1 retry on 5xx
_BACKOFF_BASE = 0.5    # seconds
_MAX_RETRY_AFTER = 3   # cap Retry-After at 3s — if rate limited, fail fast to fallback

# ---------------------------------------------------------------------------
# Module-level API key cache (populated at cold start)
# ---------------------------------------------------------------------------

_cached_api_key: Optional[str] = None


def _get_api_key() -> str:
    """Return the cached API key, fetching it from Secrets Manager if needed."""
    global _cached_api_key
    if _cached_api_key is None:
        _cached_api_key = _secrets_mod.get_gemini_api_key()
    return _cached_api_key


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are an expert vendor selection assistant for RetailFixIt, a field service management platform.

A new service job has been created with the following details:
- Job Type: {job_type}
- Location: {job_location}
- Urgency: {job_urgency}
- SLA Deadline: {sla_deadline}
- Description: {job_description}

You are evaluating Vendor #{rank} from a ranked shortlist of up to 5 candidates.

Vendor Score Breakdown (all scores normalized 0.0–1.0, higher is better):
- Completion Rate Score:     {completion_score} (weight: 25%)
- Availability Score:        {availability_score} (weight: 20%)
- Rework Rate Score:         {rework_score} (weight: 15%)
- Location Proximity Score:  {location_score} (weight: 15%)
- Specialization Match:      {specialization_score} (weight: 10%)
- Avg Response Time Score:   {response_time_score} (weight: 8%)
- SLA Breach Score:          {sla_breach_score} (weight: 4%)
- Active Jobs Score:         {active_jobs_score} (weight: 3%)
- TOTAL SCORE:               {total_score}

Task: Write a concise 2–3 sentence plain-language explanation of why this vendor is ranked #{rank} for this job.
Focus on the highest-contributing score dimensions. Do not mention vendor names or IDs.
End your response with a confidence indicator on a new line in this exact format:
CONFIDENCE: HIGH | CONFIDENCE: MEDIUM | CONFIDENCE: LOW

Respond only with the rationale text followed by the confidence indicator. No preamble.\
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_rationale(
    score_factors: "ScoreFactors",
    job: "JobEvent",
    rank: int,
) -> tuple[str, str]:
    """
    Request a human-readable rationale from the Gemini 2.5 Flash API.

    Args:
        score_factors: The vendor's computed ``ScoreFactors`` record.
        job:           The originating ``JobEvent``.
        rank:          The vendor's rank position (1-based).

    Returns:
        A ``(rationale_text, ai_quality_indicator)`` tuple where
        ``ai_quality_indicator`` is one of ``"HIGH"``, ``"MEDIUM"``, ``"LOW"``.

    Raises:
        GeminiUnavailableError: If the API is unreachable, times out, or
                                exhausts all retries.
    """
    api_key = _get_api_key()
    prompt = _build_prompt(score_factors, job, rank)
    url = _GEMINI_ENDPOINT.format(api_key=api_key)
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }

    return _send_with_retry(url, payload)


def extract_confidence(response_text: str) -> tuple[str, str]:
    """
    Parse the Gemini response text to extract rationale and confidence indicator.

    The last line of the response is expected to be in the format:
    ``CONFIDENCE: HIGH``, ``CONFIDENCE: MEDIUM``, or ``CONFIDENCE: LOW``.

    Args:
        response_text: Raw text returned by the Gemini API.

    Returns:
        A ``(rationale, ai_indicator)`` tuple.  If no confidence line is
        found, ``ai_indicator`` defaults to ``"LOW"``.
    """
    lines = response_text.strip().splitlines()
    if not lines:
        return response_text.strip(), "LOW"

    last_line = lines[-1].strip().upper()
    if last_line.startswith("CONFIDENCE:"):
        ai_indicator = last_line.split(":", 1)[1].strip()  # "HIGH", "MEDIUM", or "LOW"
        rationale = "\n".join(lines[:-1]).strip()
        return rationale, ai_indicator

    # No confidence line found — treat as LOW quality
    return response_text.strip(), "LOW"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_prompt(
    score_factors: "ScoreFactors",
    job: "JobEvent",
    rank: int,
) -> str:
    """Render the prompt template with runtime values."""
    return _PROMPT_TEMPLATE.format(
        job_type=job.type,
        job_location=job.location,
        job_urgency=job.urgency,
        sla_deadline=job.slaDeadline,
        job_description=job.description,
        rank=rank,
        completion_score=score_factors.completionScore,
        availability_score=score_factors.availabilityScore,
        rework_score=score_factors.reworkScore,
        location_score=score_factors.locationScore,
        specialization_score=score_factors.specializationScore,
        response_time_score=score_factors.responseTimeScore,
        sla_breach_score=score_factors.slaBreachScore,
        active_jobs_score=score_factors.activeJobsScore,
        total_score=score_factors.totalScore,
    )


def _send_with_retry(url: str, payload: dict) -> tuple[str, str]:
    """
    Send the HTTP POST to the Gemini API with retry logic.

    Retry policy:
      - 2 retries on HTTP 5xx with exponential backoff
      - 0 retries on HTTP 4xx (except 429)
      - Respects ``Retry-After`` on 429 (capped at ``_MAX_RETRY_AFTER`` seconds)

    Returns:
        ``(rationale_text, ai_quality_indicator)``

    Raises:
        GeminiUnavailableError: On timeout or exhausted retries.
    """
    attempt = 0
    max_attempts = _MAX_5XX_RETRIES + 1  # initial attempt + retries

    while attempt < max_attempts:
        try:
            response = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT)
        except requests.Timeout as exc:
            raise GeminiUnavailableError(
                f"Gemini API request timed out after {_REQUEST_TIMEOUT}s"
            ) from exc
        except requests.RequestException as exc:
            raise GeminiUnavailableError(
                f"Gemini API request failed: {exc}"
            ) from exc

        status = response.status_code

        if status == 200:
            return _parse_response(response.json())

        if status == 429:
            # Rate-limited — respect Retry-After header (capped)
            retry_after = _parse_retry_after(response)
            wait = min(retry_after, _MAX_RETRY_AFTER)
            _logger.warning(
                "Gemini API rate-limited (429); waiting %.1fs before retry", wait
            )
            time.sleep(wait)
            # 429 does not consume a 5xx retry slot — but we still cap total
            # attempts to avoid infinite loops
            attempt += 1
            continue

        if 500 <= status < 600:
            attempt += 1
            if attempt < max_attempts:
                wait = _BACKOFF_BASE * (2 ** (attempt - 1))
                _logger.warning(
                    "Gemini API returned HTTP %d (attempt %d/%d); "
                    "retrying in %.1fs",
                    status,
                    attempt,
                    max_attempts,
                    wait,
                )
                time.sleep(wait)
                continue
            # Exhausted retries
            raise GeminiUnavailableError(
                f"Gemini API returned HTTP {status} after {_MAX_5XX_RETRIES} retries"
            )

        # 4xx (not 429) — do not retry
        raise GeminiUnavailableError(
            f"Gemini API returned non-retryable HTTP {status}: {response.text[:200]}"
        )

    raise GeminiUnavailableError(
        f"Gemini API exhausted all {max_attempts} attempts"
    )


def _parse_response(response_json: dict) -> tuple[str, str]:
    """
    Extract the generated text from the Gemini API response JSON.

    Returns:
        ``(rationale_text, ai_quality_indicator)``

    Raises:
        GeminiUnavailableError: If the response structure is unexpected.
    """
    try:
        candidates = response_json.get("candidates", [])
        if not candidates:
            raise GeminiUnavailableError("Gemini API returned no candidates")

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise GeminiUnavailableError("Gemini API returned no content parts")

        raw_text: str = parts[0].get("text", "")
        if not raw_text:
            raise GeminiUnavailableError("Gemini API returned empty text")

        return extract_confidence(raw_text)

    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiUnavailableError(
            f"Unexpected Gemini API response structure: {exc}"
        ) from exc


def _parse_retry_after(response: requests.Response) -> float:
    """Parse the ``Retry-After`` header value in seconds (default 5s)."""
    header = response.headers.get("Retry-After", "")
    try:
        return float(header)
    except (ValueError, TypeError):
        return 5.0


def _reset_cache() -> None:
    """
    Reset the module-level API key cache.

    Intended for use in tests only.
    """
    global _cached_api_key
    _cached_api_key = None

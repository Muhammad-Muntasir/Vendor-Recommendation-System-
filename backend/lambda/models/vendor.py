"""
VendorProfile dataclass — represents a service vendor registered on RetailFixIt.

Vendor profiles are stored in the DynamoDB ai-vrs-vendors table and loaded
by the scoring engine (handlers/vendor_scoring.py) when a new job arrives.
Each profile is validated before scoring; invalid profiles are excluded and
a VendorProfileDataQualityErrors CloudWatch metric is emitted.

Requirements: 18.2
"""

from dataclasses import dataclass

# ── Allowed availability states ───────────────────────────────────────────────
# Maps directly to availabilityScore in the scoring engine:
#   available   → 1.0  (full weight applied)
#   busy        → 0.5  (half weight — vendor can take more work but is occupied)
#   unavailable → 0.0  (excluded from scoring entirely)
VALID_AVAILABILITY_VALUES = {"available", "busy", "unavailable"}


@dataclass
class VendorProfile:
    """
    Represents a vendor's profile used for scoring and ranking.

    All numeric fields are normalised to [0.0, 1.0] by the scoring engine
    before being combined into a weighted totalScore. See the normalization
    rules in handlers/vendor_scoring.py for the exact formulas.
    """

    # Unique identifier for this vendor (UUID v4)
    vendorId: str

    # Display name shown in the Admin UI on VendorCard components
    name: str

    # Historical job completion rate — used directly as completionScore
    # Range: [0.0, 1.0] where 1.0 = 100% completion rate
    completionRate: float

    # Current availability state — must be one of VALID_AVAILABILITY_VALUES
    # Unavailable vendors are filtered out before scoring begins
    availability: str

    # Rate of jobs that required rework — inverted for scoring (lower = better)
    # reworkScore = 1.0 - reworkRate
    # Range: [0.0, 1.0] where 0.0 = no rework needed
    reworkRate: float

    # Vendor's base location, e.g. "Austin, TX"
    # Compared against job location for proximity scoring:
    #   exact match → 1.0, same state → 0.5, different state → 0.0
    location: str

    # List of job types this vendor specialises in, e.g. ["plumbing", "hvac"]
    # Used for binary specialization matching: job.type in specializations → 1.0
    specializations: list

    # Average time (in hours) to respond to a new job request
    # Normalised: max(0.0, 1.0 - avgResponseTime / 24.0)
    # Capped at 0.0 for response times >= 24 hours
    avgResponseTime: float

    # Number of historical SLA breaches (lower is better)
    # Normalised: max(0.0, 1.0 - slaBreachCount / 10.0)
    # Capped at 0.0 for 10+ breaches
    slaBreachCount: int

    # Current number of active jobs assigned to this vendor (lower is better)
    # Normalised: max(0.0, 1.0 - activeJobs / 20.0)
    # Capped at 0.0 for 20+ active jobs
    # Also used as tie-breaker in rank_vendors() — fewer active jobs ranks higher
    activeJobs: int

    def __post_init__(self) -> None:
        """Validate field values immediately after dataclass construction."""
        # Reject invalid availability values — scoring engine relies on exact strings
        if self.availability not in VALID_AVAILABILITY_VALUES:
            raise ValueError(
                f"Invalid availability '{self.availability}'. "
                f"Must be one of: {sorted(VALID_AVAILABILITY_VALUES)}"
            )
        # Enforce [0.0, 1.0] range — values outside this break the scoring formula
        if not (0.0 <= self.completionRate <= 1.0):
            raise ValueError(
                f"completionRate must be in [0.0, 1.0], got {self.completionRate}"
            )
        if not (0.0 <= self.reworkRate <= 1.0):
            raise ValueError(
                f"reworkRate must be in [0.0, 1.0], got {self.reworkRate}"
            )

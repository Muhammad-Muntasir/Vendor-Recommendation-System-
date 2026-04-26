"""
JobEvent dataclass — represents a service job created on the RetailFixIt platform.

This model is the central data structure that flows through the entire scoring
pipeline. It is created when an Admin submits a new job via POST /jobs, then
published as a JobCreated_Event to EventBridge, consumed from SQS, and used
by the vendor scoring engine to match and rank vendors.

Requirements: 4.5, 18.1
"""

from dataclasses import dataclass

# ── Allowed values for the urgency field ──────────────────────────────────────
# These map to UI display and scoring behaviour:
#   Critical → triggers CriticalJobWarning in the UI, requires Admin acknowledgment
#   High     → standard priority
#   Medium   → normal priority
#   Low      → lowest priority
VALID_URGENCY_VALUES = {"Low", "Medium", "High", "Critical"}

# ── Allowed values for the status field ───────────────────────────────────────
# State machine:
#   Pending      → job created, awaiting vendor recommendation
#   Recommended  → vendor recommendations generated, awaiting Admin decision
#   Assigned     → Admin accepted a recommendation (AI or override)
#   Override     → Admin manually selected a different vendor
VALID_STATUS_VALUES = {"Pending", "Recommended", "Assigned", "Override"}


@dataclass
class JobEvent:
    """
    Represents a service job event payload.

    Instances are created by:
    - utils/validator.validate_job_event() when parsing incoming API requests
    - utils/validator.validate_job_event() when consuming SQS messages

    All fields are required. schemaVersion and status have defaults applied
    by the validator if not present in the raw dict.
    """

    # Unique identifier for this job (UUID v4 generated at creation time)
    jobId: str

    # Type of service required, e.g. "plumbing", "electrical", "hvac"
    # Used for specialization matching in the scoring engine
    type: str

    # Geographic location of the job, e.g. "Austin, TX"
    # Used for location proximity scoring
    location: str

    # Priority level — must be one of VALID_URGENCY_VALUES
    # Critical jobs require explicit Admin acknowledgment before acceptance
    urgency: str

    # ISO 8601 deadline by which the job must be completed
    # Used in the CriticalJobWarning component (< 2 hours triggers warning)
    slaDeadline: str

    # Human-readable description of the work required
    # Included in the Gemini API prompt for AI rationale generation
    description: str

    # ISO 8601 timestamp when the job was created
    createdAt: str

    # Event schema version for forward-compatible evolution (currently "1.0")
    schemaVersion: str

    # Current lifecycle status — must be one of VALID_STATUS_VALUES
    status: str

    def __post_init__(self) -> None:
        """Validate field values immediately after dataclass construction."""
        # Reject invalid urgency values early to prevent silent scoring errors
        if self.urgency not in VALID_URGENCY_VALUES:
            raise ValueError(
                f"Invalid urgency '{self.urgency}'. "
                f"Must be one of: {sorted(VALID_URGENCY_VALUES)}"
            )
        # Reject invalid status values to prevent invalid state transitions
        if self.status not in VALID_STATUS_VALUES:
            raise ValueError(
                f"Invalid status '{self.status}'. "
                f"Must be one of: {sorted(VALID_STATUS_VALUES)}"
            )

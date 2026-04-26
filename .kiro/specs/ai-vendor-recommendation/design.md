# Design Document: AI Vendor Recommendation System (AI-VRS)

## Overview

The AI Vendor Recommendation System (AI-VRS) is a new feature for the RetailFixIt platform that automates intelligent vendor selection for service jobs. When a new job is created, the system evaluates all eligible vendors, ranks the top 5 candidates using a hybrid scoring engine, and presents human-readable explanations with confidence indicators to administrators via a React-based Admin UI.

The system combines deterministic rule-based scoring with AI-generated rationale via Google Gemini 2.5 Flash. Administrators retain full override authority, and every AI decision is logged for compliance and future model improvement. The AI operates in an advisory capacity only — no vendor is ever automatically assigned without Admin confirmation.

### Key Design Goals

- **Advisory-only AI**: Recommendations are suggestions; humans confirm all assignments.
- **Resilience**: Fallback rule-based scoring ensures job dispatch is never blocked by an AI outage.
- **Auditability**: Every decision — AI or human — is logged with full context and PII masking.
- **Cost efficiency**: Single Lambda function with internal routing, DynamoDB on-demand billing, no idle compute.
- **Observability**: CloudWatch metrics and alarms for drift detection, fallback activations, and data quality.

---

## Architecture

### High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RetailFixIt Admin UI                               │
│                    (React 18 + Vite, React Router v6)                       │
│  LoginPage  Dashboard  JobsPage  RecommendationsPage  OverridePage  AuditLog│
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │ HTTPS + JWT (Authorization header)
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AWS API Gateway (REST API)                                │
│              Cognito Authorizer (JWT validation on all routes)               │
│  POST /jobs  GET /jobs  GET /jobs/{id}  GET /recommendations/{jobId}        │
│  POST /recommendations/{jobId}/accept  POST /override                       │
│  GET /audit-logs  GET /audit-logs/{logId}  GET /dashboard/metrics           │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │ Proxy integration
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AWS Lambda (Single Function)                              │
│  handler.py → router.py → handlers/                                         │
│  ┌──────────┐ ┌──────────────┐ ┌────────────────┐ ┌──────────┐ ┌────────┐ │
│  │job_created│ │vendor_scoring│ │recommendation  │ │ override │ │ query  │ │
│  └──────────┘ └──────────────┘ └────────────────┘ └──────────┘ └────────┘ │
│  ┌──────────┐                                                               │
│  │   auth   │ (Cognito post-confirm trigger)                                │
│  └──────────┘                                                               │
└──────┬───────────────────────────────────────────────────────────┬──────────┘
       │ Read/Write                                                 │ Publish events
       ▼                                                            ▼
┌──────────────────────┐    ┌──────────────────────────────────────────────────┐
│   AWS DynamoDB       │    │              AWS EventBridge                     │
│  Jobs table          │    │  JobCreated rule → SQS → Lambda                  │
│  Vendors table       │    │  VendorRecommendationGenerated rule              │
│  Recommendations     │    │  VendorOverrideRecorded rule                     │
│  AuditLog table      │    │  NoEligibleVendors rule                          │
│  Users table         │    └──────────────────────────────────────────────────┘
└──────────────────────┘                        │
                                                ▼
┌──────────────────────┐    ┌──────────────────────────────────────────────────┐
│      AWS S3          │    │                 AWS SQS                          │
│  lambda-zip bucket   │    │  vendor-scoring-queue (main)                     │
│  logs bucket (enc.)  │    │  vendor-scoring-dlq (Dead Letter Queue)          │
│  override-feedback   │    └──────────────────────────────────────────────────┘
│  model-version.txt   │
└──────────────────────┘
┌──────────────────────┐    ┌──────────────────────────────────────────────────┐
│  AWS Secrets Manager │    │              AWS Cognito                         │
│  gemini-api-key      │    │  User Pool (self-registration + login)           │
└──────────────────────┘    │  App Client (JWT issuance)                       │
                            │  Post-Confirmation Lambda trigger                │
                            └──────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────────┐
│                         AWS CloudWatch                                       │
│  Log groups (Lambda, 90d retention)  Audit log exports (365d retention)     │
│  Alarms: HighLowConfidenceRate, HighOverrideRate, FallbackScorerActivations  │
│  Metrics: VendorProfileDataQualityErrors, RecommendationConfidenceDistrib.   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Event Flow: Job Created → Recommendation Generated

```
Admin UI
  │
  │ POST /jobs
  ▼
API Gateway → Lambda (query.py creates job record in DynamoDB)
  │
  │ Lambda publishes JobCreated_Event
  ▼
EventBridge (JobCreated rule)
  │
  ▼
SQS (vendor-scoring-queue)
  │
  │ Lambda triggered by SQS message
  ▼
Lambda handler.py → router.py → job_created.py
  │
  ├─→ vendor_scoring.py
  │     Reads all VendorProfiles from DynamoDB
  │     Validates each VendorProfile (excludes invalid, logs warnings)
  │     Computes ScoreFactors for each eligible vendor
  │     Ranks top 5 by total score
  │     Calculates Confidence_Level
  │
  ├─→ recommendation.py
  │     Fetches Gemini API key from Secrets Manager (cached)
  │     Reads Model_Version from S3 (cached)
  │     Calls Gemini 2.5 Flash API for each top-5 vendor rationale
  │     Falls back to rule-based rationale on timeout/error
  │     Attaches rationale + confidence to each Recommendation
  │     Writes Recommendations to DynamoDB
  │
  ├─→ audit_logger.py
  │     Masks PII via pii_masker.py
  │     Writes AuditLog to DynamoDB + S3
  │
  └─→ EventBridge: publishes VendorRecommendationGenerated_Event
```

---

## Components and Interfaces

### Lambda Entry Point and Router

**`handler.py`** — Single AWS Lambda entry point. Receives all events (API Gateway proxy, SQS, EventBridge, Cognito trigger) and delegates to `router.py`.

```python
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    return router.route(event, context)
```

**`router.py`** — Inspects the event structure to determine the source and dispatches to the correct handler module.

| Event Source | Detection Logic | Handler Module |
|---|---|---|
| API Gateway | `event.get("httpMethod")` present | `handlers/query.py` or `handlers/override.py` based on path |
| SQS | `event.get("Records")[0]["eventSource"] == "aws:sqs"` | `handlers/job_created.py` |
| EventBridge (direct) | `event.get("source")` present | `handlers/job_created.py` |
| Cognito Post-Confirm | `event.get("triggerSource") == "PostConfirmation_ConfirmSignUp"` | `handlers/auth.py` |

The router returns a standard API Gateway response dict for HTTP events and a plain dict for async events.

### Handler Modules

**`handlers/job_created.py`**
- Entry point for SQS-delivered `JobCreated_Event` messages
- Validates the JobEvent payload (all required fields present and non-null)
- Rejects malformed messages to DLQ by raising an exception (SQS will route to DLQ after max retries)
- Orchestrates the scoring pipeline: calls `vendor_scoring`, then `recommendation`, then `audit_logger`
- Publishes `VendorRecommendationGenerated_Event` to EventBridge on success
- Publishes `NoEligibleVendors_Event` if no eligible vendors found

**`handlers/vendor_scoring.py`**
- Reads all VendorProfiles from DynamoDB via `services/dynamodb.py`
- Filters out vendors with `availability == "unavailable"`
- Validates each VendorProfile; excludes invalid profiles and emits `VendorProfileDataQualityErrors` metric
- Computes `ScoreFactors` for each eligible vendor using the weighted scoring formula
- Ranks vendors by `totalScore` descending; breaks ties by `activeJobs` ascending
- Returns top 5 (or fewer if < 5 eligible vendors)
- Calculates `Confidence_Level` from score distribution
- Attaches `modelVersion` from the cached S3 value

**`handlers/recommendation.py`**
- Receives ranked `ScoreFactors` list from `vendor_scoring`
- Calls `services/ai_client.py` for each vendor to get Gemini rationale
- Handles AI failures gracefully: falls back to `services/fallback_scorer.py`
- Assembles final `Recommendation` records with rationale, confidence, and model version
- Writes `Recommendation` records to DynamoDB
- Emits `FallbackScorerActivations` CloudWatch metric when fallback is used

**`handlers/override.py`**
- Handles `POST /override` HTTP requests
- Validates override payload: jobId, vendorId, overrideReason (10–500 chars), userId
- Checks job eligibility (not already confirmed)
- Writes override record to DynamoDB AuditLog and S3 override feedback bucket
- Publishes `VendorOverrideRecorded_Event` to EventBridge
- Returns 400 on validation failure, 409 on ineligible job, 200 on success

**`handlers/auth.py`**
- Handles Cognito Post-Confirmation trigger
- Creates a `User` record in DynamoDB Users table with userId, email, createdAt
- Returns the Cognito event unchanged (required by Cognito trigger contract)

**`handlers/query.py`**
- Handles all read-oriented HTTP endpoints:
  - `GET /jobs` — paginated job list with optional status/date filters
  - `GET /jobs/{jobId}` — single job detail
  - `GET /recommendations/{jobId}` — ranked recommendations for a job
  - `POST /recommendations/{jobId}/accept` — record AI acceptance in AuditLog
  - `GET /audit-logs` — paginated audit log with filters
  - `GET /audit-logs/{logId}` — single audit log detail
  - `GET /dashboard/metrics` — summary metrics for dashboard
  - `POST /jobs` — create a new job, publish `JobCreated_Event`

### Service Modules

**`services/dynamodb.py`**
- Wraps `boto3` DynamoDB resource with typed read/write helpers
- Methods: `get_item`, `put_item`, `query`, `scan`, `update_item`
- All writes use conditional expressions where appropriate to prevent overwrites
- Raises `DynamoDBWriteError` on failure (used by audit_logger retry logic)

**`services/s3.py`**
- Wraps `boto3` S3 client
- Methods: `read_object`, `write_object`, `write_json_object`
- Used for: model version reads, audit log writes, override feedback writes

**`services/ai_client.py`**
- Manages Gemini 2.5 Flash API communication
- Fetches API key from `services/secrets.py` at cold start; caches in module-level variable
- Builds structured prompt from `ScoreFactors` + job context (type, location, urgency, slaDeadline)
- Sends HTTP POST to Gemini API with 8-second timeout
- Retry logic: 2x on 5xx with exponential backoff; 0x on 4xx (except 429); respects `Retry-After` on 429 (max 30s wait)
- Returns `(rationale_text: str, ai_quality_indicator: str)` on success
- Raises `GeminiUnavailableError` on exhausted retries or timeout

**`services/secrets.py`**
- Fetches the Gemini API key from AWS Secrets Manager by secret name
- Caches the key in a module-level variable after first fetch (cold start only)
- Raises `SecretFetchError` if the secret cannot be retrieved

**`services/fallback_scorer.py`**
- Pure function: takes `ScoreFactors` and returns a human-readable rationale string
- Constructs rationale by describing the top contributing score dimensions in plain English
- Example output: "Vendor ranked #1 due to high completion rate (0.94), strong availability, and close location proximity. Rework rate is within acceptable range."
- Returns structurally identical output to AI rationale (same field names)

**`services/audit_logger.py`**
- Assembles `AuditLog` records from input parameters
- Calls `pii_masker.py` before any write
- Writes to DynamoDB AuditLog table with retry (3x, exponential backoff)
- Writes to S3 logs bucket (unmasked, SSE-S3 encrypted)
- Emits `RecommendationConfidenceDistribution` CloudWatch metric
- Logs DynamoDB write failures to CloudWatch after exhausting retries

**`services/pii_masker.py`**
- Scans log input/output dicts for known PII field names (email, phone, address, name patterns)
- Replaces PII values with `[REDACTED]`
- Returns a deep copy of the input with PII masked; original is preserved for S3 write

### Utility Modules

**`utils/logger.py`**
- Structured JSON logging to CloudWatch via Python `logging` module
- Includes: timestamp, level, handler name, jobId (when available), message

**`utils/validator.py`**
- `validate_job_event(event: dict) -> JobEvent` — validates and parses JobEvent fields
- `validate_vendor_profile(profile: dict) -> VendorProfile` — validates VendorProfile fields
- `validate_override_request(body: dict) -> OverrideRequest` — validates override payload
- Raises `ValidationError` with field-level detail on failure

**`utils/model_version.py`**
- Reads `model-version.txt` from S3 at cold start
- Caches the version string in a module-level variable
- Returns cached value on subsequent calls within the same Lambda invocation
- Falls back to `"0.0.0"` and logs a warning if S3 read fails

---

## Data Models

All models are defined in `backend/lambda/models/` as Python dataclasses with type annotations.

### JobEvent (`models/job.py`)

| Field | Type | Description |
|---|---|---|
| `jobId` | `str` (UUID v4) | Unique job identifier |
| `type` | `str` | Job type (e.g., "plumbing", "electrical") |
| `location` | `str` | Job location (city/region string) |
| `urgency` | `str` | One of: "Low", "Medium", "High", "Critical" |
| `slaDeadline` | `str` (ISO 8601) | SLA deadline timestamp |
| `description` | `str` | Human-readable job description |
| `createdAt` | `str` (ISO 8601) | Job creation timestamp |
| `schemaVersion` | `str` | Event schema version (e.g., "1.0") |
| `status` | `str` | One of: "Pending", "Recommended", "Assigned", "Override" |

### VendorProfile (`models/vendor.py`)

| Field | Type | Description |
|---|---|---|
| `vendorId` | `str` (UUID v4) | Unique vendor identifier |
| `name` | `str` | Vendor display name |
| `completionRate` | `float` [0.0–1.0] | Historical job completion rate |
| `availability` | `str` | One of: "available", "busy", "unavailable" |
| `reworkRate` | `float` [0.0–1.0] | Rate of jobs requiring rework (lower is better) |
| `location` | `str` | Vendor base location |
| `specializations` | `list[str]` | List of job type specializations |
| `avgResponseTime` | `float` | Average response time in hours (lower is better) |
| `slaBreachCount` | `int` | Historical SLA breach count (lower is better) |
| `activeJobs` | `int` | Current number of active jobs (lower is better) |

### ScoreFactors (`models/score.py`)

| Field | Type | Description |
|---|---|---|
| `vendorId` | `str` | Reference to VendorProfile |
| `jobId` | `str` | Reference to JobEvent |
| `completionScore` | `float` [0.0–1.0] | Normalized completion rate score |
| `availabilityScore` | `float` [0.0–1.0] | Availability score (1.0=available, 0.5=busy) |
| `locationScore` | `float` [0.0–1.0] | Proximity score (1.0=same location) |
| `specializationScore` | `float` [0.0–1.0] | Specialization match score |
| `reworkScore` | `float` [0.0–1.0] | Inverted rework rate score |
| `responseTimeScore` | `float` [0.0–1.0] | Inverted response time score |
| `slaBreachScore` | `float` [0.0–1.0] | Inverted SLA breach count score |
| `activeJobsScore` | `float` [0.0–1.0] | Inverted active job count score |
| `totalScore` | `float` [0.0–1.0] | Weighted composite score |
| `confidence` | `str` | One of: "High", "Medium", "Low" |
| `modelVersion` | `str` | Model version string (MAJOR.MINOR.PATCH) |
| `isAIGenerated` | `bool` | True if rationale was AI-generated |

### Recommendation (`models/score.py`)

| Field | Type | Description |
|---|---|---|
| `jobId` | `str` | Reference to JobEvent |
| `rank` | `int` | Rank position (1–5) |
| `vendorId` | `str` | Reference to VendorProfile |
| `totalScore` | `float` | Composite score |
| `scoreFactors` | `ScoreFactors` | Full score breakdown |
| `rationale` | `str` | Human-readable explanation |
| `confidence` | `str` | One of: "High", "Medium", "Low" |
| `modelVersion` | `str` | Model version string |
| `timestamp` | `str` (ISO 8601) | Recommendation generation timestamp |
| `isAIGenerated` | `bool` | True if rationale was AI-generated |

### AuditLog (`models/audit_log.py`)

| Field | Type | Description |
|---|---|---|
| `logId` | `str` (UUID v4) | Unique log record identifier |
| `jobId` | `str` | Reference to JobEvent |
| `vendorId` | `str` | Top-ranked or selected vendor |
| `action` | `str` | One of: "AI_RECOMMENDATION", "ADMIN_OVERRIDE", "FALLBACK_RECOMMENDATION", "AI_RECOMMENDATION_ACCEPTED", "DLQ_FAILURE" |
| `input` | `dict` | Masked input context (ScoreFactors, job details) |
| `output` | `dict` | Masked output (ranked list, rationale, confidence) |
| `overrideReason` | `str \| None` | Override reason text (ADMIN_OVERRIDE only) |
| `modelVersion` | `str` | Model version string |
| `piiMasked` | `bool` | Always True for DynamoDB records |
| `timestamp` | `str` (ISO 8601) | Log record creation timestamp |
| `aiUnavailable` | `bool \| None` | True for FALLBACK_RECOMMENDATION records |

### User (`models/` — inline in auth.py)

| Field | Type | Description |
|---|---|---|
| `userId` | `str` | Cognito sub (UUID) |
| `email` | `str` | User email address |
| `createdAt` | `str` (ISO 8601) | Account creation timestamp |


---

## Scoring Algorithm (Low-Level Design)

The scoring engine computes a `totalScore` for each eligible vendor as a weighted sum of 8 normalized dimensions.

### Dimension Weights

| Dimension | Weight | Field in ScoreFactors |
|---|---|---|
| Completion Rate | 0.25 | `completionScore` |
| Availability | 0.20 | `availabilityScore` |
| Rework Rate | 0.15 | `reworkScore` |
| Location Proximity | 0.15 | `locationScore` |
| Specialization Match | 0.10 | `specializationScore` |
| Avg Response Time | 0.08 | `responseTimeScore` |
| SLA Breach Count | 0.04 | `slaBreachScore` |
| Active Jobs | 0.03 | `activeJobsScore` |

All weights sum to 1.00.

### Normalization Rules

Each raw vendor attribute is normalized to the range [0.0, 1.0] before weighting:

| Dimension | Raw Value | Normalization Formula |
|---|---|---|
| `completionRate` | float [0.0–1.0] | Used directly: `completionScore = completionRate` |
| `availability` | enum | `1.0` if "available", `0.5` if "busy", `0.0` if "unavailable" (excluded from scoring) |
| `reworkRate` | float [0.0–1.0] | Inverted: `reworkScore = 1.0 - reworkRate` |
| `location` | string | `1.0` if vendor location == job location (exact match), `0.5` if same region, `0.0` otherwise |
| `specializations` | list[str] | `1.0` if job type in vendor specializations, `0.0` otherwise |
| `avgResponseTime` | float (hours) | `max(0.0, 1.0 - (avgResponseTime / 24.0))` — capped at 0.0 for 24+ hour response times |
| `slaBreachCount` | int | `max(0.0, 1.0 - (slaBreachCount / 10.0))` — capped at 0.0 for 10+ breaches |
| `activeJobs` | int | `max(0.0, 1.0 - (activeJobs / 20.0))` — capped at 0.0 for 20+ active jobs |

### Total Score Formula

```
totalScore = (0.25 * completionScore)
           + (0.20 * availabilityScore)
           + (0.15 * reworkScore)
           + (0.15 * locationScore)
           + (0.10 * specializationScore)
           + (0.08 * responseTimeScore)
           + (0.04 * slaBreachScore)
           + (0.03 * activeJobsScore)
```

### Confidence Level Logic

After ranking, the `Confidence_Level` for the top recommendation is determined as follows:

```
top_score  = ranked_vendors[0].totalScore
rank2_score = ranked_vendors[1].totalScore if len(ranked_vendors) >= 2 else 0.0
score_gap  = top_score - rank2_score
all_within_005 = (max(v.totalScore for v in ranked_vendors) -
                  min(v.totalScore for v in ranked_vendors)) <= 0.05

if top_score > 0.75 AND score_gap > 0.10:
    confidence = "High"
elif top_score < 0.50 OR all_within_005:
    confidence = "Low"
else:
    confidence = "Medium"
```

The same `Confidence_Level` is applied to all `Recommendation` records produced for that job.

### Tie-Breaking

When two vendors share an identical `totalScore` (after floating-point rounding to 6 decimal places), the vendor with the **lower `activeJobs`** count ranks higher. If `activeJobs` is also equal, the vendor with the lower `vendorId` (lexicographic) is ranked higher to ensure deterministic output.

### Python Pseudocode

```python
WEIGHTS = {
    "completionScore":    0.25,
    "availabilityScore":  0.20,
    "reworkScore":        0.15,
    "locationScore":      0.15,
    "specializationScore":0.10,
    "responseTimeScore":  0.08,
    "slaBreachScore":     0.04,
    "activeJobsScore":    0.03,
}

def normalize(vendor: VendorProfile, job: JobEvent) -> ScoreFactors:
    completion_score    = vendor.completionRate
    availability_score  = {"available": 1.0, "busy": 0.5, "unavailable": 0.0}[vendor.availability]
    rework_score        = 1.0 - vendor.reworkRate
    location_score      = 1.0 if vendor.location == job.location else (0.5 if same_region(vendor.location, job.location) else 0.0)
    specialization_score= 1.0 if job.type in vendor.specializations else 0.0
    response_time_score = max(0.0, 1.0 - (vendor.avgResponseTime / 24.0))
    sla_breach_score    = max(0.0, 1.0 - (vendor.slaBreachCount / 10.0))
    active_jobs_score   = max(0.0, 1.0 - (vendor.activeJobs / 20.0))

    total = sum(WEIGHTS[k] * v for k, v in {
        "completionScore":     completion_score,
        "availabilityScore":   availability_score,
        "reworkScore":         rework_score,
        "locationScore":       location_score,
        "specializationScore": specialization_score,
        "responseTimeScore":   response_time_score,
        "slaBreachScore":      sla_breach_score,
        "activeJobsScore":     active_jobs_score,
    }.items())

    return ScoreFactors(
        vendorId=vendor.vendorId, jobId=job.jobId,
        completionScore=completion_score, availabilityScore=availability_score,
        reworkScore=rework_score, locationScore=location_score,
        specializationScore=specialization_score, responseTimeScore=response_time_score,
        slaBreachScore=sla_breach_score, activeJobsScore=active_jobs_score,
        totalScore=round(total, 6), modelVersion=get_model_version(),
        isAIGenerated=False,
    )

def rank_vendors(score_factors: list[ScoreFactors]) -> list[ScoreFactors]:
    eligible = [sf for sf in score_factors if sf.availabilityScore > 0.0]
    return sorted(eligible, key=lambda sf: (-sf.totalScore, sf.activeJobs, sf.vendorId))[:5]

def compute_confidence(ranked: list[ScoreFactors]) -> str:
    if not ranked:
        return "Low"
    top = ranked[0].totalScore
    rank2 = ranked[1].totalScore if len(ranked) >= 2 else 0.0
    gap = top - rank2
    all_scores = [sf.totalScore for sf in ranked]
    all_within = (max(all_scores) - min(all_scores)) <= 0.05
    if top > 0.75 and gap > 0.10:
        return "High"
    elif top < 0.50 or all_within:
        return "Low"
    return "Medium"
```

---

## Gemini API Prompt Design

### Prompt Template

The following template is rendered by `services/ai_client.py` before each Gemini API call. Variables in `{curly_braces}` are substituted at runtime.

```
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

Respond only with the rationale text followed by the confidence indicator. No preamble.
```

### Input Variables

| Variable | Source | Example |
|---|---|---|
| `job_type` | `JobEvent.type` | `"plumbing"` |
| `job_location` | `JobEvent.location` | `"Austin, TX"` |
| `job_urgency` | `JobEvent.urgency` | `"High"` |
| `sla_deadline` | `JobEvent.slaDeadline` | `"2025-08-01T14:00:00Z"` |
| `job_description` | `JobEvent.description` | `"Burst pipe in commercial kitchen"` |
| `rank` | Position in ranked list | `1` |
| `completion_score` | `ScoreFactors.completionScore` | `0.94` |
| `availability_score` | `ScoreFactors.availabilityScore` | `1.0` |
| `rework_score` | `ScoreFactors.reworkScore` | `0.88` |
| `location_score` | `ScoreFactors.locationScore` | `1.0` |
| `specialization_score` | `ScoreFactors.specializationScore` | `1.0` |
| `response_time_score` | `ScoreFactors.responseTimeScore` | `0.75` |
| `sla_breach_score` | `ScoreFactors.slaBreachScore` | `0.90` |
| `active_jobs_score` | `ScoreFactors.activeJobsScore` | `0.85` |
| `total_score` | `ScoreFactors.totalScore` | `0.932` |

### Expected Output Format

```
This vendor is ranked #1 due to a near-perfect completion rate (0.94) and full availability,
making them the most reliable choice for this urgent plumbing job in Austin, TX.
Their strong specialization match and zero location penalty further reinforce this ranking.
CONFIDENCE: HIGH
```

### Confidence Indicator Extraction

`ai_client.py` parses the last line of the Gemini response for the confidence indicator:

```python
def extract_confidence(response_text: str) -> tuple[str, str]:
    lines = response_text.strip().splitlines()
    last_line = lines[-1].strip().upper()
    if last_line.startswith("CONFIDENCE:"):
        ai_indicator = last_line.split(":", 1)[1].strip()  # "HIGH", "MEDIUM", or "LOW"
        rationale = "\n".join(lines[:-1]).strip()
        return rationale, ai_indicator
    # If no confidence line found, treat as LOW quality
    return response_text.strip(), "LOW"
```

The `ai_indicator` from Gemini is one input to the `compute_confidence()` function in `vendor_scoring.py`. The final `Confidence_Level` is determined by the score distribution logic (see Scoring Algorithm section), with the AI indicator used as a secondary signal: if the AI returns `LOW` but the score distribution would yield `Medium`, the final confidence is downgraded to `Low`.

---

## API Contracts

All endpoints are protected by the Cognito Authorizer. Requests must include `Authorization: Bearer <access_token>`.

### Error Response Format (all endpoints)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description of the error",
    "details": { "field": "reason" }
  }
}
```

Common HTTP status codes: `400` Bad Request, `401` Unauthorized, `404` Not Found, `409` Conflict, `500` Internal Server Error.

---

### POST /jobs

Creates a new job and publishes a `JobCreated_Event`.

**Request Body**
```json
{
  "type": "plumbing",
  "location": "Austin, TX",
  "urgency": "High",
  "slaDeadline": "2025-08-01T14:00:00Z",
  "description": "Burst pipe in commercial kitchen requiring immediate repair."
}
```

| Field | Type | Required | Constraints |
|---|---|---|---|
| `type` | string | Yes | Non-empty |
| `location` | string | Yes | Non-empty |
| `urgency` | string | Yes | One of: Low, Medium, High, Critical |
| `slaDeadline` | string | Yes | ISO 8601 datetime, must be in the future |
| `description` | string | Yes | 10–1000 characters |

**Response — 201 Created**
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "type": "plumbing",
  "location": "Austin, TX",
  "urgency": "High",
  "slaDeadline": "2025-08-01T14:00:00Z",
  "description": "Burst pipe in commercial kitchen requiring immediate repair.",
  "status": "Pending",
  "createdAt": "2025-07-28T10:00:00Z",
  "schemaVersion": "1.0"
}
```

---

### GET /jobs

Returns a paginated list of jobs with optional filters.

**Query Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `status` | string | No | Filter by job status (Pending, Recommended, Assigned, Override) |
| `from` | string | No | ISO 8601 date — filter jobs created on or after this date |
| `to` | string | No | ISO 8601 date — filter jobs created on or before this date |
| `limit` | integer | No | Page size (default: 20, max: 100) |
| `nextToken` | string | No | Pagination cursor from previous response |

**Response — 200 OK**
```json
{
  "items": [
    {
      "jobId": "a1b2c3d4-...",
      "type": "plumbing",
      "location": "Austin, TX",
      "urgency": "High",
      "slaDeadline": "2025-08-01T14:00:00Z",
      "status": "Recommended",
      "createdAt": "2025-07-28T10:00:00Z"
    }
  ],
  "count": 1,
  "nextToken": "eyJsYXN0S2V5IjoiYTFiMmMzZDQifQ=="
}
```

---

### GET /jobs/{jobId}

Returns full detail for a single job.

**Path Parameters:** `jobId` (UUID v4)

**Response — 200 OK**
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "type": "plumbing",
  "location": "Austin, TX",
  "urgency": "High",
  "slaDeadline": "2025-08-01T14:00:00Z",
  "description": "Burst pipe in commercial kitchen requiring immediate repair.",
  "status": "Recommended",
  "createdAt": "2025-07-28T10:00:00Z",
  "schemaVersion": "1.0"
}
```

**Response — 404 Not Found** when `jobId` does not exist.

---

### GET /recommendations/{jobId}

Returns the ranked vendor recommendations for a job.

**Path Parameters:** `jobId` (UUID v4)

**Response — 200 OK**
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "modelVersion": "1.2.0",
  "isFallback": false,
  "recommendations": [
    {
      "rank": 1,
      "vendorId": "v1v1v1v1-...",
      "vendorName": "AcePlumbing Co.",
      "totalScore": 0.932,
      "confidence": "High",
      "rationale": "This vendor is ranked #1 due to a near-perfect completion rate...",
      "isAIGenerated": true,
      "scoreFactors": {
        "completionScore": 0.94,
        "availabilityScore": 1.0,
        "reworkScore": 0.88,
        "locationScore": 1.0,
        "specializationScore": 1.0,
        "responseTimeScore": 0.75,
        "slaBreachScore": 0.90,
        "activeJobsScore": 0.85
      }
    }
  ],
  "timestamp": "2025-07-28T10:00:05Z"
}
```

**Response — 404 Not Found** when no recommendations exist for `jobId`.

---

### POST /recommendations/{jobId}/accept

Records Admin acceptance of the top AI recommendation.

**Path Parameters:** `jobId` (UUID v4)

**Request Body** — empty body accepted; userId is extracted from the JWT.

**Response — 200 OK**
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "action": "AI_RECOMMENDATION_ACCEPTED",
  "logId": "log-uuid-here",
  "timestamp": "2025-07-28T10:01:00Z"
}
```

**Response — 409 Conflict** when job already has a confirmed vendor assignment.

---

### POST /override

Records an Admin vendor override.

**Request Body**
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "selectedVendorId": "v2v2v2v2-...",
  "overrideReason": "Selected vendor has prior relationship with this client and specific equipment on-site."
}
```

| Field | Type | Required | Constraints |
|---|---|---|---|
| `jobId` | string | Yes | UUID v4, must reference an existing job |
| `selectedVendorId` | string | Yes | UUID v4, must reference an eligible vendor |
| `overrideReason` | string | Yes | 10–500 characters |

**Response — 200 OK**
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "selectedVendorId": "v2v2v2v2-...",
  "action": "ADMIN_OVERRIDE",
  "logId": "log-uuid-here",
  "timestamp": "2025-07-28T10:02:00Z"
}
```

**Response — 400 Bad Request** when `overrideReason` is missing or out of range.
**Response — 409 Conflict** when job is already confirmed and no longer eligible for override.

---

### GET /audit-logs

Returns a paginated list of audit log records with optional filters.

**Query Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `action` | string | No | Filter by action type |
| `from` | string | No | ISO 8601 date — records on or after |
| `to` | string | No | ISO 8601 date — records on or before |
| `jobId` | string | No | Filter by jobId |
| `vendorId` | string | No | Filter by vendorId |
| `limit` | integer | No | Page size (default: 20, max: 100) |
| `nextToken` | string | No | Pagination cursor |

**Response — 200 OK**
```json
{
  "items": [
    {
      "logId": "log-uuid-here",
      "jobId": "a1b2c3d4-...",
      "vendorId": "v1v1v1v1-...",
      "action": "AI_RECOMMENDATION",
      "confidence": "High",
      "modelVersion": "1.2.0",
      "piiMasked": true,
      "timestamp": "2025-07-28T10:00:05Z"
    }
  ],
  "count": 1,
  "nextToken": null
}
```

---

### GET /audit-logs/{logId}

Returns full detail for a single audit log record.

**Path Parameters:** `logId` (UUID v4)

**Response — 200 OK**
```json
{
  "logId": "log-uuid-here",
  "jobId": "a1b2c3d4-...",
  "vendorId": "v1v1v1v1-...",
  "action": "AI_RECOMMENDATION",
  "input": { "scoreFactors": [ "..." ], "jobDetails": { "..." } },
  "output": { "rankedList": [ "..." ], "confidence": "High" },
  "overrideReason": null,
  "modelVersion": "1.2.0",
  "piiMasked": true,
  "aiUnavailable": false,
  "timestamp": "2025-07-28T10:00:05Z"
}
```

**Response — 404 Not Found** when `logId` does not exist.

---

### GET /dashboard/metrics

Returns summary metrics for the Admin Dashboard.

**Response — 200 OK**
```json
{
  "date": "2025-07-28",
  "totalJobsToday": 42,
  "totalRecommendationsToday": 38,
  "totalOverridesToday": 5,
  "aiServiceStatus": "Active",
  "fallbackActivationsToday": 0,
  "lowConfidenceRateToday": 0.08
}
```

| Field | Description |
|---|---|
| `aiServiceStatus` | `"Active"` or `"Fallback"` |
| `fallbackActivationsToday` | Count of fallback scorer activations today |
| `lowConfidenceRateToday` | Fraction of today's recommendations with Low confidence |


---

## DynamoDB Table Design

All tables use on-demand billing mode. Partition keys and sort keys are strings unless noted.

---

### Jobs Table

**Table name:** `ai-vrs-jobs`

| Key | Attribute | Type |
|---|---|---|
| Partition Key | `jobId` | String (UUID v4) |
| Sort Key | — (none) | — |

**GSIs:**

| GSI Name | Partition Key | Sort Key | Purpose |
|---|---|---|---|
| `status-createdAt-index` | `status` | `createdAt` | Filter jobs by status, sorted by creation time |
| `createdAt-index` | `createdAt` (date prefix `YYYY-MM-DD`) | `jobId` | Date-range queries for dashboard metrics |

**Key Access Patterns:**
- Get job by `jobId` (primary key lookup)
- List jobs by `status` ordered by `createdAt` (GSI: `status-createdAt-index`)
- List all jobs in a date range (GSI: `createdAt-index`)

**Example Item:**
```json
{
  "jobId":        "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "type":         "plumbing",
  "location":     "Austin, TX",
  "urgency":      "High",
  "slaDeadline":  "2025-08-01T14:00:00Z",
  "description":  "Burst pipe in commercial kitchen.",
  "status":       "Recommended",
  "createdAt":    "2025-07-28T10:00:00Z",
  "schemaVersion":"1.0"
}
```

---

### Vendors Table

**Table name:** `ai-vrs-vendors`

| Key | Attribute | Type |
|---|---|---|
| Partition Key | `vendorId` | String (UUID v4) |
| Sort Key | — (none) | — |

**GSIs:**

| GSI Name | Partition Key | Sort Key | Purpose |
|---|---|---|---|
| `availability-index` | `availability` | `vendorId` | Fetch all available/busy vendors efficiently |

**Key Access Patterns:**
- Get vendor by `vendorId` (primary key lookup)
- Scan all vendors for scoring (full table scan — acceptable given ~1,000 vendors)
- Filter vendors by `availability` (GSI: `availability-index`)

**Example Item:**
```json
{
  "vendorId":        "v1v1v1v1-1111-2222-3333-444444444444",
  "name":            "AcePlumbing Co.",
  "completionRate":  0.94,
  "availability":    "available",
  "reworkRate":      0.06,
  "location":        "Austin, TX",
  "specializations": ["plumbing", "water-heater"],
  "avgResponseTime": 2.5,
  "slaBreachCount":  1,
  "activeJobs":      3
}
```

---

### Recommendations Table

**Table name:** `ai-vrs-recommendations`

| Key | Attribute | Type |
|---|---|---|
| Partition Key | `jobId` | String (UUID v4) |
| Sort Key | `rank` | Number (1–5) |

**GSIs:**

| GSI Name | Partition Key | Sort Key | Purpose |
|---|---|---|---|
| `vendorId-timestamp-index` | `vendorId` | `timestamp` | Look up all recommendations for a vendor over time |
| `modelVersion-index` | `modelVersion` | `timestamp` | Query recommendations by model version for drift analysis |

**Key Access Patterns:**
- Get all recommendations for a job (partition key: `jobId`) — returns up to 5 items
- Get rank-1 recommendation for a job (`jobId` + `rank=1`)
- Look up recommendation history for a vendor (GSI: `vendorId-timestamp-index`)

**Example Item:**
```json
{
  "jobId":         "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "rank":          1,
  "vendorId":      "v1v1v1v1-1111-2222-3333-444444444444",
  "vendorName":    "AcePlumbing Co.",
  "totalScore":    0.932,
  "confidence":    "High",
  "rationale":     "Ranked #1 due to high completion rate and full availability...",
  "isAIGenerated": true,
  "modelVersion":  "1.2.0",
  "scoreFactors": {
    "completionScore": 0.94, "availabilityScore": 1.0,
    "reworkScore": 0.88,     "locationScore": 1.0,
    "specializationScore": 1.0, "responseTimeScore": 0.75,
    "slaBreachScore": 0.90,  "activeJobsScore": 0.85
  },
  "timestamp":     "2025-07-28T10:00:05Z"
}
```

---

### AuditLog Table

**Table name:** `ai-vrs-audit-log`

| Key | Attribute | Type |
|---|---|---|
| Partition Key | `logId` | String (UUID v4) |
| Sort Key | — (none) | — |

**GSIs:**

| GSI Name | Partition Key | Sort Key | Purpose |
|---|---|---|---|
| `jobId-timestamp-index` | `jobId` | `timestamp` | Fetch all audit records for a job |
| `action-timestamp-index` | `action` | `timestamp` | Filter audit log by action type with date range |
| `vendorId-timestamp-index` | `vendorId` | `timestamp` | Fetch all audit records for a vendor |

**Key Access Patterns:**
- Get audit record by `logId` (primary key lookup)
- Get all audit records for a job (GSI: `jobId-timestamp-index`)
- Filter by action type in a date range (GSI: `action-timestamp-index`)
- Search by `vendorId` (GSI: `vendorId-timestamp-index`)

**Example Item:**
```json
{
  "logId":        "log-uuid-0001-0002-0003-000400050006",
  "jobId":        "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "vendorId":     "v1v1v1v1-1111-2222-3333-444444444444",
  "action":       "AI_RECOMMENDATION",
  "input":        { "scoreFactors": ["[REDACTED or masked dict]"] },
  "output":       { "rankedList": ["[masked]"], "confidence": "High" },
  "overrideReason": null,
  "modelVersion": "1.2.0",
  "piiMasked":    true,
  "aiUnavailable":false,
  "timestamp":    "2025-07-28T10:00:05Z"
}
```

---

### Users Table

**Table name:** `ai-vrs-users`

| Key | Attribute | Type |
|---|---|---|
| Partition Key | `userId` | String (Cognito sub UUID) |
| Sort Key | — (none) | — |

**GSIs:**

| GSI Name | Partition Key | Sort Key | Purpose |
|---|---|---|---|
| `email-index` | `email` | — | Look up user by email address |

**Key Access Patterns:**
- Get user by `userId` (primary key lookup — used by auth handler)
- Look up user by `email` (GSI: `email-index` — used for duplicate registration check)

**Example Item:**
```json
{
  "userId":    "cognito-sub-uuid-here",
  "email":     "admin@retailfixit.com",
  "createdAt": "2025-07-01T09:00:00Z"
}
```


---

## Terraform Infrastructure Design

All infrastructure is defined in `infrastructure/terraform/`. The AWS provider version is `~> 5.0` and Terraform version is `~> 1.5`.

---

### `main.tf`

Defines the Terraform backend, required providers, and top-level provider configuration.

```hcl
terraform {
  required_version = "~> 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket = "retailfixit-terraform-state"
    key    = "ai-vrs/terraform.tfstate"
    region = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = { Project = "ai-vrs", Environment = var.environment } }
}
```

---

### `lambda.tf`

Defines the Lambda function, its IAM execution role, inline policy, and SQS event source mapping.

**Resources:**
- `aws_lambda_function.ai_vrs` — single Lambda function, Python 3.11 runtime, `handler.lambda_handler` entry point, reads zip from S3 lambda-zip bucket, reserved concurrency set via `var.lambda_reserved_concurrency`
- `aws_iam_role.lambda_exec` — assume-role policy for `lambda.amazonaws.com`
- `aws_iam_role_policy.lambda_policy` — inline policy granting least-privilege access to: DynamoDB (all 5 AI-VRS tables), S3 (all 3 AI-VRS buckets), Secrets Manager (Gemini API key secret ARN), EventBridge (AI-VRS rules), SQS (vendor-scoring-queue consume), CloudWatch Logs (write)
- `aws_lambda_event_source_mapping.sqs_trigger` — maps `vendor-scoring-queue` to the Lambda function with batch size 1

**Environment variables on the Lambda function:**
- `JOBS_TABLE`, `VENDORS_TABLE`, `RECOMMENDATIONS_TABLE`, `AUDIT_LOG_TABLE`, `USERS_TABLE`
- `LAMBDA_ZIP_BUCKET`, `LOGS_BUCKET`, `OVERRIDE_FEEDBACK_BUCKET`
- `GEMINI_SECRET_NAME` (value: `"ai-vrs/gemini-api-key"`)
- `EVENTBRIDGE_BUS_NAME`, `SQS_QUEUE_URL`
- `ENVIRONMENT` (e.g., `"production"`)

---

### `dynamodb.tf`

Defines all 5 DynamoDB tables with on-demand billing, keys, and GSIs as described in the DynamoDB Table Design section.

**Resources:**
- `aws_dynamodb_table.jobs` — partition key `jobId`; GSIs: `status-createdAt-index`, `createdAt-index`
- `aws_dynamodb_table.vendors` — partition key `vendorId`; GSI: `availability-index`
- `aws_dynamodb_table.recommendations` — partition key `jobId`, sort key `rank` (Number); GSIs: `vendorId-timestamp-index`, `modelVersion-index`
- `aws_dynamodb_table.audit_log` — partition key `logId`; GSIs: `jobId-timestamp-index`, `action-timestamp-index`, `vendorId-timestamp-index`
- `aws_dynamodb_table.users` — partition key `userId`; GSI: `email-index`

All tables set `billing_mode = "PAY_PER_REQUEST"` and `point_in_time_recovery { enabled = true }`.

---

### `cognito.tf`

Defines the Cognito User Pool and App Client for Admin authentication.

**Resources:**
- `aws_cognito_user_pool.admin_pool` — self-registration enabled, email verification required, password policy: minimum 8 characters, requires uppercase, lowercase, numbers, and symbols; Lambda trigger: `post_confirmation = aws_lambda_function.ai_vrs.arn`
- `aws_cognito_user_pool_client.admin_client` — no client secret (SPA client), explicit auth flows: `ALLOW_USER_PASSWORD_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH`, `ALLOW_USER_SRP_AUTH`; access token validity: 1 hour; refresh token validity: 30 days

---

### `s3.tf`

Defines the 3 S3 buckets with encryption and lifecycle policies.

**Resources:**
- `aws_s3_bucket.lambda_zip` — stores `lambda.zip` and `model-version.txt`; SSE-S3 encryption; versioning enabled
- `aws_s3_bucket.logs` — stores audit log exports; SSE-S3 encryption; lifecycle rule: transition to S3 Glacier after 90 days, expire after 365 days; public access block: all public access denied
- `aws_s3_bucket.override_feedback` — stores override feedback JSON; SSE-S3 encryption; lifecycle rule: expire after 730 days (2 years for retraining data); public access block: all public access denied

All buckets have `aws_s3_bucket_public_access_block` resources with all four block settings set to `true`.

---

### `api_gateway.tf`

Defines the REST API, all resources and methods, Cognito authorizer, CORS, deployment, and stage.

**Resources:**
- `aws_api_gateway_rest_api.ai_vrs` — REST API with endpoint type REGIONAL
- `aws_api_gateway_authorizer.cognito` — type `COGNITO_USER_POOLS`, references `aws_cognito_user_pool.admin_pool`
- Resource tree: `/jobs`, `/jobs/{jobId}`, `/recommendations/{jobId}`, `/recommendations/{jobId}/accept`, `/override`, `/audit-logs`, `/audit-logs/{logId}`, `/dashboard/metrics`
- For each resource: `aws_api_gateway_method` (with `authorization = "COGNITO_USER_POOLS"`), `aws_api_gateway_integration` (Lambda proxy), `aws_api_gateway_method_response`, `aws_api_gateway_integration_response`
- CORS: `OPTIONS` method on each resource with `mock` integration returning `Access-Control-Allow-Origin: var.allowed_cors_origin`, `Access-Control-Allow-Headers`, `Access-Control-Allow-Methods`
- `aws_api_gateway_deployment.prod` — triggers redeployment on resource/method changes
- `aws_api_gateway_stage.prod` — stage name from `var.environment`; CloudWatch logging enabled; access log format JSON

---

### `eventbridge.tf`

Defines EventBridge rules for the 4 AI-VRS events.

**Resources:**
- `aws_cloudwatch_event_rule.job_created` — event pattern matching `source = "retailfixit.jobs"`, `detail-type = "JobCreated"`; target: SQS vendor-scoring-queue
- `aws_cloudwatch_event_rule.recommendation_generated` — event pattern matching `detail-type = "VendorRecommendationGenerated"`; target: CloudWatch log group (for audit trail)
- `aws_cloudwatch_event_rule.override_recorded` — event pattern matching `detail-type = "VendorOverrideRecorded"`; target: CloudWatch log group
- `aws_cloudwatch_event_rule.no_eligible_vendors` — event pattern matching `detail-type = "NoEligibleVendors"`; target: CloudWatch log group + SNS alert topic
- `aws_cloudwatch_event_target` resources for each rule
- `aws_sqs_queue_policy` granting EventBridge permission to send to the SQS queue

---

### `sqs.tf`

Defines the main SQS queue and Dead Letter Queue with redrive policy.

**Resources:**
- `aws_sqs_queue.dlq` — `ai-vrs-vendor-scoring-dlq`; message retention: 14 days
- `aws_sqs_queue.main` — `ai-vrs-vendor-scoring-queue`; visibility timeout: 30 seconds (must exceed Lambda timeout); message retention: 4 days; redrive policy: `maxReceiveCount = 3`, `deadLetterTargetArn = aws_sqs_queue.dlq.arn`

---

### `secrets.tf`

References the existing Secrets Manager secret containing the Gemini API key. The secret is created out-of-band (not managed by Terraform) to avoid storing the key value in Terraform state.

```hcl
data "aws_secretsmanager_secret" "gemini_api_key" {
  name = "ai-vrs/gemini-api-key"
}
```

The Lambda IAM policy grants `secretsmanager:GetSecretValue` on `data.aws_secretsmanager_secret.gemini_api_key.arn`.

---

### `cloudwatch.tf`

Defines CloudWatch log groups, metric alarms, and metric filters.

**Resources:**
- `aws_cloudwatch_log_group.lambda` — `/aws/lambda/ai-vrs`; retention: 90 days
- `aws_cloudwatch_log_group.audit_exports` — `/ai-vrs/audit-log-exports`; retention: 365 days
- `aws_cloudwatch_metric_alarm.high_low_confidence_rate` — alarm name `HighLowConfidenceRate`; triggers when `RecommendationConfidenceDistribution` (Low fraction) > 0.30 over a 24-hour period; alarm action: SNS topic
- `aws_cloudwatch_metric_alarm.high_override_rate` — alarm name `HighOverrideRate`; triggers when override rate > 0.40 over a 7-day window; alarm action: SNS topic
- `aws_cloudwatch_metric_alarm.fallback_activations` — alarm name `FallbackScorerActivations`; triggers when `FallbackScorerActivations` count > 10 in a 1-hour period; alarm action: SNS topic
- `aws_cloudwatch_log_metric_filter` resources for extracting `VendorProfileDataQualityErrors` and `FallbackScorerActivations` from Lambda log output

---

### `variables.tf`

Defines all input variables with descriptions and defaults.

| Variable | Type | Default | Description |
|---|---|---|---|
| `aws_region` | string | `"us-east-1"` | AWS region for all resources |
| `environment` | string | `"production"` | Deployment environment name |
| `lambda_zip_key` | string | `"lambda.zip"` | S3 key for the Lambda deployment package |
| `lambda_reserved_concurrency` | number | `10` | Reserved concurrency limit for the Lambda function |
| `lambda_timeout` | number | `25` | Lambda function timeout in seconds |
| `lambda_memory_size` | number | `512` | Lambda memory allocation in MB |
| `allowed_cors_origin` | string | — | Explicit allowed origin for API Gateway CORS (no default — must be set) |
| `gemini_secret_name` | string | `"ai-vrs/gemini-api-key"` | Secrets Manager secret name for Gemini API key |
| `sqs_visibility_timeout` | number | `30` | SQS visibility timeout in seconds |
| `sqs_max_receive_count` | number | `3` | Max SQS receive count before routing to DLQ |
| `cognito_access_token_validity` | number | `1` | Cognito access token validity in hours |
| `cognito_refresh_token_validity` | number | `30` | Cognito refresh token validity in days |

---

### `outputs.tf`

Exposes key resource identifiers after `terraform apply`.

| Output | Description |
|---|---|
| `api_gateway_url` | API Gateway invoke URL (e.g., `https://{id}.execute-api.us-east-1.amazonaws.com/production`) |
| `cognito_user_pool_id` | Cognito User Pool ID |
| `cognito_client_id` | Cognito App Client ID |
| `sqs_queue_url` | Vendor scoring SQS queue URL |
| `dlq_url` | Dead Letter Queue URL |


---

## Frontend Design

### Technology Stack

| Concern | Choice | Reason |
|---|---|---|
| Framework | React 18 | Component model, hooks, wide ecosystem |
| Build tool | Vite | Fast HMR, ES module native |
| Routing | React Router v6 | Declarative nested routes |
| HTTP client | Axios | Interceptors for JWT injection |
| Auth | `amazon-cognito-identity-js` | Direct Cognito SDK, no Amplify overhead |
| Styling | CSS Modules + theme.js tokens | Scoped styles, no runtime CSS-in-JS cost |
| State | React Context + `useState`/`useEffect` | No Redux needed at this scale |

---

### Route Structure

```
/                       → redirect to /dashboard (if authenticated) or /auth
/auth                   → LoginPage (Login + Register tabs)
/dashboard              → Dashboard (protected)
/jobs                   → JobsPage (protected)
/jobs/:jobId            → JobDetail (protected)
/recommendations/:jobId → RecommendationsPage (protected)
/override/:jobId        → OverridePage (protected)
/audit-logs             → AuditLogPage (protected)
```

All routes except `/auth` are wrapped in `ProtectedRoute`, which checks for a valid Cognito session and redirects to `/auth` if none exists.

---

### Component Tree

```
App
├── AuthProvider (Context: user, tokens, login, logout, register)
│
├── /auth → LoginPage
│   ├── Tab: "Login"  → LoginForm
│   └── Tab: "Register" → RegisterForm
│
└── AppLayout (Header + Sidebar + Footer wrapper)
    ├── Header
    │   ├── RetailFixIt logo
    │   ├── Current page title
    │   └── Logout button
    ├── Sidebar
    │   └── NavLinks: Dashboard | Jobs | Recommendations | Override | Audit Log
    ├── FallbackBanner (rendered globally when aiServiceStatus === "Fallback")
    │
    ├── /dashboard → Dashboard
    │   ├── MetricCard (Jobs Today)
    │   ├── MetricCard (Recommendations Today)
    │   ├── MetricCard (Overrides Today)
    │   └── AIStatusBadge (Active / Fallback)
    │
    ├── /jobs → JobsPage
    │   ├── JobFilterBar (status dropdown, date range pickers)
    │   ├── LoadingSpinner (while loading)
    │   ├── ErrorBanner (on API error)
    │   └── JobList → JobRow[] (click → /jobs/:jobId)
    │
    ├── /jobs/:jobId → JobDetail
    │   ├── JobInfoPanel (all job fields)
    │   └── Link → /recommendations/:jobId
    │
    ├── /recommendations/:jobId → RecommendationsPage
    │   ├── FallbackBanner (if isFallback === true)
    │   ├── LoadingSpinner (while loading)
    │   ├── VendorList
    │   │   └── VendorCard[] (rank 1–5)
    │   │       ├── VendorName + Rank badge
    │   │       ├── TotalScore bar
    │   │       ├── ScoreFactors breakdown (8 dimensions)
    │   │       ├── RationaleBox (AI or rule-based text)
    │   │       ├── ConfidenceBadge (green/amber/red)
    │   │       └── Buttons: "Accept" | "Override"
    │   └── CriticalJobWarning (if urgency=Critical or SLA < 2h)
    │
    ├── /override/:jobId → OverridePage
    │   ├── CurrentRecommendationSummary
    │   └── OverridePanel
    │       ├── VendorSelector (dropdown of all eligible vendors)
    │       ├── SelectedVendorProfile (shown after selection)
    │       ├── ReasonTextArea (10–500 chars, character counter)
    │       ├── ErrorBanner (on submit failure)
    │       └── SubmitButton
    │
    ├── /audit-logs → AuditLogPage
    │   ├── AuditFilterBar (action type, date range, jobId, vendorId search)
    │   ├── LoadingSpinner (while loading)
    │   ├── AuditLogList → AuditLogRow[]
    │   └── AuditLogDetailPanel (shown on row click)
    │
    └── Footer
        └── Version | Docs link | RetailFixIt © 2025
```

---

### Auth Flow (Frontend)

```
User visits /dashboard (unauthenticated)
        ↓
ProtectedRoute detects no session → redirect to /auth
        ↓
User clicks "Register" tab → fills email + password + confirm-password
        ↓
RegisterForm calls Cognito SDK: signUp(email, password)
        ↓
Cognito sends verification email
        ↓
User confirms email via link
        ↓
User clicks "Login" tab → fills email + password
        ↓
LoginForm calls Cognito SDK: signIn(email, password)
        ↓
AuthProvider stores JWT access token + refresh token in memory
        ↓
Redirect to /dashboard
        ↓
Axios interceptor injects "Authorization: Bearer <token>" on every API call
        ↓
On token expiry: Cognito SDK auto-refreshes using refresh token
        ↓
Logout: Cognito SDK signOut() → clear tokens → redirect to /auth
```

---

### `services/api.js` — API Client

All API calls go through a single Axios instance configured with:
- `baseURL`: API Gateway invoke URL (from environment variable `VITE_API_URL`)
- Request interceptor: injects `Authorization: Bearer <access_token>` from `AuthProvider`
- Response interceptor: on 401, attempts token refresh; on second 401, redirects to `/auth`

```javascript
// Key functions exported from api.js
export const createJob = (jobData) => api.post('/jobs', jobData)
export const getJobs = (params) => api.get('/jobs', { params })
export const getJob = (jobId) => api.get(`/jobs/${jobId}`)
export const getRecommendations = (jobId) => api.get(`/recommendations/${jobId}`)
export const acceptRecommendation = (jobId) => api.post(`/recommendations/${jobId}/accept`)
export const submitOverride = (data) => api.post('/override', data)
export const getAuditLogs = (params) => api.get('/audit-logs', { params })
export const getAuditLog = (logId) => api.get(`/audit-logs/${logId}`)
export const getDashboardMetrics = () => api.get('/dashboard/metrics')
```

---

### `hooks/useAuth.js`

Wraps `AuthProvider` context. Exposes: `user`, `isAuthenticated`, `login(email, password)`, `register(email, password)`, `logout()`, `getAccessToken()`.

### `hooks/useRecommendations.js`

Fetches recommendations for a given `jobId`. Returns: `{ recommendations, isFallback, isLoading, error, refetch }`.

---

## S3 File Structure

```
ai-vrs-lambda-zip/
├── lambda.zip                  # Lambda deployment package
└── model-version.txt           # Current model version (e.g., "1.2.0")

ai-vrs-logs/
└── audit-logs/
    └── YYYY/MM/DD/
        └── {logId}.json        # Full unmasked audit log records (SSE-S3 encrypted)

ai-vrs-override-feedback/
└── YYYY/MM/DD/
    └── {jobId}-{timestamp}.json  # Override feedback records for retraining
```

Override feedback record schema (stored in S3):
```json
{
  "jobId": "...",
  "originalRankedList": [ { "rank": 1, "vendorId": "...", "scoreFactors": {...} } ],
  "selectedVendorId": "...",
  "overrideReason": "...",
  "adminUserId": "...",
  "timestamp": "2025-07-28T10:02:00Z",
  "modelVersion": "1.2.0"
}
```

---

## Correctness Properties

These properties define the formal correctness criteria for the scoring engine and are the basis for property-based tests.

### Property 1: Score Bounds
For any valid `VendorProfile` and `JobEvent`, the `totalScore` produced by the scoring engine must be in the range [0.0, 1.0].

```
∀ vendor ∈ VendorProfile, job ∈ JobEvent:
  score = compute_score(vendor, job)
  0.0 ≤ score.totalScore ≤ 1.0
```

### Property 2: Ranking Consistency
The ranked list must be sorted in descending order of `totalScore`. No vendor ranked at position `i` may have a lower `totalScore` than a vendor at position `i+1`.

```
∀ ranked_list where len(ranked_list) >= 2:
  ∀ i in range(len(ranked_list) - 1):
    ranked_list[i].totalScore >= ranked_list[i+1].totalScore
```

### Property 3: Unavailable Vendor Exclusion
No vendor with `availability == "unavailable"` may appear in the ranked output.

```
∀ vendor in ranked_output:
  vendor.availability != "unavailable"
```

### Property 4: Ranked List Size Bound
The ranked list must contain at most 5 vendors and at least 0 (when no eligible vendors exist).

```
0 ≤ len(ranked_output) ≤ 5
```

### Property 5: Model Version Propagation
Every `ScoreFactors` record in the ranked output must carry the same `modelVersion` string as the value read from S3 at Lambda cold start.

```
∀ sf in ranked_output:
  sf.modelVersion == get_model_version()
```

### Property 6: Tie-Breaking Determinism
When two vendors share an identical `totalScore` (rounded to 6 decimal places), the vendor with the lower `activeJobs` count must rank higher. If `activeJobs` is also equal, the vendor with the lexicographically lower `vendorId` must rank higher.

```
∀ (v_i, v_j) where round(v_i.totalScore, 6) == round(v_j.totalScore, 6):
  if v_i.activeJobs < v_j.activeJobs: rank(v_i) < rank(v_j)
  elif v_i.activeJobs == v_j.activeJobs: rank(v_i) < rank(v_j) iff v_i.vendorId < v_j.vendorId
```

### Property 7: Fallback Structural Equivalence
The `ScoreFactors` record produced by `fallback_scorer` must be structurally identical to one produced by the normal scoring path — same field names, same types, same `modelVersion`.

```
∀ sf_fallback = fallback_scorer.score(vendor, job):
  fields(sf_fallback) == fields(ScoreFactors)
  sf_fallback.modelVersion == get_model_version()
```

### Property 8: Confidence Level Validity
Every `Recommendation` record must have a `confidence` value that is exactly one of: `"High"`, `"Medium"`, `"Low"`.

```
∀ rec in recommendations:
  rec.confidence ∈ {"High", "Medium", "Low"}
```

### Property 9: Override Reason Length
The `Override_Handler` must reject any override request where `overrideReason` has fewer than 10 or more than 500 characters.

```
∀ override_request:
  if len(override_request.overrideReason) < 10 OR len(override_request.overrideReason) > 500:
    result == ValidationError
```

### Property 10: Audit Log PII Masking
Every `AuditLog` record written to DynamoDB must have `piiMasked == True`. No field in the `input` or `output` dicts of a DynamoDB record may contain a raw email address or phone number pattern.

```
∀ audit_record written to DynamoDB:
  audit_record.piiMasked == True
  ∀ value in flatten(audit_record.input):
    not matches_email_pattern(value) AND not matches_phone_pattern(value)
```

---

## Key Tradeoffs and Assumptions

### Tradeoffs

**Single Lambda vs. multiple Lambdas**
Chose a single Lambda with internal routing to minimize cost and cold start surface area. Tradeoff: the function package is larger and all handlers share the same memory/timeout configuration. Mitigated by keeping handlers thin and delegating to service modules.

**DynamoDB full table scan for vendor scoring**
With ~1,000 vendors, a full scan of the Vendors table is acceptable (< 1MB, < 100ms at DynamoDB speeds). If the vendor count grows beyond ~10,000, this should be replaced with a GSI-based filtered query or a pre-computed eligible vendor list.

**Gemini API for rationale (external dependency)**
Using an external AI API introduces latency and availability risk. Mitigated by the 8-second timeout, retry logic, and the Fallback_Scorer. The Gemini key is stored in Secrets Manager and never in code or environment variables.

**Rule-based location matching (exact string + region heuristic)**
Location proximity uses exact string match and a simple region heuristic rather than geospatial distance. This is a deliberate simplification — production would use a geocoding API or pre-computed distance matrix.

**No real-time model retraining**
Override feedback is stored in S3 in a retraining-ready schema but no automated retraining pipeline is implemented. This is intentional for the assessment scope. The data structure supports future integration with a batch training job.

**Terraform state in S3**
Terraform state is stored in an S3 bucket (`retailfixit-terraform-state`). This bucket must be created manually before the first `terraform init`. The bucket is not managed by this Terraform configuration to avoid a bootstrapping circular dependency.

### Assumptions

1. The Gemini API key is manually stored in AWS Secrets Manager under the name `ai-vrs/gemini-api-key` before deployment.
2. The Terraform state S3 bucket (`retailfixit-terraform-state`) exists before running `terraform init`.
3. AWS credentials with sufficient permissions are configured in the deployment environment (`aws configure` or IAM role).
4. Vendor location strings use a consistent format (e.g., "City, State") to enable the exact-match location scoring heuristic.
5. The `model-version.txt` file is uploaded to the Lambda zip S3 bucket before the first Lambda invocation.
6. The Admin UI is served from a known origin (configured in `var.allowed_cors_origin`) — wildcard CORS is not permitted.
7. All DynamoDB table names use the `ai-vrs-` prefix and are unique within the AWS account and region.
8. The system is deployed to a single AWS region (`us-east-1` by default). Multi-region is out of scope.

---

## Security Design Summary

| Concern | Mechanism |
|---|---|
| API authentication | Cognito JWT — all API Gateway routes require valid Bearer token |
| API authorization | Cognito Authorizer on API Gateway — 401 on missing/expired token |
| Gemini API key | AWS Secrets Manager — fetched at runtime, never in code or env vars |
| Lambda permissions | Least-privilege IAM role — scoped to specific table ARNs and bucket ARNs |
| Audit log encryption | S3 SSE-S3 on logs and override feedback buckets |
| PII in logs | `pii_masker.py` redacts email/phone patterns before DynamoDB writes |
| CORS | Explicit allowed origin in API Gateway — no wildcard |
| S3 public access | All buckets have `aws_s3_bucket_public_access_block` with all four settings `true` |
| Terraform state | Stored in encrypted S3 bucket with versioning enabled |
| Password policy | Cognito: min 8 chars, uppercase, lowercase, digit, special character |


---

## Seed Data Script Design

### Purpose

The `scripts/seed_data.py` script populates DynamoDB with realistic test data to enable system demonstration and testing without requiring real production data.

### Script Location

`scripts/seed_data.py`

### Dependencies

```python
# requirements: boto3, faker
import boto3
from faker import Faker
import uuid
from datetime import datetime, timedelta
import random
```

### Execution

```bash
# From project root
python scripts/seed_data.py --region us-east-1 --environment production
```

### Command-Line Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--region` | No | `us-east-1` | AWS region |
| `--environment` | No | `production` | Environment name (used to construct table names) |
| `--vendors` | No | `10` | Number of vendor profiles to create |
| `--jobs` | No | `5` | Number of job records to create |
| `--dry-run` | No | `False` | Print records without writing to DynamoDB |

### Idempotency Strategy

The script checks for existing records by primary key before inserting. If a record with the same `vendorId` or `jobId` already exists, the script skips that record and logs a message. This allows the script to be run multiple times safely.

```python
def seed_vendor(table, vendor_data):
    try:
        table.put_item(
            Item=vendor_data,
            ConditionExpression='attribute_not_exists(vendorId)'
        )
        print(f"✓ Created vendor: {vendor_data['name']}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"⊘ Vendor {vendor_data['vendorId']} already exists, skipping")
        else:
            raise
```

### Vendor Profile Generation

Each vendor profile includes:
- `vendorId`: UUID v4
- `name`: Realistic company name (e.g., "AcePlumbing Co.", "QuickFix Electric")
- `completionRate`: Random float [0.70–0.98] (realistic range)
- `availability`: Random choice weighted: 60% "available", 30% "busy", 10% "unavailable"
- `reworkRate`: Random float [0.02–0.15] (inverse of completion rate)
- `location`: Random choice from ["Austin, TX", "Dallas, TX", "Houston, TX", "San Antonio, TX", "Phoenix, AZ", "Tucson, AZ"]
- `specializations`: Random subset of ["plumbing", "electrical", "hvac", "carpentry", "roofing", "painting"]
- `avgResponseTime`: Random float [1.0–8.0] hours
- `slaBreachCount`: Random int [0–5]
- `activeJobs`: Random int [0–10]

### Job Event Generation

Each job record includes:
- `jobId`: UUID v4
- `type`: Random choice from vendor specializations
- `location`: Random choice from vendor locations
- `urgency`: Random choice weighted: 40% "Low", 30% "Medium", 20% "High", 10% "Critical"
- `slaDeadline`: Current time + random offset [2 hours–7 days]
- `description`: Template-based realistic description (e.g., "Burst pipe in commercial kitchen requiring immediate repair")
- `status`: Always "Pending" for seed data
- `createdAt`: Current timestamp
- `schemaVersion`: "1.0"

### Output

```
Seeding AI-VRS DynamoDB tables in us-east-1 (production)...

Vendors Table: ai-vrs-vendors
✓ Created vendor: AcePlumbing Co. (vendorId: v1v1v1v1-...)
✓ Created vendor: QuickFix Electric (vendorId: v2v2v2v2-...)
✓ Created vendor: HVAC Masters (vendorId: v3v3v3v3-...)
...
✓ 10 vendors created

Jobs Table: ai-vrs-jobs
✓ Created job: plumbing job in Austin, TX (jobId: a1b2c3d4-...)
✓ Created job: electrical job in Dallas, TX (jobId: b2c3d4e5-...)
...
✓ 5 jobs created

Seed data complete. Run the system to generate recommendations for these jobs.
```

---

## Deployment Script Design

### Purpose

The `scripts/deploy.sh` script packages the Lambda function and deploys all AWS infrastructure in a single command using Terraform.

### Script Location

`scripts/deploy.sh`

### Prerequisites

1. AWS CLI configured (`aws configure` completed)
2. Terraform installed (`terraform --version` shows ~> 1.5)
3. Python 3.11 installed
4. Gemini API key stored in AWS Secrets Manager under `ai-vrs/gemini-api-key`
5. Terraform state S3 bucket (`retailfixit-terraform-state`) created

### Execution

```bash
# From project root
./scripts/deploy.sh
```

### Script Flow

```bash
#!/bin/bash
set -e  # Exit on any error

echo "========================================="
echo "AI-VRS Deployment Script"
echo "========================================="

# Step 1: Package Lambda function
echo ""
echo "[1/5] Packaging Lambda function..."
cd backend/lambda
rm -f ../../infra/terraform/lambda.zip
zip -r ../../infra/terraform/lambda.zip . -x "*.pyc" -x "__pycache__/*" -x "*.egg-info/*"
cd ../..
echo "✓ Lambda packaged: infra/terraform/lambda.zip"

# Step 2: Upload Lambda zip to S3
echo ""
echo "[2/5] Uploading Lambda zip to S3..."
aws s3 cp infra/terraform/lambda.zip s3://ai-vrs-lambda-zip/lambda.zip
echo "✓ Lambda zip uploaded to S3"

# Step 3: Upload model version file
echo ""
echo "[3/5] Uploading model version..."
echo "1.0.0" > /tmp/model-version.txt
aws s3 cp /tmp/model-version.txt s3://ai-vrs-lambda-zip/model-version.txt
rm /tmp/model-version.txt
echo "✓ Model version uploaded: 1.0.0"

# Step 4: Terraform init (if not already initialized)
echo ""
echo "[4/5] Initializing Terraform..."
cd infra/terraform
terraform init
echo "✓ Terraform initialized"

# Step 5: Terraform apply
echo ""
echo "[5/5] Deploying infrastructure with Terraform..."
terraform apply -auto-approve
echo "✓ Infrastructure deployed"

# Step 6: Display outputs
echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
terraform output -json > /tmp/tf-outputs.json
API_URL=$(cat /tmp/tf-outputs.json | jq -r '.api_gateway_url.value')
COGNITO_POOL_ID=$(cat /tmp/tf-outputs.json | jq -r '.cognito_user_pool_id.value')
COGNITO_CLIENT_ID=$(cat /tmp/tf-outputs.json | jq -r '.cognito_client_id.value')
rm /tmp/tf-outputs.json

echo ""
echo "API Gateway URL:       $API_URL"
echo "Cognito User Pool ID:  $COGNITO_POOL_ID"
echo "Cognito Client ID:     $COGNITO_CLIENT_ID"
echo ""
echo "Next steps:"
echo "1. Update frontend/.env with VITE_API_URL=$API_URL"
echo "2. Update frontend/.env with VITE_COGNITO_USER_POOL_ID=$COGNITO_POOL_ID"
echo "3. Update frontend/.env with VITE_COGNITO_CLIENT_ID=$COGNITO_CLIENT_ID"
echo "4. Run: python scripts/seed_data.py --region us-east-1"
echo "5. Start frontend: cd frontend && npm run dev"
echo ""
```

### Error Handling

The script uses `set -e` to exit immediately on any command failure. Common failure points:
- Lambda zip creation fails → check Python dependencies in `requirements.txt`
- S3 upload fails → check AWS credentials and bucket existence
- Terraform init fails → check Terraform state bucket exists
- Terraform apply fails → check AWS IAM permissions

### Output

```
=========================================
AI-VRS Deployment Script
=========================================

[1/5] Packaging Lambda function...
  adding: handler.py (deflated 65%)
  adding: router.py (deflated 58%)
  adding: handlers/ (stored 0%)
  ...
✓ Lambda packaged: infra/terraform/lambda.zip

[2/5] Uploading Lambda zip to S3...
upload: infra/terraform/lambda.zip to s3://ai-vrs-lambda-zip/lambda.zip
✓ Lambda zip uploaded to S3

[3/5] Uploading model version...
upload: /tmp/model-version.txt to s3://ai-vrs-lambda-zip/model-version.txt
✓ Model version uploaded: 1.0.0

[4/5] Initializing Terraform...
Terraform has been successfully initialized!
✓ Terraform initialized

[5/5] Deploying infrastructure with Terraform...
aws_dynamodb_table.jobs: Creating...
aws_dynamodb_table.vendors: Creating...
...
Apply complete! Resources: 42 added, 0 changed, 0 destroyed.
✓ Infrastructure deployed

=========================================
Deployment Complete!
=========================================

API Gateway URL:       https://abc123xyz.execute-api.us-east-1.amazonaws.com/production
Cognito User Pool ID:  us-east-1_ABC123XYZ
Cognito Client ID:     1a2b3c4d5e6f7g8h9i0j

Next steps:
1. Update frontend/.env with VITE_API_URL=https://abc123xyz.execute-api.us-east-1.amazonaws.com/production
2. Update frontend/.env with VITE_COGNITO_USER_POOL_ID=us-east-1_ABC123XYZ
3. Update frontend/.env with VITE_COGNITO_CLIENT_ID=1a2b3c4d5e6f7g8h9i0j
4. Run: python scripts/seed_data.py --region us-east-1
5. Start frontend: cd frontend && npm run dev
```

---

## Documentation Deliverables Design

### README.md Structure

The `README.md` file at the project root follows this structure:

```markdown
# AI Vendor Recommendation System (AI-VRS)

## System Overview

[2-3 paragraph summary of the system, its purpose, and key capabilities]

## Architecture

[Link to docs/architecture.md for detailed architecture diagram and AWS services]

## AI Approach and Assumptions

### Hybrid Scoring Model
[Description of rule-based scoring + Gemini 2.5 Flash AI rationale]

### Scoring Dimensions
[Table of 8 scoring dimensions with weights]

### Assumptions
[List of 8 key assumptions from design document]

## Explainability

### How Rationale is Generated
[Description of Gemini API prompt design and fallback scorer]

### Confidence Levels
[Explanation of High/Medium/Low confidence calculation]

## Feedback Loop and Model Retraining

### Override Data Structure
[Description of S3 override feedback schema]

### Future Retraining Pipeline
[Conceptual description of how override data would feed a batch training job]

## Deployment

### Prerequisites
[List of 5 prerequisites from deployment script design]

### Quick Start
```bash
./scripts/deploy.sh
python scripts/seed_data.py --region us-east-1
cd frontend && npm install && npm run dev
```

### Manual Deployment Steps
[Detailed step-by-step if deploy.sh cannot be used]

## Development

### Backend (Lambda)
```bash
cd backend/lambda
pip install -r requirements.txt
pytest tests/
```

### Frontend (React)
```bash
cd frontend
npm install
npm run dev
```

### Infrastructure (Terraform)
```bash
cd infra/terraform
terraform plan
terraform apply
```

## Testing

### Unit Tests
[Location and execution of Python unit tests]

### Property-Based Tests
[Reference to 10 correctness properties in design.md]

### Integration Tests
[Description of end-to-end test scenarios]

## Known Limitations and Next Steps

### Limitations
1. Location matching uses exact string match, not geospatial distance
2. No automated model retraining pipeline
3. Gemini API introduces external dependency and latency
4. Single AWS region deployment only
5. DynamoDB full table scan for ~1,000 vendors (acceptable, but not scalable beyond ~10,000)

### Next Steps
1. Implement geospatial distance calculation for location scoring
2. Build automated retraining pipeline using S3 override feedback data
3. Add A/B testing framework to compare AI vs manual dispatch outcomes
4. Implement confidence scoring abstention logic (auto-escalate Low confidence to human review)
5. Add fairness/bias monitoring for vendor selection patterns
6. Multi-region deployment with DynamoDB global tables

## License

[License information]

## Contact

[Contact information for RetailFixIt team]
```

---

### docs/architecture.md Structure

```markdown
# AI-VRS Architecture

## High-Level Diagram

[ASCII or image diagram from design.md]

## AWS Services Used

| Service | Purpose | Key Configuration |
|---|---|---|
| Lambda | All backend logic | Python 3.11, 512MB, 25s timeout, concurrency limit 10 |
| API Gateway | HTTP endpoints | Cognito authorizer, CORS enabled |
| DynamoDB | Data storage | 5 tables, on-demand billing, point-in-time recovery |
| S3 | Artifacts & logs | 3 buckets, SSE-S3 encryption, lifecycle policies |
| Cognito | Authentication | Self-registration, email verification, JWT tokens |
| EventBridge | Event routing | 4 rules for job/recommendation/override/error events |
| SQS | Event queue | Main queue + DLQ, 3 retries before DLQ |
| Secrets Manager | Gemini API key | Fetched at Lambda cold start, cached |
| CloudWatch | Observability | Logs (90d retention), 3 alarms, custom metrics |

## Event Flow Diagrams

[Detailed event flow from design.md]

## Component Interaction

[Component diagram showing Lambda handlers, services, and AWS resources]

## Advisory vs Automated Decisions

| Decision | Mode | Reason |
|---|---|---|
| Vendor scoring | Automated | Low risk, reversible |
| Rationale generation | Automated | Advisory only, human reviews |
| Vendor assignment | Manual (Admin confirms) | High risk, business-critical |
| Override recording | Automated | Audit trail, no business logic |

## Failure Modes and Resilience

[Table from design.md showing Gemini failures, DLQ, fallback scorer]
```

---

### docs/governance_answers.md Structure

```markdown
# AI Governance — Part 3 Written Answers

## 1. AI Authority & Risk

**Question:** Which decisions should never be fully autonomous in this system, and why?

**Answer:**

[2-3 paragraphs covering:
- Final vendor assignment must always require Admin confirmation
- Critical/urgent jobs (SLA < 2h) require explicit acknowledgment
- Low-confidence recommendations should trigger manual review
- Vendor pricing, demographics, customer identity must never be scoring factors
- Rationale: high business impact, potential for bias, regulatory compliance]

## 2. Model Drift & Feedback

**Question:** How would you detect model drift and incorporate human overrides into retraining safely?

**Answer:**

[2-3 paragraphs covering:
- CloudWatch alarms: HighLowConfidenceRate (>30% Low in 24h), HighOverrideRate (>40% in 7d)
- Override data stored in S3 with full context (original ranked list, selected vendor, reason, ScoreFactors)
- Retraining pipeline would: filter overrides by reason category, validate override quality, retrain on accepted overrides only
- Safeguards: shadow mode testing, A/B testing, gradual rollout, human review of model updates]

## 3. Data Quality & Events

**Question:** What event instrumentation is critical to make AI recommendations reliable over time?

**Answer:**

[2-3 paragraphs covering:
- JobCreated_Event with schema version for forward compatibility
- VendorProfile validation with VendorProfileDataQualityErrors metric
- VendorRecommendationGenerated_Event with modelVersion for traceability
- AuditLog records with full input/output for debugging
- CloudWatch metrics: RecommendationConfidenceDistribution, FallbackScorerActivations
- DLQ for failed events with alerting]

## 4. Failure Modes

**Question:** How should the system behave if the AI service is unavailable, slow, or producing low-confidence results?

**Answer:**

[2-3 paragraphs covering:
- Gemini unavailable → Fallback_Scorer activates, FallbackBanner shown in UI, job dispatch continues
- Gemini slow (>8s) → timeout, fallback to rule-based rationale
- Low confidence → warning message in UI, Admin advised to verify manually, no auto-assignment
- Lambda timeout → SQS reprocesses message up to 3 times, then routes to DLQ
- DLQ → CloudWatch alarm triggers, ops team investigates
- No vendor found → NoEligibleVendors_Event published, SNS alert sent]
```

---

### docs/model_versioning.md Structure

```markdown
# Model Versioning Strategy

## Purpose

Track the version of the scoring logic and AI prompt configuration used to produce each recommendation, enabling safe model updates and decision traceability.

## Version Format

Semantic versioning: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes to scoring algorithm or data model
- **MINOR**: New scoring dimensions, weight adjustments, prompt changes
- **PATCH**: Bug fixes, no logic changes

## Storage

The current model version is stored in S3 at `s3://ai-vrs-lambda-zip/model-version.txt` as a plain text file containing a single line (e.g., `1.2.0`).

## Propagation

1. Lambda reads `model-version.txt` from S3 at cold start
2. Version is cached in `utils/model_version.py` module-level variable
3. Every `ScoreFactors`, `Recommendation`, and `AuditLog` record includes the `modelVersion` field

## Update Process

1. Update scoring logic or prompt template in code
2. Increment version number in `model-version.txt`
3. Upload new `model-version.txt` to S3: `aws s3 cp model-version.txt s3://ai-vrs-lambda-zip/`
4. Deploy new Lambda code: `./scripts/deploy.sh`
5. Next Lambda cold start picks up new version automatically

## Querying by Version

DynamoDB GSI `modelVersion-index` on the Recommendations table enables queries like:
- "Show all recommendations produced by model version 1.1.0"
- "Compare override rates between version 1.0.0 and 1.1.0"

## Rollback

If a new model version produces poor results:
1. Revert `model-version.txt` in S3 to previous version
2. Redeploy previous Lambda code
3. Force Lambda cold start by updating environment variable or redeploying
```

---

## Event Payload Examples

### events/job_created.json

```json
{
  "version": "0",
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "detail-type": "JobCreated",
  "source": "retailfixit.jobs",
  "account": "123456789012",
  "time": "2025-07-28T10:00:00Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "type": "plumbing",
    "location": "Austin, TX",
    "urgency": "High",
    "slaDeadline": "2025-08-01T14:00:00Z",
    "description": "Burst pipe in commercial kitchen requiring immediate repair.",
    "createdAt": "2025-07-28T10:00:00Z",
    "schemaVersion": "1.0"
  }
}
```

### events/vendor_recommendation.json

```json
{
  "version": "0",
  "id": "rec-uuid-here",
  "detail-type": "VendorRecommendationGenerated",
  "source": "retailfixit.ai-vrs",
  "account": "123456789012",
  "time": "2025-07-28T10:00:05Z",
  "region": "us-east-1",
  "resources": [],
  "detail": {
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "modelVersion": "1.2.0",
    "isFallback": false,
    "recommendations": [
      {
        "rank": 1,
        "vendorId": "v1v1v1v1-1111-2222-3333-444444444444",
        "totalScore": 0.932,
        "confidence": "High"
      },
      {
        "rank": 2,
        "vendorId": "v2v2v2v2-2222-3333-4444-555555555555",
        "totalScore": 0.875,
        "confidence": "High"
      }
    ],
    "timestamp": "2025-07-28T10:00:05Z"
  }
}
```

### API Request/Response Examples

**POST /jobs — Create Job**

Request:
```json
{
  "type": "plumbing",
  "location": "Austin, TX",
  "urgency": "High",
  "slaDeadline": "2025-08-01T14:00:00Z",
  "description": "Burst pipe in commercial kitchen requiring immediate repair."
}
```

Response (201 Created):
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "type": "plumbing",
  "location": "Austin, TX",
  "urgency": "High",
  "slaDeadline": "2025-08-01T14:00:00Z",
  "description": "Burst pipe in commercial kitchen requiring immediate repair.",
  "status": "Pending",
  "createdAt": "2025-07-28T10:00:00Z",
  "schemaVersion": "1.0"
}
```

**GET /recommendations/{jobId} — Get Recommendations**

Response (200 OK):
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "modelVersion": "1.2.0",
  "isFallback": false,
  "recommendations": [
    {
      "rank": 1,
      "vendorId": "v1v1v1v1-1111-2222-3333-444444444444",
      "vendorName": "AcePlumbing Co.",
      "totalScore": 0.932,
      "confidence": "High",
      "rationale": "This vendor is ranked #1 due to a near-perfect completion rate (0.94) and full availability...",
      "isAIGenerated": true,
      "scoreFactors": {
        "completionScore": 0.94,
        "availabilityScore": 1.0,
        "reworkScore": 0.88,
        "locationScore": 1.0,
        "specializationScore": 1.0,
        "responseTimeScore": 0.75,
        "slaBreachScore": 0.90,
        "activeJobsScore": 0.85
      }
    }
  ],
  "timestamp": "2025-07-28T10:00:05Z"
}
```

**POST /override — Submit Override**

Request:
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "selectedVendorId": "v2v2v2v2-2222-3333-4444-555555555555",
  "overrideReason": "Selected vendor has prior relationship with this client and specific equipment on-site."
}
```

Response (200 OK):
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "selectedVendorId": "v2v2v2v2-2222-3333-4444-555555555555",
  "action": "ADMIN_OVERRIDE",
  "logId": "log-uuid-here",
  "timestamp": "2025-07-28T10:02:00Z"
}
```

**POST /recommendations/{jobId}/accept — Accept Recommendation**

Request: (empty body)

Response (200 OK):
```json
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "action": "AI_RECOMMENDATION_ACCEPTED",
  "logId": "log-uuid-here",
  "timestamp": "2025-07-28T10:01:00Z"
}
```

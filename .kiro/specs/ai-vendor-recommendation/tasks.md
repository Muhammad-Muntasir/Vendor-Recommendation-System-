# Implementation Plan: AI Vendor Recommendation System (AI-VRS)

## Overview

This plan implements the AI-VRS feature end-to-end: a Python Lambda backend with internal routing, a React 18 + Vite frontend, Terraform-managed AWS infrastructure, property-based tests for the scoring engine, and all supporting scripts and documentation. Tasks are ordered so each step builds on the previous, with no orphaned code.

---

## Tasks

- [x] 1. Project scaffold and repository structure
  - Create the top-level directory tree: `backend/lambda/`, `frontend/`, `infra/terraform/`, `events/`, `scripts/`, `docs/`, `tests/`
  - Create all empty `__init__.py` files for Python packages: `backend/lambda/handlers/`, `backend/lambda/services/`, `backend/lambda/models/`, `backend/lambda/utils/`
  - Create `backend/lambda/requirements.txt` with pinned dependencies: `boto3==1.34.0`, `requests==2.31.0`, `hypothesis==6.112.0`, `pytest==8.2.0`, `faker==25.0.0`
  - Create `tests/conftest.py` with shared pytest fixtures: a `sample_vendor_profile()` fixture returning a valid `VendorProfile`, a `sample_job_event()` fixture returning a valid `JobEvent`, and a `mock_dynamodb()` fixture using `unittest.mock.patch` to stub DynamoDB calls
  - Create `.gitignore` excluding Terraform state files (`*.tfstate`, `*.tfstate.backup`, `.terraform/`), `terraform.tfvars`, Lambda zip files (`*.zip`), Python virtual environments (`venv/`, `.venv/`, `__pycache__/`), Node modules (`node_modules/`), `.env` files, and AWS credential files (`~/.aws/credentials`)
  - _Requirements: 21.7_

- [x] 2. Backend — Data models
  - [x] 2.1 Implement `models/job.py` — `JobEvent` dataclass
    - Define `JobEvent` as a Python `@dataclass` with fields: `jobId: str`, `type: str`, `location: str`, `urgency: str`, `slaDeadline: str`, `description: str`, `createdAt: str`, `schemaVersion: str`, `status: str`
    - Add `urgency` validation: must be one of `"Low"`, `"Medium"`, `"High"`, `"Critical"`
    - Add `status` validation: must be one of `"Pending"`, `"Recommended"`, `"Assigned"`, `"Override"`
    - _Requirements: 4.5, 18.1_

  - [x] 2.2 Implement `models/vendor.py` — `VendorProfile` dataclass
    - Define `VendorProfile` as a Python `@dataclass` with fields: `vendorId: str`, `name: str`, `completionRate: float`, `availability: str`, `reworkRate: float`, `location: str`, `specializations: list[str]`, `avgResponseTime: float`, `slaBreachCount: int`, `activeJobs: int`
    - Add `availability` validation: must be one of `"available"`, `"busy"`, `"unavailable"`
    - Add range validation: `completionRate` and `reworkRate` must be in `[0.0, 1.0]`
    - _Requirements: 18.2_

  - [x] 2.3 Implement `models/score.py` — `ScoreFactors` and `Recommendation` dataclasses
    - Define `ScoreFactors` with all 8 dimension score fields (`completionScore`, `availabilityScore`, `reworkScore`, `locationScore`, `specializationScore`, `responseTimeScore`, `slaBreachScore`, `activeJobsScore`), plus `totalScore: float`, `confidence: str`, `modelVersion: str`, `isAIGenerated: bool`, `vendorId: str`, `jobId: str`
    - Define `Recommendation` with fields: `jobId`, `rank`, `vendorId`, `totalScore`, `scoreFactors`, `rationale`, `confidence`, `modelVersion`, `timestamp`, `isAIGenerated`
    - _Requirements: 1.2, 1.4, 2.4, 14.2_

  - [x] 2.4 Implement `models/audit_log.py` — `AuditLog` dataclass
    - Define `AuditLog` with fields: `logId: str`, `jobId: str`, `vendorId: str`, `action: str`, `input: dict`, `output: dict`, `overrideReason: str | None`, `modelVersion: str`, `piiMasked: bool`, `timestamp: str`, `aiUnavailable: bool | None`
    - Add `action` validation: must be one of `"AI_RECOMMENDATION"`, `"ADMIN_OVERRIDE"`, `"FALLBACK_RECOMMENDATION"`, `"AI_RECOMMENDATION_ACCEPTED"`, `"DLQ_FAILURE"`
    - _Requirements: 6.1, 6.2, 6.3, 6.6_

- [x] 3. Backend — Utility modules
  - [x] 3.1 Implement `utils/logger.py` — structured JSON logger
    - Configure Python `logging` module to emit structured JSON with fields: `timestamp`, `level`, `handler`, `jobId` (optional), `message`
    - Expose a `get_logger(name: str) -> logging.Logger` factory function
    - _Requirements: 15.1_

  - [x] 3.2 Implement `utils/validator.py` — input validation helpers
    - Implement `validate_job_event(event: dict) -> JobEvent` — validates all required fields are present and non-null; raises `ValidationError` with field-level detail on failure
    - Implement `validate_vendor_profile(profile: dict) -> VendorProfile` — validates all required VendorProfile fields; raises `ValidationError` on failure
    - Implement `validate_override_request(body: dict) -> OverrideRequest` — validates `jobId`, `vendorId`, `overrideReason` (10–500 chars), `userId`; raises `ValidationError` on failure
    - Define `ValidationError` exception class with a `fields: dict` attribute
    - _Requirements: 4.7, 5.3, 5.4, 18.1, 18.2_

  - [x] 3.3 Implement `utils/model_version.py` — S3-backed model version cache
    - Implement `get_model_version() -> str` that reads `model-version.txt` from the Lambda zip S3 bucket on first call and caches the result in a module-level variable
    - Fall back to `"0.0.0"` and log a warning if the S3 read fails
    - Validate that the returned string matches semantic versioning format `MAJOR.MINOR.PATCH`
    - _Requirements: 14.1, 14.3, 14.4_

- [x] 4. Backend — Service layer
  - [x] 4.1 Implement `services/dynamodb.py` — DynamoDB wrapper
    - Wrap `boto3` DynamoDB resource with typed helpers: `get_item(table, key)`, `put_item(table, item)`, `query(table, key_condition, filter_expression, limit, next_token)`, `scan(table, filter_expression)`, `update_item(table, key, update_expression)`
    - Use conditional expressions on `put_item` to prevent silent overwrites where appropriate
    - Define `DynamoDBWriteError` exception class
    - _Requirements: 6.5, 6.7_

  - [x] 4.2 Implement `services/s3.py` — S3 wrapper
    - Implement `read_object(bucket, key) -> str`, `write_object(bucket, key, body: str)`, `write_json_object(bucket, key, data: dict)` using `boto3` S3 client
    - Used for model version reads, audit log writes (SSE-S3 encrypted), and override feedback writes
    - _Requirements: 6.5, 6.8, 14.1, 17.1_

  - [x] 4.3 Implement `services/secrets.py` — Secrets Manager cache
    - Implement `get_gemini_api_key() -> str` that fetches the secret named `ai-vrs/gemini-api-key` from AWS Secrets Manager on first call and caches it in a module-level variable
    - Define `SecretFetchError` exception class raised when the secret cannot be retrieved
    - _Requirements: 15.4_

  - [x] 4.4 Implement `services/pii_masker.py` — PII redaction
    - Implement `mask(data: dict) -> dict` that performs a deep copy of the input dict and replaces values matching known PII field names (`email`, `phone`, `address`, `name` patterns) and regex patterns (email addresses, phone numbers) with `"[REDACTED]"`
    - Return the masked copy; leave the original dict unmodified (used for S3 unmasked write)
    - _Requirements: 6.4, 6.8_

  - [x]* 4.5 Write unit tests for `pii_masker.py`
    - Test that email addresses in values are redacted
    - Test that phone number patterns are redacted
    - Test that non-PII fields are preserved unchanged
    - Test that the original dict is not mutated
    - _Requirements: 6.4_

  - [x] 4.6 Implement `services/fallback_scorer.py` — rule-based rationale generator
    - Implement `generate_rationale(score_factors: ScoreFactors, rank: int) -> str` that constructs a plain-English rationale by describing the top contributing score dimensions
    - Output must be structurally identical to AI rationale: same field names, same `modelVersion`
    - Example: `"Vendor ranked #1 due to high completion rate (0.94), strong availability, and close location proximity."`
    - _Requirements: 3.1, 3.5_

  - [x] 4.7 Implement `services/audit_logger.py` — dual-write audit logger
    - Implement `log_recommendation(job, ranked_vendors, model_version, ai_unavailable)` — assembles and writes `AuditLog` with `action="AI_RECOMMENDATION"` or `"FALLBACK_RECOMMENDATION"`
    - Implement `log_override(job, original_recommendation, selected_vendor_id, reason, user_id, model_version)` — assembles and writes `AuditLog` with `action="ADMIN_OVERRIDE"`
    - Implement `log_acceptance(job, recommendation, model_version)` — writes `AuditLog` with `action="AI_RECOMMENDATION_ACCEPTED"`
    - Implement `log_dlq_failure(job_id, reason, timestamp)` — writes `AuditLog` with `action="DLQ_FAILURE"`
    - Call `pii_masker.mask()` before DynamoDB write; write unmasked data to S3 with SSE-S3
    - Retry DynamoDB write up to 3 times with exponential backoff; log failure to CloudWatch after exhausting retries
    - Assign `logId` using `uuid.uuid4()` for every record
    - Emit `RecommendationConfidenceDistribution` CloudWatch metric after each AI recommendation log
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 17.2_

  - [x]* 4.8 Write unit tests for `audit_logger.py`
    - Test that `piiMasked` is always `True` on DynamoDB records
    - Test that DynamoDB retry logic fires up to 3 times on `DynamoDBWriteError`
    - Test that `logId` is a valid UUID v4 string
    - Test that `log_dlq_failure` writes a record with `action="DLQ_FAILURE"`
    - _Requirements: 6.6, 6.7_

  - [x] 4.9 Implement `services/ai_client.py` — Gemini 2.5 Flash API client
    - Fetch API key from `services/secrets.py` at cold start; cache in module-level variable
    - Build structured prompt from `ScoreFactors` + job context using the template defined in the design document
    - Send HTTP POST to Gemini API with 8-second timeout
    - Retry logic: 2x on HTTP 5xx with exponential backoff; 0x on 4xx (except 429); respect `Retry-After` on 429 (max 30s wait)
    - Parse response: extract rationale text and `CONFIDENCE: HIGH/MEDIUM/LOW` indicator from last line using `extract_confidence()`
    - Raise `GeminiUnavailableError` on exhausted retries or timeout
    - _Requirements: 2.1, 2.2, 2.6, 19.1, 19.2, 19.3_

- [x] 5. Backend — Scoring engine
  - [x] 5.1 Implement scoring normalization and `totalScore` computation in `handlers/vendor_scoring.py`
    - Implement `normalize(vendor: VendorProfile, job: JobEvent) -> ScoreFactors` applying all 8 normalization rules from the design (completion direct, availability enum map, rework inverted, location exact/region/none, specialization binary, response time capped, SLA breach capped, active jobs capped)
    - Implement `same_region(loc1: str, loc2: str) -> bool` helper that returns `True` when two location strings share the same state abbreviation (e.g., both contain `"TX"`) — used to assign `locationScore = 0.5` for same-region but different-city vendors
    - Implement `compute_total_score(sf: ScoreFactors) -> float` using the weighted formula: `0.25*completion + 0.20*availability + 0.15*rework + 0.15*location + 0.10*specialization + 0.08*responseTime + 0.04*slaBreach + 0.03*activeJobs`
    - Round `totalScore` to 6 decimal places
    - Attach `modelVersion` from `utils/model_version.get_model_version()`
    - _Requirements: 1.2, 1.4, 14.2_

  - [x]* 5.2 Write property test: Score Bounds (Property 1)
    - **Property 1: Score Bounds** — for any valid `VendorProfile` and `JobEvent`, `totalScore` is always in `[0.0, 1.0]`
    - Use Hypothesis `@given` with strategies generating arbitrary valid vendor and job inputs
    - **Validates: Requirements 1.2**

  - [x] 5.3 Implement vendor ranking and tie-breaking in `handlers/vendor_scoring.py`
    - Implement `rank_vendors(score_factors: list[ScoreFactors]) -> list[ScoreFactors]` that filters out vendors with `availabilityScore == 0.0`, sorts by `(-totalScore, activeJobs, vendorId)`, and returns the top 5
    - Implement `compute_confidence(ranked: list[ScoreFactors]) -> str` using the score distribution logic: High if `top > 0.75 and gap > 0.10`; Low if `top < 0.50 or all_within_0.05`; else Medium; downgrade to Low if AI indicator is LOW
    - _Requirements: 1.3, 1.5, 1.6, 2.4_

  - [x]* 5.4 Write property test: Ranking Consistency (Property 2)
    - **Property 2: Ranking Consistency** — the ranked list is always sorted in descending order of `totalScore`; no vendor at position `i` has a lower `totalScore` than the vendor at position `i+1`
    - **Validates: Requirements 1.3**

  - [x]* 5.5 Write property test: Unavailable Vendor Exclusion (Property 3)
    - **Property 3: Unavailable Vendor Exclusion** — no vendor with `availability == "unavailable"` appears in the ranked output
    - **Validates: Requirements 1.1**

  - [x]* 5.6 Write property test: Ranked List Size Bound (Property 4)
    - **Property 4: Ranked List Size Bound** — the ranked list always contains between 0 and 5 vendors inclusive
    - **Validates: Requirements 1.3, 1.6**

  - [x]* 5.7 Write property test: Tie-Breaking Determinism (Property 6)
    - **Property 6: Tie-Breaking Determinism** — when two vendors share an identical `totalScore` (rounded to 6 decimal places), the vendor with the lower `activeJobs` ranks higher; if equal, the vendor with the lexicographically lower `vendorId` ranks higher
    - **Validates: Requirements 1.5**

  - [x]* 5.8 Write property test: Confidence Level Validity (Property 8)
    - **Property 8: Confidence Level Validity** — every `Recommendation` record has a `confidence` value that is exactly one of `"High"`, `"Medium"`, `"Low"`
    - **Validates: Requirements 2.4**

  - [x] 5.9 Implement full `handlers/vendor_scoring.py` orchestration
    - Read all `VendorProfile` records from DynamoDB via `services/dynamodb.py`
    - Validate each profile via `utils/validator.validate_vendor_profile()`; exclude invalid profiles and emit `VendorProfileDataQualityErrors` CloudWatch metric per excluded vendor
    - Filter out `availability == "unavailable"` vendors before scoring
    - Call `normalize()` and `compute_total_score()` for each eligible vendor
    - Call `rank_vendors()` and `compute_confidence()`
    - Return ranked `ScoreFactors` list with `modelVersion` attached
    - Emit `FallbackScorerActivations` CloudWatch metric when fallback is used
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 3.3, 18.2, 18.3, 18.4, 19.6_

- [x] 6. Backend — Recommendation and fallback handler
  - [x] 6.1 Implement `handlers/recommendation.py` — AI rationale assembly
    - Receive ranked `ScoreFactors` list from `vendor_scoring`
    - For each of the top 5 vendors, call `services/ai_client.get_rationale(score_factors, job)` with 8-second timeout
    - On `GeminiUnavailableError` or timeout, call `services/fallback_scorer.generate_rationale()` instead and set `isAIGenerated=False`
    - Assemble `Recommendation` records with rationale, confidence, `modelVersion`, `timestamp`, and `isAIGenerated` flag
    - Write `Recommendation` records to DynamoDB Recommendations table
    - Emit `FallbackScorerActivations` CloudWatch metric when fallback path is taken
    - _Requirements: 2.1, 2.3, 2.5, 2.6, 2.7, 3.1, 3.4, 19.6_

  - [x]* 6.2 Write property test: Fallback Structural Equivalence (Property 7)
    - **Property 7: Fallback Structural Equivalence** — the `ScoreFactors` record produced by `fallback_scorer` has the same field names, same types, and same `modelVersion` as one produced by the normal scoring path
    - **Validates: Requirements 3.5**

- [x] 7. Backend — Override, auth, and query handlers
  - [x] 7.1 Implement `handlers/override.py` — override submission handler
    - Handle `POST /override` HTTP requests routed from `router.py`
    - Validate override payload via `utils/validator.validate_override_request()`: `jobId`, `vendorId`, `overrideReason` (10–500 chars), `userId`; return HTTP 400 on failure
    - Check job eligibility: query DynamoDB Jobs table; return HTTP 409 if job status is `"Assigned"` or already overridden
    - Write override record to DynamoDB AuditLog table and S3 override feedback bucket (partitioned by `year/month/day`)
    - Publish `VendorOverrideRecorded_Event` to EventBridge with `jobId`, `selectedVendorId`, `timestamp`
    - Include all retraining fields in the S3 record: `jobId`, original ranked list, `selectedVendorId`, `overrideReason`, `ScoreFactors` for all ranked vendors, `timestamp`
    - Return HTTP 200 on success
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 17.1, 17.5_

  - [x]* 7.2 Write unit tests for `override.py`
    - Test that missing `overrideReason` returns HTTP 400
    - Test that `overrideReason` shorter than 10 characters returns HTTP 400
    - Test that `overrideReason` longer than 500 characters returns HTTP 400
    - Test that overriding an already-assigned job returns HTTP 409
    - Test that a valid override writes to DynamoDB and S3 and publishes to EventBridge
    - _Requirements: 5.3, 5.4, 5.7_

  - [x] 7.3 Implement `handlers/auth.py` — Cognito Post-Confirmation trigger
    - Handle Cognito `PostConfirmation_ConfirmSignUp` trigger events routed from `router.py`
    - Create a `User` record in DynamoDB Users table with `userId` (Cognito sub), `email`, `createdAt`
    - Return the Cognito event dict unchanged (required by Cognito trigger contract)
    - _Requirements: 7.6_

  - [x] 7.4 Implement `handlers/query.py` — all HTTP read/write endpoints
    - `POST /jobs` — validate request body, create job record in DynamoDB Jobs table, publish `JobCreated_Event` to EventBridge, return HTTP 201 with job record including `schemaVersion: "1.0"`
    - `GET /jobs` — paginated scan/query with optional `status` and date range filters; return `items` array and `nextToken`
    - `GET /jobs/{jobId}` — fetch single job from DynamoDB; return HTTP 404 if not found
    - `GET /recommendations/{jobId}` — fetch ranked recommendations from DynamoDB; return HTTP 404 if not found; response includes `isFallback` flag and `vendorName` on each recommendation item
    - `POST /recommendations/{jobId}/accept` — write `AuditLog` with `action="AI_RECOMMENDATION_ACCEPTED"` via `audit_logger`; return HTTP 200 with `logId` and `timestamp`; return HTTP 409 if job already has confirmed vendor
    - `GET /audit-logs` — paginated query with optional `action` type and date range filters; support `jobId` and `vendorId` search params
    - `GET /audit-logs/{logId}` — fetch single audit log record; return HTTP 404 if not found
    - `GET /dashboard/metrics` — return: `date`, `totalJobsToday`, `totalRecommendationsToday`, `totalOverridesToday`, `aiServiceStatus` ("Active" or "Fallback"), `fallbackActivationsToday`, `lowConfidenceRateToday`
    - _Requirements: 10.1, 10.2, 10.4, 10.5, 11.6, 13.1, 13.3, 13.4, 16.5_

  - [x] 7.5 Implement `handlers/job_created.py` — SQS event orchestrator
    - Handle SQS-delivered `JobCreated_Event` messages routed from `router.py`
    - Validate the `JobEvent` payload via `utils/validator.validate_job_event()`; raise an exception on failure (SQS routes to DLQ after max retries); call `audit_logger.log_dlq_failure()` before raising
    - Orchestrate the scoring pipeline: call `vendor_scoring` → `recommendation` → `audit_logger`
    - Publish `VendorRecommendationGenerated_Event` to EventBridge on success (with `jobId`, ranked list, `modelVersion`, `timestamp`, `schemaVersion`)
    - Publish `NoEligibleVendors_Event` to EventBridge and log a CloudWatch warning if no eligible vendors found
    - Complete full scoring within 10 seconds excluding Gemini API latency
    - _Requirements: 1.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 18.5, 19.5, 19.7_

  - [x] 7.6 Implement `router.py` — Lambda event router
    - Inspect event structure to determine source: API Gateway (`httpMethod` present), SQS (`Records[0].eventSource == "aws:sqs"`), EventBridge (`source` present), Cognito (`triggerSource == "PostConfirmation_ConfirmSignUp"`)
    - Dispatch to the correct handler module based on source and HTTP path/method
    - Return standard API Gateway response dict for HTTP events; plain dict for async events
    - _Requirements: 4.1_

  - [x] 7.7 Implement `handler.py` — Lambda entry point
    - Define `lambda_handler(event: dict, context) -> dict` that delegates to `router.route(event, context)`
    - _Requirements: 15.1_

- [x] 8. Backend — CloudWatch metrics and alarms wiring
  - Add `FallbackScorerActivations` metric emission in `handlers/recommendation.py` (increment by 1 each time fallback is used)
  - Add `VendorProfileDataQualityErrors` metric emission in `handlers/vendor_scoring.py` (increment by 1 per excluded vendor)
  - Add `RecommendationConfidenceDistribution` metric emission in `services/audit_logger.py` (record confidence level per recommendation)
  - Add `HighLowConfidenceRate` alarm logic: when Low-confidence proportion in a 24-hour window exceeds 30%, publish CloudWatch alarm
  - Add `HighOverrideRate` alarm logic: when override rate in a 7-day window exceeds 40%, publish CloudWatch alarm
  - _Requirements: 17.2, 17.3, 17.4, 18.4, 19.6_

- [x] 9. Backend checkpoint — Ensure all tests pass
  - Run `pytest tests/` and confirm all unit and property tests pass
  - Verify that `handler.py` can be imported without errors
  - Ask the user if any questions arise before proceeding to the frontend.


- [x] 10. Frontend — Vite + React 18 project setup
  - Scaffold the frontend project using `npm create vite@5.2.0 frontend -- --template react` (React 18, Vite)
  - Install pinned dependencies: `react-router-dom@6.23.0`, `axios@1.7.2`, `amazon-cognito-identity-js@6.3.7`
  - Configure `vite.config.js` with a dev proxy for `/api` pointing to the API Gateway URL (read from env var `VITE_API_URL`)
  - Create `frontend/.env.example` with required variables: `VITE_API_URL`, `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_CLIENT_ID`
  - Create `frontend/src/main.jsx` with `ReactDOM.createRoot` and `<BrowserRouter>` wrapping `<App />`
  - Create `frontend/src/App.jsx` with React Router v6 `<Routes>` defining all page routes: `/auth` (public), `/` redirect to `/dashboard`, `/dashboard`, `/jobs`, `/jobs/:jobId`, `/recommendations/:jobId`, `/override/:jobId`, `/audit-logs` (all protected)
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 11. Frontend — API and auth service layer
  - [x] 11.1 Implement `frontend/src/services/auth.js` — Cognito JWT auth service using `amazon-cognito-identity-js`
    - Implement `login(email, password) -> { accessToken, refreshToken }` using Cognito `AuthenticationDetails` + `CognitoUser.authenticateUser()`
    - Implement `register(email, password) -> void` using `CognitoUserPool.signUp()`
    - Implement `logout() -> void` that calls `CognitoUser.signOut()` and clears localStorage
    - Implement `refreshAccessToken() -> string` using the stored refresh token to obtain a new access token without re-entering credentials
    - Store tokens in `localStorage`; clear on logout
    - _Requirements: 7.3, 7.5, 7.8_

  - [x] 11.2 Implement `frontend/src/context/AuthProvider.jsx` — React Context for auth state
    - Create `AuthContext` with `user`, `isAuthenticated`, `login(email, password)`, `register(email, password)`, `logout()`, `getAccessToken()` values
    - Wrap the app in `<AuthProvider>` in `main.jsx`; all protected pages consume this context
    - On mount, check localStorage for existing tokens and restore session if valid
    - _Requirements: 7.3, 7.5, 8.4_

  - [x] 11.3 Implement `frontend/src/hooks/useAuth.js` — auth hook
    - Wraps `AuthContext`; exposes: `user`, `isAuthenticated`, `login`, `register`, `logout`, `getAccessToken`
    - _Requirements: 7.3_

  - [x] 11.4 Implement `frontend/src/hooks/useRecommendations.js` — recommendations data hook
    - Fetches recommendations for a given `jobId` via `api.getRecommendations(jobId)`
    - Returns: `{ recommendations, isFallback, isLoading, error, refetch }`
    - _Requirements: 11.1, 11.7_

  - [x] 11.5 Implement `frontend/src/services/api.js` — Axios API client
    - Create an Axios instance with `baseURL` from `VITE_API_URL`
    - Add a request interceptor that attaches `Authorization: Bearer <accessToken>` from `AuthContext` to every request
    - Add a response interceptor that calls `auth.refreshAccessToken()` on HTTP 401 and retries the original request once; redirects to `/auth` if refresh fails
    - Implement typed functions for all endpoints: `createJob`, `getJobs`, `getJob`, `getRecommendations`, `acceptRecommendation`, `submitOverride`, `getAuditLogs`, `getAuditLog`, `getDashboardMetrics`
    - _Requirements: 7.4, 7.5_

- [x] 12. Frontend — Layout components
  - [x] 12.1 Implement `components/layout/Header.jsx`
    - Render the RetailFixIt logo, current page title (passed as prop), and a logout button
    - Logout button calls `auth.logout()` and redirects to `/login`
    - _Requirements: 8.1_

  - [x] 12.2 Implement `components/layout/Sidebar.jsx`
    - Render navigation links to: Dashboard (`/`), Jobs (`/jobs`), Recommendations (`/recommendations`), Override (`/override`), Audit Log (`/audit-log`)
    - Highlight the active route using React Router `NavLink`
    - _Requirements: 8.2_

  - [x] 12.3 Implement `components/layout/Footer.jsx`
    - Render a simple footer with copyright text
    - _Requirements: 8.3_

  - [x] 12.4 Implement `components/layout/Layout.jsx` and `ProtectedRoute`
    - `Layout.jsx` composes `Header`, `Sidebar`, `Footer`, and an `<Outlet />` for page content
    - `ProtectedRoute` checks for a valid access token in `localStorage`; redirects to `/login` if absent
    - Conditionally render `FallbackBanner` at the top of every page when the API returns `fallbackActive: true` in dashboard metrics
    - Ensure layout renders correctly on viewport widths 1024px–2560px using CSS flexbox/grid
    - _Requirements: 8.4, 8.5, 8.6_

- [x] 13. Frontend — Shared UI components
  - [x] 13.1 Implement `components/ui/ConfidenceBadge.jsx`
    - Accept `confidence: "High" | "Medium" | "Low"` prop
    - Render with distinct visual styling: green background for High, amber for Medium, red for Low
    - _Requirements: 11.3_

  - [x] 13.2 Implement `components/ui/RationaleBox.jsx`
    - Accept `rationale: string` and `isAIGenerated: boolean` props
    - Display the rationale text in a styled box; show a label indicating AI-generated vs. rule-based
    - _Requirements: 11.2_

  - [x] 13.3 Implement `components/ui/FallbackBanner.jsx`
    - Render a prominent banner indicating AI rationale is unavailable and recommendations are rule-based
    - _Requirements: 3.2, 8.5, 11.4_

  - [x] 13.4 Implement `components/ui/LoadingSpinner.jsx`
    - Render an accessible loading spinner (with `aria-label="Loading"`)
    - _Requirements: 10.5, 11.7, 13.6_

  - [x] 13.5 Implement `components/ui/ErrorBanner.jsx`
    - Accept `message: string` and `onRetry: () => void` props
    - Render an error message with a retry button
    - _Requirements: 10.6, 12.5_

  - [x] 13.6 Implement `components/ui/OverridePanel.jsx`
    - Accept `selectedVendor` and `onReasonChange` props
    - Display the selected vendor's profile summary
    - Include a required `<textarea>` for override reason with a live character counter (max 500)
    - _Requirements: 12.2, 12.3_

  - [x] 13.7 Implement `components/ui/MetricCard.jsx` and `components/ui/AIStatusBadge.jsx`
    - `MetricCard` — accepts `label: string` and `value: number | string` props; renders a styled card used on the Dashboard for Jobs Today, Recommendations Today, Overrides Today
    - `AIStatusBadge` — accepts `status: "Active" | "Fallback"` prop; renders green badge for Active, amber badge for Fallback; used on Dashboard
    - _Requirements: 10.1_

  - [x] 13.8 Implement `components/ui/JobFilterBar.jsx`
    - Renders a status dropdown (Pending / Recommended / Assigned / Override / All) and two date pickers (from / to)
    - Calls `onFilterChange(filters)` callback when any filter changes; used on Jobs page
    - _Requirements: 10.5_

  - [x] 13.9 Implement `components/ui/VendorCard.jsx` and `components/ui/CriticalJobWarning.jsx`
    - `VendorCard` — renders a single ranked vendor on the Recommendations page: vendor name, rank badge, total score bar, 8-dimension `ScoreFactors` breakdown, `RationaleBox`, `ConfidenceBadge`, and Accept / Override buttons
    - `CriticalJobWarning` — renders a prominent warning banner when `urgency == "Critical"` or SLA deadline is within 2 hours; requires explicit Admin acknowledgment (checkbox or confirm button) before Accept is enabled
    - _Requirements: 11.2, 11.3, 16.2_

  - [x] 13.10 Implement `components/ui/AuditFilterBar.jsx`
    - Renders action type dropdown (AI_RECOMMENDATION / ADMIN_OVERRIDE / FALLBACK_RECOMMENDATION / AI_RECOMMENDATION_ACCEPTED / All), date range pickers, and text inputs for `jobId` and `vendorId` search
    - Calls `onFilterChange(filters)` callback; used on Audit Log page
    - _Requirements: 13.3, 13.4_

- [x] 14. Frontend — Authentication page
  - Implement `pages/AuthPage.jsx` with two tabs: "Login" and "Register"
  - Login tab: email and password fields, submit button; on failure display inline error without clearing email field
  - Register tab: email, password, confirm-password fields; validate password match client-side before submit; display inline error on duplicate email
  - On successful login, redirect to `/` (Dashboard)
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

- [x] 15. Frontend — Dashboard page
  - Implement `pages/DashboardPage.jsx`
  - Call `api.getDashboardMetrics()` on mount; display: total jobs created today, total recommendations generated today, total overrides applied today, current AI service status (Active or Fallback)
  - Show `LoadingSpinner` while loading; show `ErrorBanner` on API error
  - _Requirements: 10.1_

- [x] 16. Frontend — Jobs page
  - Implement `pages/JobsPage.jsx`
  - Display a paginated list of jobs; each row shows: `jobId`, job type, location, urgency, SLA deadline, status
  - Support filtering by job status and date range (from/to); pass filters as query params to `api.getJobs()`
  - Clicking a job row navigates to a `JobDetail` view showing all job fields plus a link to `/recommendations?jobId=...`
  - Show `LoadingSpinner` while loading; show `ErrorBanner` with retry button on API error
  - Display a prominent warning on the job detail view when `urgency == "Critical"` or SLA deadline is within 2 hours, requiring explicit Admin acknowledgment before accepting a recommendation
  - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 16.2_

- [x] 17. Frontend — Recommendations page
  - Implement `pages/RecommendationsPage.jsx`
  - Read `jobId` from query params; call `api.getRecommendations(jobId)` on mount
  - Display ranked list of up to 5 vendors ordered by descending `totalScore`; for each: vendor name, total score, `ScoreFactors` breakdown, `RationaleBox`, `ConfidenceBadge`
  - Show `FallbackBanner` above the list when `isAIGenerated == false`
  - Show additional advisory message when `confidence == "Low"` recommending manual review
  - "Override" button navigates to `/override?jobId=...`
  - "Accept" button calls `api.acceptRecommendation(jobId)` and records acceptance; show success confirmation
  - Show `LoadingSpinner` while loading
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 16.3_

- [x] 18. Frontend — Override page
  - Implement `pages/OverridePage.jsx`
  - Read `jobId` from query params; display current AI-recommended vendor list alongside a vendor selection dropdown listing all eligible vendors
  - On vendor selection, render `OverridePanel` with the selected vendor's profile summary and the reason textarea (character counter, max 500)
  - On form submit with valid vendor and reason, call `api.submitOverride()`; show success confirmation and update job status display to "Vendor Assigned — Override"
  - On API failure, show `ErrorBanner` with failure reason and preserve form state for retry
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [x] 19. Frontend — Audit Log page
  - Implement `pages/AuditLogPage.jsx`
  - Display a paginated list of `AuditLog` records ordered by descending timestamp
  - Each row shows: `logId`, `jobId`, action type, `vendorId`, `confidence` (for AI recommendations), `modelVersion`, `piiMasked`, `timestamp`
  - Support filtering by action type and date range; support searching by `jobId` or `vendorId`
  - Clicking a record opens a detail panel showing full `input` and `output` fields
  - Show `LoadingSpinner` while loading
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [x] 20. Frontend checkpoint — Ensure all pages render without errors
  - Verify all pages render without console errors using `npm run build` (Vite production build)
  - Confirm React Router routes are correctly wired in `App.jsx`
  - Ask the user if any questions arise before proceeding to Terraform.


- [x] 21. Terraform — DynamoDB tables
  - Create `infra/terraform/dynamodb.tf` defining all 5 DynamoDB tables with `billing_mode = "PAY_PER_REQUEST"` and `point_in_time_recovery { enabled = true }`:
    - `ai-vrs-jobs` table: partition key `jobId` (String); GSIs: `status-createdAt-index` (PK: `status`, SK: `createdAt`), `createdAt-index` (PK: `createdAt` date prefix, SK: `jobId`)
    - `ai-vrs-vendors` table: partition key `vendorId` (String); GSI: `availability-index` (PK: `availability`, SK: `vendorId`)
    - `ai-vrs-recommendations` table: partition key `jobId` (String), sort key `rank` (Number); GSIs: `vendorId-timestamp-index`, `modelVersion-index`
    - `ai-vrs-audit-log` table: partition key `logId` (String); GSIs: `jobId-timestamp-index`, `action-timestamp-index`, `vendorId-timestamp-index`
    - `ai-vrs-users` table: partition key `userId` (String); GSI: `email-index` (PK: `email`) for duplicate registration check
  - _Requirements: 15.1, 15.5_

- [x] 22. Terraform — S3 buckets
  - Create `infra/terraform/s3.tf` defining 3 S3 buckets with `aws_s3_bucket_public_access_block` (all four settings `true`) on each:
    - `ai-vrs-lambda-zip` — stores Lambda deployment zip and `model-version.txt`; SSE-S3 encryption; versioning enabled (`aws_s3_bucket_versioning`)
    - `ai-vrs-logs` — stores audit log exports; SSE-S3 encryption; lifecycle rule: transition to S3 Glacier after 90 days, expire after 365 days
    - `ai-vrs-override-feedback` — stores override feedback JSON; SSE-S3 encryption; lifecycle rule: expire after 730 days (2 years for retraining data); key prefix pattern `year={YYYY}/month={MM}/day={DD}/`
  - _Requirements: 15.1, 15.6, 17.5_

- [x] 23. Terraform — IAM role and Lambda function
  - Create `infra/terraform/iam.tf` defining the Lambda execution role with least-privilege inline policy:
    - DynamoDB: `GetItem`, `PutItem`, `Query`, `Scan`, `UpdateItem` on all 5 AI-VRS tables
    - S3: `GetObject`, `PutObject` on all 3 AI-VRS buckets
    - Secrets Manager: `GetSecretValue` on `ai-vrs/gemini-api-key`
    - EventBridge: `PutEvents` on AI-VRS event bus
    - SQS: `ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes` on the vendor scoring queue
    - CloudWatch Logs: `CreateLogGroup`, `CreateLogStream`, `PutLogEvents`
    - CloudWatch Metrics: `PutMetricData`
  - Create `infra/terraform/lambda.tf` defining the Lambda function:
    - Runtime: `python3.12`, handler: `handler.lambda_handler`, memory: 512MB, timeout: 25 seconds
    - Source: zip from `ai-vrs-lambda-zip` S3 bucket (key from `var.lambda_zip_key`)
    - Set `reserved_concurrent_executions` via `var.lambda_reserved_concurrency` (default: 10)
    - Set environment variables: `JOBS_TABLE`, `VENDORS_TABLE`, `RECOMMENDATIONS_TABLE`, `AUDIT_LOG_TABLE`, `USERS_TABLE`, `LAMBDA_ZIP_BUCKET`, `LOGS_BUCKET`, `OVERRIDE_FEEDBACK_BUCKET`, `GEMINI_SECRET_NAME`, `EVENTBRIDGE_BUS_NAME`, `SQS_QUEUE_URL`, `ENVIRONMENT`
    - Do NOT store the Gemini API key in environment variables — only `GEMINI_SECRET_NAME` (the secret name string)
    - Add SQS event source mapping for `vendor-scoring-queue` with `batch_size = 1`
    - _Requirements: 15.2, 15.3, 15.4_

- [x] 24. Terraform — Cognito User Pool and App Client
  - Create `infra/terraform/cognito.tf` defining:
    - Cognito User Pool with self-registration enabled, email verification required
    - Password policy: minimum 8 characters, require uppercase, lowercase, digit, and special character
    - Post-Confirmation Lambda trigger pointing to the AI-VRS Lambda function ARN
    - App Client with explicit auth flows: `ALLOW_USER_PASSWORD_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH`, `ALLOW_USER_SRP_AUTH`; no client secret (SPA); access token validity: 1 hour; refresh token validity: 30 days
  - _Requirements: 7.1, 7.2, 7.7_

- [x] 25. Terraform — API Gateway with Cognito Authorizer and CORS
  - Create `infra/terraform/api_gateway.tf` defining:
    - REST API with proxy integration to the Lambda function
    - Cognito Authorizer validating JWT tokens from the User Pool
    - All routes protected by the Cognito Authorizer: `POST /jobs`, `GET /jobs`, `GET /jobs/{jobId}`, `GET /recommendations/{jobId}`, `POST /recommendations/{jobId}/accept`, `POST /override`, `GET /audit-logs`, `GET /audit-logs/{logId}`, `GET /dashboard/metrics`
    - CORS configuration with an explicit `allowed_origins` list (no wildcard `*` in production); allowed methods: `GET, POST, OPTIONS`; allowed headers: `Authorization, Content-Type`
  - _Requirements: 7.4, 15.1, 15.4_

- [x] 26. Terraform — EventBridge rules and SQS queue with DLQ
  - Create `infra/terraform/eventbridge.tf` defining EventBridge rules:
    - `JobCreated` rule: event pattern `source = "retailfixit.jobs"`, `detail-type = "JobCreated"`; target: SQS vendor-scoring-queue; include `aws_sqs_queue_policy` granting EventBridge permission to send to the queue
    - `VendorRecommendationGenerated` rule: event pattern `detail-type = "VendorRecommendationGenerated"`; target: CloudWatch log group
    - `VendorOverrideRecorded` rule: event pattern `detail-type = "VendorOverrideRecorded"`; target: CloudWatch log group
    - `NoEligibleVendors` rule: event pattern `detail-type = "NoEligibleVendors"`; target: CloudWatch log group + SNS alert topic
  - Create `infra/terraform/sqs.tf` defining:
    - `ai-vrs-vendor-scoring-dlq` — message retention: 14 days
    - `ai-vrs-vendor-scoring-queue` (main) — visibility timeout: 30 seconds (must exceed Lambda timeout), message retention: 4 days; redrive policy: `maxReceiveCount = 3`, `deadLetterTargetArn = dlq.arn`
  - Create `infra/terraform/secrets.tf` with a data source reference (not a resource) for the existing Secrets Manager secret: `data "aws_secretsmanager_secret" "gemini_api_key" { name = "ai-vrs/gemini-api-key" }` — the secret is pre-provisioned manually and must NOT be created by Terraform
  - _Requirements: 4.1, 4.2, 4.3, 15.1_

- [x] 27. Terraform — CloudWatch log groups and alarms
  - Create `infra/terraform/cloudwatch.tf` defining:
    - Lambda log group `/aws/lambda/ai-vrs` with `retention_in_days = 90`
    - Audit log export log group `/ai-vrs/audit-log-exports` with `retention_in_days = 365`
    - CloudWatch alarm `HighLowConfidenceRate`: triggers when `RecommendationConfidenceDistribution` (Low fraction) > 0.30 over a 24-hour period; alarm action: SNS topic
    - CloudWatch alarm `HighOverrideRate`: triggers when override rate > 0.40 over a 7-day window; alarm action: SNS topic
    - CloudWatch alarm `FallbackScorerActivations`: triggers when `FallbackScorerActivations` count > 10 in a 1-hour period; alarm action: SNS topic
    - `aws_cloudwatch_log_metric_filter` resources for extracting `VendorProfileDataQualityErrors` and `FallbackScorerActivations` counts from Lambda log output
  - _Requirements: 15.1, 15.7, 17.3, 17.4_

- [x] 28. Terraform — variables.tf, Secrets Manager reference, and outputs
  - Create `infra/terraform/variables.tf` with all input variables: `aws_region` (default: `"us-east-1"`), `environment` (default: `"production"`), `lambda_zip_key` (default: `"lambda.zip"`), `lambda_reserved_concurrency` (default: `10`), `lambda_timeout` (default: `25`), `lambda_memory_size` (default: `512`), `allowed_cors_origin` (no default — must be set explicitly), `gemini_secret_name` (default: `"ai-vrs/gemini-api-key"`), `sqs_visibility_timeout` (default: `30`), `sqs_max_receive_count` (default: `3`), `cognito_access_token_validity` (default: `1`), `cognito_refresh_token_validity` (default: `30`)
  - Configure Terraform backend in `main.tf`: S3 bucket `retailfixit-terraform-state`, key `ai-vrs/terraform.tfstate`, region `us-east-1`, `encrypt = true`; Terraform version `~> 1.5`, AWS provider `~> 5.0`; `default_tags` with `Project = "ai-vrs"` and `Environment = var.environment`
  - Create `infra/terraform/outputs.tf` exposing: `api_gateway_url`, `cognito_user_pool_id`, `cognito_client_id`, `sqs_queue_url`, `dlq_url`
  - _Requirements: 15.1, 15.8, 21.5_

- [x] 29. Terraform checkpoint — Validate Terraform configuration
  - Run `terraform validate` in `infra/terraform/` and confirm no errors
  - Run `terraform fmt` to ensure consistent formatting
  - Ask the user if any questions arise before proceeding to scripts and docs.


- [x] 30. Scripts — `seed_data.py`
  - Create `scripts/seed_data.py` that populates DynamoDB with realistic test data:
    - Accept CLI arguments: `--region` (default: `us-east-1`), `--environment` (default: `production`), `--vendors` (default: 10), `--jobs` (default: 5), `--dry-run` (print without writing)
    - At least 10 `VendorProfile` records covering a range of `completionRate` values [0.70–0.98], all three `availability` states (weighted: 60% available, 30% busy, 10% unavailable), multiple `specializations` from ["plumbing", "electrical", "hvac", "carpentry", "roofing", "painting"], and multiple locations from ["Austin, TX", "Dallas, TX", "Houston, TX", "San Antonio, TX", "Phoenix, AZ"]
    - At least 5 `JobEvent` records covering different `type`, `urgency` levels (weighted: 40% Low, 30% Medium, 20% High, 10% Critical), and `slaDeadline` values (current time + 2 hours to 7 days)
    - Use `put_item` with `ConditionExpression="attribute_not_exists(vendorId)"` (and `attribute_not_exists(jobId)` for jobs) to make the script idempotent — running it multiple times must not create duplicates
    - All seeded `VendorProfile` records must include all required fields: `vendorId`, `name`, `completionRate`, `availability`, `reworkRate`, `location`, `specializations`, `avgResponseTime`, `slaBreachCount`, `activeJobs`
    - Print progress output showing each record created or skipped
  - _Requirements: 20.1, 20.2, 20.3, 20.4_

- [x] 31. Scripts — `deploy.sh`
  - Create `scripts/deploy.sh` with `set -e` (exit on any error) that executes these steps in order:
    - **[1/5] Package Lambda**: `cd backend/lambda && zip -r ../../infra/terraform/lambda.zip . -x "*.pyc" -x "__pycache__/*"` 
    - **[2/5] Upload Lambda zip to S3**: `aws s3 cp infra/terraform/lambda.zip s3://ai-vrs-lambda-zip/lambda.zip`
    - **[3/5] Upload model version**: write `1.0.0` to a temp file and upload to `s3://ai-vrs-lambda-zip/model-version.txt`
    - **[4/5] Terraform init**: `terraform -chdir=infra/terraform init`
    - **[5/5] Terraform apply**: `terraform -chdir=infra/terraform apply -auto-approve`
    - **Print outputs**: use `terraform -chdir=infra/terraform output -json` + `jq` to extract and print `api_gateway_url`, `cognito_user_pool_id`, `cognito_client_id`
    - Print "Next steps" instructions: update `frontend/.env` with the three output values, run `seed_data.py`, start frontend with `npm run dev`
  - _Requirements: 21.1, 21.5_

- [x] 32. Events — sample JSON payloads
  - Create `events/job_created.json` — a complete EventBridge envelope for `JobCreated_Event` with fields: `version`, `id`, `detail-type: "JobCreated"`, `source: "retailfixit.jobs"`, `account`, `time`, `region`, `resources: []`, and `detail` containing all required JobEvent fields: `jobId`, `type`, `location`, `urgency`, `slaDeadline`, `description`, `createdAt`, `schemaVersion: "1.0"`
  - Create `events/vendor_recommendation.json` — a complete EventBridge envelope for `VendorRecommendationGenerated_Event` with `detail-type: "VendorRecommendationGenerated"`, `source: "retailfixit.ai-vrs"`, and `detail` containing: `jobId`, `modelVersion`, `isFallback: false`, `recommendations` array (5 items each with `rank`, `vendorId`, `totalScore`, `confidence`), `timestamp`
  - Create `events/api_examples.json` — sample request/response pairs for: `POST /jobs` (201), `GET /recommendations/{jobId}` (200 with full scoreFactors), `POST /override` (200), `POST /recommendations/{jobId}/accept` (200)
  - _Requirements: 4.5, 4.6, 18.5, 21.6_

- [x] 33. Documentation — `README.md`
  - Create `README.md` at the project root with the following sections:
    - **System Overview** — what AI-VRS does, key AWS services, and the advisory-only AI principle
    - **Architecture** — link to `docs/architecture.md`
    - **AI Approach and Assumptions** — hybrid scoring engine, 8 scoring dimensions with weights table, Gemini 2.5 Flash rationale, fallback mode, list of 8 key assumptions
    - **Explainability** — how Gemini generates rationale from `ScoreFactors` and the prompt template; High/Medium/Low confidence calculation
    - **Feedback Loop and Model Retraining** — S3 override feedback schema; conceptual future retraining pipeline
    - **Deployment** — prerequisites (5 items), Quick Start (`./scripts/deploy.sh` + `seed_data.py` + `npm run dev`), manual deployment steps
    - **Development** — backend (`pytest tests/`), frontend (`npm run dev`), infrastructure (`terraform plan`)
    - **Testing** — unit tests, property-based tests (reference to 10 correctness properties), integration test scenarios
    - **Known Limitations and Next Steps** — 5 limitations (location matching, no retraining pipeline, Gemini dependency, single region, DynamoDB scan scale), 6 next steps
  - _Requirements: 21.2, 20.5_

- [x] 34. Documentation — `docs/governance_answers.md`, `docs/architecture.md`, and `docs/model_versioning.md`
  - Create `docs/governance_answers.md` with written answers to all four Part 3 governance questions:
    - **1. AI Authority & Risk** — final vendor assignment always requires Admin confirmation; Critical/near-SLA (< 2h) jobs require explicit acknowledgment; Low-confidence triggers manual review advisory; vendor pricing/demographics/customer identity must never be scoring factors
    - **2. Model Drift & Feedback** — `HighLowConfidenceRate` alarm (>30% Low in 24h), `HighOverrideRate` alarm (>40% in 7d); override data stored in S3 with full context; retraining safeguards: shadow mode, A/B testing, gradual rollout
    - **3. Data Quality & Events** — `JobCreated_Event` validation with `schemaVersion` field; `VendorProfileDataQualityErrors` metric; `VendorRecommendationGenerated_Event` with `modelVersion`; DLQ for failed events
    - **4. Failure Modes** — Gemini unavailable → Fallback_Scorer + FallbackBanner; Gemini slow (>8s) → timeout + fallback; Low confidence → UI warning; Lambda timeout → SQS reprocesses up to 3x then DLQ; no eligible vendors → `NoEligibleVendors_Event` + SNS alert
  - Create `docs/architecture.md` with: high-level ASCII diagram (from design), AWS services table (9 services with purpose and key config), event flow diagrams, component interaction description, advisory vs automated decisions table
  - Create `docs/model_versioning.md` with: version format (MAJOR.MINOR.PATCH), storage location (`s3://ai-vrs-lambda-zip/model-version.txt`), propagation flow, update process (5 steps), querying by version via DynamoDB GSI, rollback procedure
  - _Requirements: 21.3, 21.4_

- [x] 35. Testing — property-based tests for scoring engine
  - Create `tests/test_scoring_properties.py` using the Hypothesis library (`@given`, `@settings`)
  - Define Hypothesis strategies for generating valid `VendorProfile` and `JobEvent` instances with arbitrary but valid field values
  - [x]* 35.1 Write property test: Score Bounds (Property 1)
    - **Property 1: Score Bounds** — `totalScore` is always in `[0.0, 1.0]` for any valid inputs
    - **Validates: Requirements 1.2**
  - [x]* 35.2 Write property test: Weight Sum (design invariant)
    - Verify that the sum of all dimension weights in `WEIGHTS` dict equals exactly `1.0`
    - **Validates: Requirements 1.2**
  - [x]* 35.3 Write property test: Ranking Consistency (Property 2)
    - **Property 2: Ranking Consistency** — ranked list is always sorted in descending `totalScore` order
    - **Validates: Requirements 1.3**
  - [x]* 35.4 Write property test: Unavailable Vendor Exclusion (Property 3)
    - **Property 3: Unavailable Vendor Exclusion** — no vendor with `availability == "unavailable"` appears in ranked output
    - **Validates: Requirements 1.1**
  - [x]* 35.5 Write property test: Ranked List Size Bound (Property 4)
    - **Property 4: Ranked List Size Bound** — ranked list always has 0–5 vendors
    - **Validates: Requirements 1.3, 1.6**
  - [x]* 35.6 Write property test: Tie-Breaking Determinism (Property 6)
    - **Property 6: Tie-Breaking Determinism** — same input always produces the same ranked order; tie broken by `activeJobs` then `vendorId`
    - **Validates: Requirements 1.5**
  - [x]* 35.7 Write property test: Fallback Structural Equivalence (Property 7)
    - **Property 7: Fallback Structural Equivalence** — `fallback_scorer` output has same field names, types, and `modelVersion` as normal scoring output
    - **Validates: Requirements 3.5**
  - [x]* 35.8 Write property test: Confidence Level Validity (Property 8)
    - **Property 8: Confidence Level Validity** — `confidence` is always one of `"High"`, `"Medium"`, `"Low"`
    - **Validates: Requirements 2.4**
  - [x]* 35.9 Write property test: Model Version Propagation (Property 5)
    - **Property 5: Model Version Propagation** — every `ScoreFactors` record in the ranked output carries the same `modelVersion` string as the value returned by `get_model_version()`
    - Mock `get_model_version()` to return a fixed string; assert every item in the ranked output has `modelVersion == that string`
    - **Validates: Requirements 14.2, 1.4**
  - [x]* 35.10 Write property test: Override Reason Length (Property 9)
    - **Property 9: Override Reason Length** — `validate_override_request()` raises `ValidationError` for any `overrideReason` with `len < 10` or `len > 500`; accepts all reasons with `10 ≤ len ≤ 500`
    - Use Hypothesis `@given(st.text())` to generate arbitrary reason strings and verify the boundary
    - **Validates: Requirements 5.3, 5.4**
  - [x]* 35.11 Write property test: Audit Log PII Masking (Property 10)
    - **Property 10: Audit Log PII Masking** — for any dict containing email or phone patterns, `pii_masker.mask()` returns a copy where `piiMasked == True` and no value matches an email or phone regex; the original dict is not mutated
    - Use Hypothesis `@given` with strategies that inject email-like and phone-like strings into arbitrary dict structures
    - **Validates: Requirements 6.4, 6.8**

- [x] 36. Testing — unit tests for override handler, audit logger, and PII masker
  - Create `tests/test_vendor_scoring.py` with unit tests for the scoring normalization and `compute_confidence` functions:
    - Test each normalization formula with boundary values (0.0, 1.0, mid-range)
    - Test `compute_confidence` for all three branches (High, Medium, Low)
    - Test that fewer than 5 eligible vendors returns all of them without padding
    - _Requirements: 1.2, 1.3, 1.6, 2.4_
  - Create `tests/test_override_handler.py` with unit tests for `handlers/override.py`:
    - Test missing `overrideReason` → HTTP 400
    - Test `overrideReason` < 10 chars → HTTP 400
    - Test `overrideReason` > 500 chars → HTTP 400
    - Test overriding an already-assigned job → HTTP 409
    - Test valid override → DynamoDB write + S3 write + EventBridge publish + HTTP 200
    - _Requirements: 5.3, 5.4, 5.7_
  - Create `tests/test_audit_logger.py` with unit tests for `services/audit_logger.py`:
    - Test `piiMasked == True` on all DynamoDB records
    - Test DynamoDB retry fires up to 3 times on `DynamoDBWriteError`
    - Test `logId` is a valid UUID v4
    - _Requirements: 6.6, 6.7_
  - Create `tests/test_pii_masker.py` with unit tests for `services/pii_masker.py`:
    - Test email addresses in values are redacted to `"[REDACTED]"`
    - Test phone number patterns are redacted
    - Test non-PII fields are preserved unchanged
    - Test original dict is not mutated
    - _Requirements: 6.4_

- [x] 37. Final checkpoint — Ensure all tests pass
  - Run `pytest tests/ -v` and confirm all unit and property-based tests pass
  - Run `npm run build` in `frontend/` and confirm the Vite production build succeeds with no errors
  - Run `terraform validate` in `infra/terraform/` and confirm no configuration errors
  - Ask the user if any questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; they do not block subsequent tasks
- Each task references specific requirements for traceability
- Checkpoints (tasks 9, 20, 29, 37) ensure incremental validation at phase boundaries
- Property tests in `tests/test_scoring_properties.py` (task 35) cover all 10 correctness properties defined in the design document (Properties 1–10)
- The Gemini API key must be manually stored in AWS Secrets Manager under `ai-vrs/gemini-api-key` before running `deploy.sh`
- The Terraform state S3 bucket (`retailfixit-terraform-state`) must exist before running `terraform init`
- `faker` is used by `scripts/seed_data.py` for realistic test data generation; it is listed in `requirements.txt` (task 1)
- The `same_region()` helper (task 5.1) is the only location-matching logic — it uses state abbreviation matching as a deliberate simplification (see design tradeoffs)

# Requirements Document

## Introduction

The AI Vendor Recommendation System (AI-VRS) is a new feature for the RetailFixIt platform that automates intelligent vendor selection for service jobs. RetailFixIt operates a multi-portal, event-driven platform coordinating service jobs between customers and a network of approximately 1,000 vendors.

The AI-VRS introduces a hybrid scoring engine that combines deterministic rule-based scoring with AI-generated rationale via Google Gemini 2.5 Flash. When a new job is created, the system automatically evaluates all eligible vendors against the job's requirements, ranks the top candidates, and presents human-readable explanations with confidence indicators to administrators. Administrators retain full override authority, and every AI decision is logged for compliance and future model improvement.

The system is built on AWS (Lambda, DynamoDB, S3, Cognito, EventBridge, SQS, API Gateway, CloudWatch, Secrets Manager) with a React + Vite frontend and Terraform-managed infrastructure.

---

## Glossary

- **AI-VRS**: AI Vendor Recommendation System — the system described in this document.
- **Admin**: An authenticated RetailFixIt administrator who uses the Admin UI to manage jobs, view recommendations, and apply overrides.
- **Vendor**: A service provider registered in the RetailFixIt network, described by a VendorProfile.
- **Job**: A service request created by a customer, described by a JobEvent.
- **Scoring_Engine**: The component that computes a ranked list of vendors for a given job using rule-based scoring and, when available, Gemini AI rationale.
- **Fallback_Scorer**: The rule-based scoring component that operates independently of the Gemini API, used when the AI service is unavailable or returns low-confidence results.
- **Recommendation**: A ranked vendor suggestion produced by the Scoring_Engine for a specific job, including score breakdown, confidence level, and rationale.
- **Override**: An Admin action that replaces the AI-recommended vendor with a manually selected vendor, recorded with a reason.
- **Audit_Logger**: The component responsible for recording every AI decision and override to DynamoDB and S3 with PII masking applied.
- **PII_Masker**: The component that detects and redacts personally identifiable information before writing to any log or audit record.
- **Confidence_Level**: A categorical assessment of recommendation reliability — one of High, Medium, or Low — derived from score distribution and AI response quality.
- **Model_Version**: A string identifier tracking the version of the scoring logic and AI prompt configuration used to produce a recommendation.
- **JobCreated_Event**: An EventBridge event published when a new job is created, which triggers the vendor scoring pipeline.
- **VendorRecommendationGenerated_Event**: An EventBridge event published after the Scoring_Engine produces a ranked vendor list for a job.
- **Dead_Letter_Queue (DLQ)**: An SQS queue that receives events that could not be processed after the maximum number of retries.
- **Cognito_Authorizer**: The AWS API Gateway authorizer that validates JWT tokens issued by AWS Cognito before allowing access to protected endpoints.
- **ScoreFactors**: The per-vendor breakdown of scoring dimensions (completion, availability, location, specialization, rework) that contribute to the total score.
- **AuditLog**: The DynamoDB table and S3 record storing every AI decision and override with full input/output context.
- **SLA**: Service Level Agreement — a deadline by which a job must be completed.
- **Gemini_Client**: The component that communicates with the Google Gemini 2.5 Flash API to generate human-readable rationale for recommendations.
- **VendorOverrideRecorded_Event**: An EventBridge event published when an Admin successfully submits a vendor override, containing the jobId, selected vendorId, and timestamp.
- **Seed_Data**: A set of pre-populated test VendorProfile and JobEvent records loaded into DynamoDB to enable system demonstration and testing without real production data.

---

## Requirements

### Requirement 1: Vendor Scoring Pipeline

**User Story:** As an Admin, I want the system to automatically score and rank vendors when a new job is created, so that I receive an ordered shortlist of the best-fit vendors without manual evaluation.

#### Acceptance Criteria

1. WHEN a `JobCreated_Event` is received by the Scoring_Engine, THE Scoring_Engine SHALL compute a ScoreFactors record for every vendor whose availability is not set to unavailable.
2. THE Scoring_Engine SHALL calculate each vendor's total score as a weighted composite of the following dimensions: completion rate, availability, rework rate, location proximity, specialization match, average response time, SLA breach count, and active job count.
3. WHEN scoring is complete, THE Scoring_Engine SHALL produce a ranked list of the top 5 vendors ordered by descending total score.
4. THE Scoring_Engine SHALL include the current Model_Version string in every ScoreFactors record it produces.
5. WHEN two vendors share an equal total score, THE Scoring_Engine SHALL rank the vendor with the lower active job count higher.
6. IF the vendor dataset contains fewer than 5 eligible vendors for a job, THEN THE Scoring_Engine SHALL return all eligible vendors in ranked order without padding the list.
7. THE Scoring_Engine SHALL complete the full scoring computation for a job within 10 seconds of receiving the `JobCreated_Event`, excluding Gemini API latency.

---

### Requirement 2: AI-Generated Rationale and Explainability

**User Story:** As an Admin, I want a plain-language explanation for each vendor recommendation, so that I can understand why a vendor was ranked at a given position and make an informed override decision.

#### Acceptance Criteria

1. WHEN the Scoring_Engine produces a ranked vendor list, THE Gemini_Client SHALL request a human-readable rationale for each of the top 5 vendors from the Google Gemini 2.5 Flash API.
2. THE Gemini_Client SHALL include the vendor's ScoreFactors, the job's type, location, urgency, and SLA deadline in the prompt sent to the Gemini API.
3. WHEN the Gemini API returns a rationale, THE Scoring_Engine SHALL attach the rationale text to the corresponding Recommendation record.
4. THE Scoring_Engine SHALL assign a Confidence_Level of High, Medium, or Low to each Recommendation based on the score distribution across ranked vendors and the AI response quality indicator returned by the Gemini API.
5. WHEN the Gemini API is unavailable or returns an error, THE Scoring_Engine SHALL assign a Confidence_Level of Low to all affected Recommendations and populate the rationale field with a system-generated explanation derived from the ScoreFactors alone.
6. WHEN the Gemini API response latency exceeds 8 seconds, THE Gemini_Client SHALL time out the request and THE Scoring_Engine SHALL fall back to rule-based rationale generation for that recommendation.
7. THE Scoring_Engine SHALL include the Model_Version in every Recommendation record regardless of whether the rationale was AI-generated or rule-based.

---

### Requirement 3: Fallback Scoring Mode

**User Story:** As an Admin, I want the system to continue producing vendor recommendations even when the Gemini AI service is unavailable, so that job dispatch is never blocked by an external API outage.

#### Acceptance Criteria

1. WHEN the Gemini API is unavailable, THE Fallback_Scorer SHALL produce a ranked vendor list using rule-based scoring alone, without calling the Gemini API.
2. WHEN the Fallback_Scorer is active, THE Admin_UI SHALL display a FallbackBanner indicating that AI-generated rationale is unavailable and recommendations are rule-based.
3. WHILE the Fallback_Scorer is active, THE Scoring_Engine SHALL continue to process all incoming `JobCreated_Event` messages without delay.
4. WHEN the Gemini API becomes available again, THE Scoring_Engine SHALL resume AI-assisted rationale generation for new jobs without requiring a system restart.
5. THE Fallback_Scorer SHALL produce ScoreFactors records that are structurally identical to those produced during normal AI-assisted operation, including the Model_Version field.

---

### Requirement 4: Event-Driven Integration

**User Story:** As a platform engineer, I want vendor scoring to be triggered automatically by job creation events and to publish its results as events, so that the system integrates cleanly with the existing event-driven architecture.

#### Acceptance Criteria

1. WHEN a job is created in the platform, THE Event_Bus SHALL publish a `JobCreated_Event` to the EventBridge rule that routes it to the vendor scoring SQS queue.
2. WHEN the Scoring_Engine successfully produces a ranked vendor list, THE Event_Bus SHALL publish a `VendorRecommendationGenerated_Event` containing the jobId, ranked vendor list, and Model_Version to EventBridge.
3. THE SQS queue SHALL be configured with a Dead_Letter_Queue that receives any `JobCreated_Event` message that fails processing after 3 retry attempts.
4. WHEN a message is moved to the Dead_Letter_Queue, THE Audit_Logger SHALL record the failed event with the jobId, failure reason, and timestamp.
5. THE `JobCreated_Event` payload SHALL conform to the JobEvent schema: jobId, type, location, urgency, slaDeadline, description, and createdAt fields.
6. THE `VendorRecommendationGenerated_Event` payload SHALL include the jobId, the ranked list of up to 5 vendor recommendations, the Model_Version, and a timestamp.
7. IF a `JobCreated_Event` message is malformed or missing required fields, THEN THE Scoring_Engine SHALL reject the message, publish the message to the Dead_Letter_Queue, and log the validation error via the Audit_Logger.

---

### Requirement 5: Human Override

**User Story:** As an Admin, I want to manually select a different vendor than the one recommended by the AI, so that I can apply domain knowledge or business context that the scoring model may not capture.

#### Acceptance Criteria

1. WHEN an Admin selects a vendor override on the Override page, THE Override_Handler SHALL record the override with the jobId, the originally recommended vendorId, the selected vendorId, the override reason text, and the Admin's userId.
2. THE Override_Handler SHALL store the override record in the DynamoDB AuditLog table and write a copy to the S3 override feedback bucket.
3. WHEN an override is submitted without a reason, THE Override_Handler SHALL reject the request and return a validation error indicating that a reason is required.
4. THE Override_Handler SHALL accept override reason text between 10 and 500 characters in length.
5. WHEN an override is successfully recorded, THE Override_Handler SHALL publish a `VendorOverrideRecorded_Event` to EventBridge containing the jobId, selected vendorId, and timestamp.
6. THE Override_Handler SHALL structure override records to include all fields required for future model retraining: jobId, original ranked list, selected vendorId, override reason, ScoreFactors for all ranked vendors, and timestamp.
7. WHEN an Admin attempts to override a job that already has a confirmed vendor assignment, THE Override_Handler SHALL reject the request and return an error indicating the job is no longer eligible for override.

---

### Requirement 6: Audit Logging

**User Story:** As a compliance officer, I want every AI decision and human override to be logged with full context, so that the system maintains a verifiable audit trail for regulatory review.

#### Acceptance Criteria

1. WHEN the Scoring_Engine produces a Recommendation, THE Audit_Logger SHALL write an AuditLog record containing: logId, jobId, vendorId (top-ranked), action ("AI_RECOMMENDATION"), input (ScoreFactors for all ranked vendors), output (ranked list with rationale and confidence), Model_Version, piiMasked flag set to true, and timestamp.
2. WHEN an Admin submits an override, THE Audit_Logger SHALL write an AuditLog record containing: logId, jobId, vendorId (selected), action ("ADMIN_OVERRIDE"), input (original recommendation), output (override selection), overrideReason, Model_Version, piiMasked flag set to true, and timestamp.
3. WHEN a Fallback_Scorer result is used, THE Audit_Logger SHALL write an AuditLog record with action ("FALLBACK_RECOMMENDATION") and include a flag indicating AI was unavailable.
4. THE PII_Masker SHALL redact all personally identifiable information from log inputs and outputs before THE Audit_Logger writes any record to DynamoDB or S3.
5. THE Audit_Logger SHALL write every AuditLog record to both the DynamoDB AuditLog table and the S3 logs bucket within 5 seconds of the triggering event.
6. THE Audit_Logger SHALL assign a unique logId to every AuditLog record using a UUID v4 format.
7. IF the DynamoDB write fails, THEN THE Audit_Logger SHALL retry the write up to 3 times with exponential backoff before logging the failure to CloudWatch and discarding the record.
8. THE Audit_Logger SHALL preserve the complete, unmasked input and output data in the S3 logs bucket using server-side encryption, accessible only to authorized IAM roles.

---

### Requirement 7: Authentication and Authorization

**User Story:** As a RetailFixIt administrator, I want to register and log in with my email and password, so that I can securely access the Admin UI and all protected API endpoints.

#### Acceptance Criteria

1. WHEN a new user submits a registration form with a valid email address and a password meeting complexity requirements, THE Cognito_User_Pool SHALL create a new user account and send an email verification link.
2. WHEN a user clicks the email verification link, THE Cognito_User_Pool SHALL mark the account as confirmed and allow the user to log in.
3. WHEN a confirmed user submits valid login credentials, THE Cognito_User_Pool SHALL issue a JWT access token and a refresh token.
4. THE Cognito_Authorizer SHALL reject any API Gateway request that does not include a valid, non-expired JWT access token in the Authorization header, returning HTTP 401.
5. WHEN a user's JWT access token expires, THE Auth_Service SHALL use the refresh token to obtain a new access token without requiring the user to re-enter credentials, provided the refresh token is still valid.
6. WHEN a new Cognito user account is confirmed, THE Post_Confirmation_Lambda SHALL create a corresponding user record in the DynamoDB Users table containing the userId, email, and account creation timestamp.
7. THE password complexity rule SHALL require a minimum of 8 characters, at least one uppercase letter, at least one lowercase letter, at least one digit, and at least one special character.
8. WHEN a user logs out, THE Auth_Service SHALL invalidate the current session tokens and redirect the user to the login page.

---

### Requirement 8: Admin UI — Core Layout and Navigation

**User Story:** As an Admin, I want a consistent navigation structure across all pages of the Admin UI, so that I can move between features efficiently without losing context.

#### Acceptance Criteria

1. THE Admin_UI SHALL render a persistent Header component on every page containing the RetailFixIt logo, the current page title, and a logout button.
2. THE Admin_UI SHALL render a persistent Sidebar component on every page containing navigation links to: Dashboard, Jobs, Recommendations, Override, and Audit Log.
3. THE Admin_UI SHALL render a persistent Footer component on every page.
4. WHEN an unauthenticated user navigates to any protected route, THE Admin_UI SHALL redirect the user to the login page via the ProtectedRoute component.
5. WHEN the Admin_UI is operating in Fallback_Scorer mode, THE Admin_UI SHALL display a FallbackBanner at the top of every page indicating that AI rationale is unavailable.
6. THE Admin_UI SHALL be responsive and render correctly on viewport widths from 1024px to 2560px.

---

### Requirement 9: Admin UI — Authentication Pages

**User Story:** As an Admin, I want a single login/register page with tab-based navigation, so that I can access both authentication flows from one location.

#### Acceptance Criteria

1. THE Admin_UI SHALL render a login/register page with two tabs: "Login" and "Register".
2. WHEN the Login tab is active, THE Admin_UI SHALL display the LoginForm component with email and password fields and a submit button.
3. WHEN the Register tab is active, THE Admin_UI SHALL display the RegisterForm component with email, password, and confirm-password fields and a submit button.
4. WHEN a login attempt fails due to invalid credentials, THE Admin_UI SHALL display an inline error message on the LoginForm without clearing the email field.
5. WHEN a registration attempt fails due to a duplicate email, THE Admin_UI SHALL display an inline error message on the RegisterForm indicating the email is already in use.
6. WHEN the password and confirm-password fields on the RegisterForm do not match, THE Admin_UI SHALL display an inline validation error and SHALL NOT submit the form.
7. WHEN a user successfully logs in, THE Admin_UI SHALL redirect the user to the Dashboard page.

---

### Requirement 10: Admin UI — Dashboard and Jobs Pages

**User Story:** As an Admin, I want a dashboard overview and a jobs list page, so that I can monitor platform activity and navigate to individual job details.

#### Acceptance Criteria

1. THE Dashboard page SHALL display summary metrics including: total jobs created today, total recommendations generated today, total overrides applied today, and the current AI service status (Active or Fallback).
2. THE Jobs page SHALL display a paginated list of all jobs, with each row showing: jobId, job type, location, urgency, SLA deadline, and current status.
3. WHEN an Admin clicks a job row on the Jobs page, THE Admin_UI SHALL navigate to the JobDetail view for that job.
4. THE JobDetail view SHALL display: jobId, job type, location, urgency, SLA deadline, description, creation timestamp, current status, and a link to the Recommendations page for that job.
5. THE Jobs page SHALL support filtering the job list by job status and by date range of creation.
5. WHEN the jobs list is loading, THE Admin_UI SHALL display a LoadingSpinner component in place of the job list.
6. IF the jobs API call returns an error, THEN THE Admin_UI SHALL display an ErrorBanner component with the error message and a retry button.

---

### Requirement 11: Admin UI — Recommendations Page

**User Story:** As an Admin, I want to view the ranked vendor recommendations for a job with rationale and confidence indicators, so that I can evaluate the AI's suggestions before deciding whether to accept or override them.

#### Acceptance Criteria

1. THE Recommendations page SHALL display the ranked list of up to 5 vendor recommendations for a selected job, ordered by descending total score.
2. FOR each recommendation, THE Recommendations page SHALL display: vendor name, total score, ScoreFactors breakdown, AI-generated rationale text in a RationaleBox component, and a ConfidenceBadge.
3. THE ConfidenceBadge SHALL render with distinct visual styling for each Confidence_Level: green for High, amber for Medium, and red for Low.
4. WHEN the recommendation was produced by the Fallback_Scorer, THE Recommendations page SHALL display a FallbackBanner above the vendor list indicating that rationale is rule-based.
5. WHEN an Admin clicks the "Override" button on the Recommendations page, THE Admin_UI SHALL navigate to the Override page pre-populated with the current jobId.
6. WHEN an Admin clicks the "Accept" button on the Recommendations page, THE Admin_UI SHALL call the accept API endpoint and record the acceptance in the AuditLog with action type "AI_RECOMMENDATION_ACCEPTED".
7. WHEN recommendations are loading, THE Admin_UI SHALL display a LoadingSpinner in place of the vendor list.

---

### Requirement 12: Admin UI — Override Page

**User Story:** As an Admin, I want to select a different vendor and record my reason, so that my override decision is captured for compliance and future model improvement.

#### Acceptance Criteria

1. THE Override page SHALL display the current AI-recommended vendor list for the selected job alongside a vendor selection control listing all eligible vendors.
2. WHEN an Admin selects a vendor from the selection control, THE OverridePanel component SHALL display the selected vendor's profile summary.
3. THE OverridePanel SHALL include a required text area for the override reason, with a character counter showing remaining characters up to the 500-character limit.
4. WHEN an Admin submits the override form with a valid vendor selection and reason, THE Admin_UI SHALL call the override API endpoint and display a success confirmation message.
5. WHEN the override API call fails, THE Admin_UI SHALL display an ErrorBanner with the failure reason and preserve the form state so the Admin can retry.
6. WHEN an override is successfully submitted, THE Admin_UI SHALL update the job's displayed status to "Vendor Assigned — Override".

---

### Requirement 13: Admin UI — Audit Log Page

**User Story:** As a compliance officer, I want to view a searchable audit log of all AI decisions and overrides, so that I can investigate specific events and demonstrate compliance.

#### Acceptance Criteria

1. THE Audit Log page SHALL display a paginated list of AuditLog records ordered by descending timestamp.
2. FOR each AuditLog record, THE Audit Log page SHALL display: logId, jobId, action type, vendorId, Confidence_Level (for AI recommendations), Model_Version, piiMasked status, and timestamp.
3. THE Audit Log page SHALL support filtering records by action type (AI_RECOMMENDATION, ADMIN_OVERRIDE, FALLBACK_RECOMMENDATION, AI_RECOMMENDATION_ACCEPTED) and by date range.
4. THE Audit Log page SHALL support searching records by jobId or vendorId.
5. WHEN an Admin clicks an AuditLog record, THE Admin_UI SHALL display a detail panel showing the full input and output fields for that record.
6. WHEN the audit log is loading, THE Admin_UI SHALL display a LoadingSpinner in place of the log list.

---

### Requirement 14: Model Versioning

**User Story:** As a platform engineer, I want every recommendation to reference the scoring model version that produced it, so that I can trace decisions to a specific model configuration and manage model updates safely.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL read the current Model_Version string from S3 at startup and cache it in memory for the duration of the Lambda invocation.
2. THE Scoring_Engine SHALL include the Model_Version in every ScoreFactors record, every Recommendation record, and every AuditLog record it produces.
3. WHEN the Model_Version value in S3 is updated, THE Scoring_Engine SHALL use the updated version on the next Lambda cold start without requiring a code deployment.
4. THE Model_Version string SHALL follow semantic versioning format (MAJOR.MINOR.PATCH) and SHALL be stored in a dedicated S3 object in the Lambda zip bucket.
5. WHEN two AuditLog records reference the same jobId but different Model_Version values, THE Audit_Logger SHALL preserve both records without overwriting either.

---

### Requirement 15: Infrastructure and Operational Constraints

**User Story:** As a platform engineer, I want the AI-VRS infrastructure to be fully defined in Terraform and to enforce cost, reliability, and security controls, so that the system is reproducible, observable, and safe to operate.

#### Acceptance Criteria

1. THE Terraform configuration SHALL define all infrastructure resources: Lambda function, DynamoDB tables (Jobs, Vendors, Recommendations, AuditLog, Users), S3 buckets (Lambda zip, logs, override feedback), Cognito User Pool and App Client, API Gateway with Cognito Authorizer and CORS, EventBridge rules, SQS queue and Dead_Letter_Queue, Secrets Manager reference, and CloudWatch log groups.
2. THE Lambda function SHALL be configured with a reserved concurrency limit to prevent unbounded scaling and cost overruns.
3. THE Lambda function SHALL be assigned an IAM execution role with least-privilege permissions scoped to: DynamoDB read/write on all AI-VRS tables, S3 read/write on all AI-VRS buckets, Secrets Manager read on the Gemini API key secret, EventBridge publish on AI-VRS event rules, SQS consume on the vendor scoring queue, and CloudWatch Logs write.
4. THE Lambda function SHALL retrieve the Gemini API key exclusively from AWS Secrets Manager at runtime; the key SHALL NOT be stored in environment variables or source code.
4. THE API Gateway SHALL enforce CORS with an explicit list of allowed origins; wildcard origins SHALL NOT be permitted in production.
5. THE DynamoDB tables SHALL use on-demand billing mode to accommodate variable traffic without pre-provisioning capacity.
6. THE S3 buckets storing audit logs and override feedback SHALL have server-side encryption enabled using AWS-managed keys.
7. THE CloudWatch log groups SHALL have a retention policy of 90 days for Lambda function logs and 365 days for audit log exports.
8. THE Terraform configuration SHALL expose output values for: API Gateway endpoint URL, Cognito User Pool ID, Cognito App Client ID, SQS queue URL, and Dead_Letter_Queue URL.

---

### Requirement 16: AI Governance — Authority and Risk Boundaries

**User Story:** As a RetailFixIt product owner, I want clear boundaries on what the AI system can decide autonomously versus what requires human approval, so that high-risk dispatch decisions are never made without human oversight.

#### Acceptance Criteria

1. THE AI-VRS SHALL operate in an advisory capacity only; THE Scoring_Engine SHALL produce recommendations but SHALL NOT automatically assign a vendor to a job without Admin confirmation.
2. WHEN a job has an urgency level of "Critical" or an SLA deadline within 2 hours of the `JobCreated_Event` timestamp, THE Admin_UI SHALL display a prominent warning requiring explicit Admin acknowledgment before the recommendation is accepted.
3. THE Admin_UI SHALL display the Confidence_Level for every recommendation; WHEN the Confidence_Level is Low, THE Admin_UI SHALL display an additional advisory message recommending manual review before acceptance.
4. THE Scoring_Engine SHALL NOT use vendor pricing, vendor demographic attributes, or customer identity as scoring dimensions.
5. WHEN an Admin accepts a recommendation without modification, THE Override_Handler SHALL record the acceptance action in the AuditLog with action type "AI_RECOMMENDATION_ACCEPTED" to maintain a complete decision trail.

---

### Requirement 17: Model Drift Detection and Feedback Loop

**User Story:** As a data engineer, I want override data to be structured for retraining and drift to be detectable from audit data, so that the scoring model can be improved over time based on real dispatch outcomes.

#### Acceptance Criteria

1. THE Override_Handler SHALL store override records in the S3 override feedback bucket in a schema that includes all fields required for supervised retraining: jobId, original ranked list with ScoreFactors, selected vendorId, override reason, and timestamp.
2. THE Audit_Logger SHALL record the Confidence_Level distribution across all recommendations produced in a 24-hour window as a CloudWatch metric named `RecommendationConfidenceDistribution`.
3. WHEN the proportion of Low-confidence recommendations in a 24-hour window exceeds 30%, THE Scoring_Engine SHALL publish a CloudWatch alarm named `HighLowConfidenceRate` to alert the operations team.
4. WHEN the override rate for AI recommendations in a 7-day window exceeds 40%, THE Scoring_Engine SHALL publish a CloudWatch alarm named `HighOverrideRate` to alert the operations team.
5. THE S3 override feedback bucket SHALL be partitioned by year/month/day to support efficient batch export for retraining pipelines.

---

### Requirement 18: Data Quality and Event Instrumentation

**User Story:** As a platform engineer, I want all critical events to carry validated, complete payloads, so that the scoring pipeline never operates on incomplete or corrupt data.

#### Acceptance Criteria

1. WHEN the Scoring_Engine receives a `JobCreated_Event`, THE Scoring_Engine SHALL validate that all required JobEvent fields are present and non-null: jobId, type, location, urgency, slaDeadline, description, and createdAt.
2. WHEN the Scoring_Engine retrieves a VendorProfile from DynamoDB, THE Scoring_Engine SHALL validate that all required VendorProfile fields are present: vendorId, name, completionRate, availability, reworkRate, location, specializations, avgResponseTime, slaBreachCount, and activeJobs.
3. IF a VendorProfile is missing one or more required fields, THEN THE Scoring_Engine SHALL exclude that vendor from scoring and log a data quality warning to CloudWatch with the vendorId and missing field names.
4. THE Scoring_Engine SHALL publish a CloudWatch metric named `VendorProfileDataQualityErrors` incremented by 1 for each vendor excluded due to missing fields.
5. THE Event_Bus SHALL include a schema version field in all `JobCreated_Event` and `VendorRecommendationGenerated_Event` payloads to support forward-compatible schema evolution.

---

### Requirement 19: Failure Modes and Resilience

**User Story:** As a platform engineer, I want the system to handle AI service failures, slow responses, and low-confidence results gracefully, so that job dispatch is never blocked and Admins are always informed of degraded operation.

#### Acceptance Criteria

1. WHEN the Gemini API returns an HTTP 5xx error, THE Gemini_Client SHALL retry the request up to 2 times with exponential backoff before activating the Fallback_Scorer for that job.
2. WHEN the Gemini API returns an HTTP 4xx error (excluding 429), THE Gemini_Client SHALL NOT retry the request and SHALL immediately activate the Fallback_Scorer for that job.
3. WHEN the Gemini API returns HTTP 429 (rate limit), THE Gemini_Client SHALL wait for the duration specified in the Retry-After response header before retrying, up to a maximum wait of 30 seconds, after which THE Fallback_Scorer SHALL be activated.
4. WHEN the Scoring_Engine produces a recommendation with all vendors at Low confidence, THE Admin_UI SHALL display a warning message on the Recommendations page advising the Admin to verify vendor availability manually.
5. WHEN a Lambda invocation exceeds its configured timeout, THE SQS queue SHALL make the unprocessed `JobCreated_Event` message visible again for reprocessing, up to the maximum retry count before routing to the Dead_Letter_Queue.
6. THE Scoring_Engine SHALL emit a CloudWatch metric named `FallbackScorerActivations` incremented by 1 each time the Fallback_Scorer is used in place of AI-assisted scoring.
7. IF the DynamoDB Vendors table returns zero eligible vendors for a job, THEN THE Scoring_Engine SHALL publish a `NoEligibleVendors_Event` to EventBridge and log a warning to CloudWatch with the jobId.

---

### Requirement 20: Seed Data and Initial Vendor Dataset

**User Story:** As a developer, I want the system to ship with realistic test vendor and job data, so that the scoring engine can be demonstrated and tested without requiring real production data.

#### Acceptance Criteria

1. THE system SHALL include a `seed_data.py` script that populates the DynamoDB Vendors table with at least 10 realistic VendorProfile records covering a range of completion rates, availability states, specializations, and locations.
2. THE seed script SHALL populate the DynamoDB Jobs table with at least 5 realistic JobEvent records covering different job types, urgency levels, and SLA deadlines.
3. EACH seeded VendorProfile SHALL include all required fields: vendorId, name, completionRate, availability, reworkRate, location, specializations, avgResponseTime, slaBreachCount, and activeJobs.
4. THE seed script SHALL be idempotent — running it multiple times SHALL NOT create duplicate records.
5. THE seed script SHALL be documented in the README with instructions for running it before first use.

---

### Requirement 21: Deployment and Documentation Deliverables

**User Story:** As a developer, I want a single deployment script and complete documentation, so that the system can be deployed to AWS and evaluated end-to-end without manual steps.

#### Acceptance Criteria

1. THE system SHALL include a `deploy.sh` script that packages the Lambda function into a zip file and runs `terraform apply` to deploy all AWS infrastructure in a single command.
2. THE README SHALL include the following sections: system overview, AI approach and assumptions, how explainability is generated via Gemini 2.5 Flash, how human override feedback would be used to retrain the scoring model, and known limitations and next steps.
3. THE system SHALL include a `docs/governance_answers.md` file containing written answers to all four Part 3 governance questions: AI Authority and Risk, Model Drift and Feedback, Data Quality and Events, and Failure Modes.
4. THE `docs/architecture.md` file SHALL include a high-level description of all AWS services used, how they connect, and where AI decisions are advisory versus automated.
5. THE deploy script SHALL print the API Gateway endpoint URL, Cognito User Pool ID, and Cognito App Client ID after a successful deployment using Terraform output values.
6. THE system SHALL include an `events/` directory containing sample JSON payloads for: `job_created.json` (JobCreated_Event), `vendor_recommendation.json` (VendorRecommendationGenerated_Event), and example API request/response pairs for the recommend, override, query, and accept endpoints.
7. THE `.gitignore` SHALL exclude: Terraform state files, `terraform.tfvars`, Lambda zip files, Python virtual environments, Node modules, `.env` files, and AWS credential files.

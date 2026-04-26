# AI Governance — Questions and Answers

## 1. AI Authority & Risk Boundaries

**Q: What decisions can the AI make autonomously, and what requires human approval?**

The AI-VRS operates in a strictly advisory capacity. It produces ranked vendor recommendations but **never automatically assigns a vendor to a job**. Every assignment requires explicit Admin confirmation via the Accept button in the Admin UI.

**High-risk job handling:**
- When a job has `urgency == "Critical"` or an SLA deadline within 2 hours of creation, the Admin UI displays a prominent `CriticalJobWarning` component requiring explicit checkbox acknowledgment before the Accept button is enabled.
- When `confidence == "Low"`, the UI displays an additional advisory message recommending manual review before acceptance.

**Prohibited scoring factors:**
The scoring engine must never use vendor pricing, vendor demographic attributes, or customer identity as scoring dimensions. The 8 permitted dimensions are: completion rate, availability, rework rate, location proximity, specialization match, average response time, SLA breach count, and active job count.

**Audit trail:**
Every acceptance (with or without override) is recorded in the AuditLog with `action="AI_RECOMMENDATION_ACCEPTED"` or `action="ADMIN_OVERRIDE"`, maintaining a complete decision trail for compliance review.

---

## 2. Model Drift Detection & Feedback Loop

**Q: How is model drift detected and how does override data feed back into the model?**

**Drift detection alarms:**
- `HighLowConfidenceRate` — triggers when the proportion of Low-confidence recommendations in a 24-hour window exceeds 30%. Published as a CloudWatch alarm with SNS notification.
- `HighOverrideRate` — triggers when the override rate for AI recommendations in a 7-day window exceeds 40%. Published as a CloudWatch alarm with SNS notification.
- `FallbackScorerActivations` — triggers when fallback activations exceed 10 in a 1-hour period.

**Override feedback storage:**
Every override is written to `s3://ai-vrs-override-feedback/year={YYYY}/month={MM}/day={DD}/{jobId}_{timestamp}.json` with the full retraining schema:
- `jobId`, `selectedVendorId`, `overrideReason`, `userId`, `timestamp`
- `originalRankedList` — complete ScoreFactors for all ranked vendors

**Retraining safeguards:**
1. **Shadow mode** — new model weights run in parallel without affecting production output
2. **A/B testing** — gradual traffic split between old and new weights
3. **Gradual rollout** — new weights deployed to 10% → 50% → 100% of traffic
4. **Rollback** — revert `model-version.txt` in S3 to previous version; takes effect on next Lambda cold start

---

## 3. Data Quality & Event Instrumentation

**Q: How does the system ensure data quality and event schema consistency?**

**JobCreated_Event validation:**
Every `JobCreated_Event` message is validated by `utils/validator.validate_job_event()` before scoring begins. Required fields: `jobId`, `type`, `location`, `urgency`, `slaDeadline`, `description`, `createdAt`. Malformed messages are routed to the DLQ after 3 retries, and `audit_logger.log_dlq_failure()` records the failure.

**VendorProfile validation:**
Every VendorProfile retrieved from DynamoDB is validated by `utils/validator.validate_vendor_profile()`. Vendors with missing required fields are excluded from scoring, and a `VendorProfileDataQualityErrors` CloudWatch metric is incremented per excluded vendor.

**Schema versioning:**
All `JobCreated_Event` and `VendorRecommendationGenerated_Event` payloads include a `schemaVersion` field (currently `"1.0"`) to support forward-compatible schema evolution without breaking existing consumers.

**Dead Letter Queue:**
The SQS vendor-scoring-queue is configured with a DLQ (`ai-vrs-vendor-scoring-dlq`) that receives messages after 3 failed processing attempts. DLQ messages are retained for 14 days for investigation.

---

## 4. Failure Modes & Resilience

**Q: How does the system handle AI service failures, slow responses, and low-confidence results?**

| Failure Mode | System Response | Admin Impact |
|---|---|---|
| Gemini API unavailable (5xx) | Retry 2x with exponential backoff; fall back to rule-based rationale | FallbackBanner shown in UI; `isAIGenerated=False` on recommendations |
| Gemini API slow (>8s) | Request times out; fall back to rule-based rationale | Same as above |
| Gemini API rate-limited (429) | Respect `Retry-After` header (max 30s); retry once | Brief delay; fallback if retry fails |
| Low confidence score | UI displays advisory message recommending manual review | Admin must consciously choose to accept |
| Lambda timeout | SQS reprocesses message up to 3x; then routes to DLQ | `log_dlq_failure()` records the event; no vendor assigned |
| No eligible vendors | `NoEligibleVendors_Event` published to EventBridge; SNS alert sent | Admin notified; no recommendations generated |
| DynamoDB write failure | Retry 3x with exponential backoff; log to CloudWatch after exhaustion | Audit record may be missing; CloudWatch alarm fires |
| Invalid JobEvent payload | Validation error logged; message sent to DLQ | `log_dlq_failure()` records the failure |

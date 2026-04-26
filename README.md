# AI Vendor Recommendation System (AI-VRS)

## System Overview

AI-VRS automates intelligent vendor selection for service jobs on the RetailFixIt platform. When a new job is created, the system evaluates all eligible vendors, ranks the top 5 candidates using a hybrid scoring engine, and presents human-readable explanations with confidence indicators to administrators.

**Key AWS services:** Lambda, DynamoDB, S3, Cognito, EventBridge, SQS, API Gateway, CloudWatch, Secrets Manager

**Advisory-only AI principle:** The system never automatically assigns a vendor. Every recommendation requires explicit Admin confirmation. Admins retain full override authority at all times.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full architecture diagram, AWS services table, and event flow descriptions.

## AI Approach and Assumptions

### Hybrid Scoring Engine

Each vendor is scored across 8 dimensions, then ranked by weighted total score:

| Dimension | Weight | Notes |
|---|---|---|
| Completion Rate | 25% | Historical job completion rate |
| Availability | 20% | available=1.0, busy=0.5, unavailable=0.0 |
| Rework Rate | 15% | Inverted (lower rework = higher score) |
| Location Proximity | 15% | Exact match=1.0, same region=0.5, other=0.0 |
| Specialization Match | 10% | Binary: job type in vendor specializations |
| Avg Response Time | 8% | Capped at 24h (score=0 for 24h+) |
| SLA Breach Count | 4% | Capped at 10 breaches (score=0 for 10+) |
| Active Jobs | 3% | Capped at 20 jobs (score=0 for 20+) |

### Gemini 2.5 Flash Rationale

For each top-5 vendor, the system calls the Google Gemini 2.5 Flash API with a structured prompt containing the vendor's ScoreFactors and job context. The API returns a 2–3 sentence plain-language explanation and a confidence indicator (HIGH/MEDIUM/LOW).

### Fallback Mode

When Gemini is unavailable or times out (>8s), the system falls back to rule-based rationale generation. The Admin UI displays a FallbackBanner. Job dispatch is never blocked.

### Key Assumptions

1. Vendor profiles are pre-loaded in DynamoDB before jobs are created
2. Location matching uses US state abbreviation extraction (e.g. "TX") — not geocoding
3. All scoring dimensions are equally applicable across all job types
4. The Gemini API key is pre-provisioned in AWS Secrets Manager
5. A single Lambda function handles all event sources (API Gateway, SQS, Cognito, EventBridge)
6. DynamoDB on-demand billing is sufficient for expected traffic volumes
7. Admins are authenticated via Cognito; no role-based access control beyond authentication
8. Override feedback is stored for future retraining but no automated retraining pipeline exists yet

## Explainability

### How Rationale is Generated

The Gemini prompt includes the vendor's 8 normalized dimension scores (0.0–1.0), the job type, location, urgency, SLA deadline, and description. Gemini returns a 2–3 sentence explanation focusing on the highest-contributing dimensions.

### Confidence Calculation

After ranking, confidence is determined by score distribution:
- **High**: top score > 0.75 AND gap to #2 > 0.10
- **Low**: top score < 0.50 OR all scores within 0.05 of each other
- **Medium**: everything else
- Downgraded to Low if Gemini returns a LOW quality indicator

## Feedback Loop and Model Retraining

### Override Feedback Schema (S3)

Every override is stored at `s3://ai-vrs-override-feedback/year={YYYY}/month={MM}/day={DD}/{jobId}_{timestamp}.json` with:
- `jobId`, `selectedVendorId`, `overrideReason`, `userId`, `timestamp`
- `originalRankedList` — full ScoreFactors for all ranked vendors

### Conceptual Retraining Pipeline

1. Export override feedback from S3 (partitioned by date)
2. Join with job outcomes (completion, rework, SLA adherence)
3. Retrain scoring weights using supervised learning
4. Shadow-test new weights against production traffic
5. Gradual rollout with A/B testing
6. Update `model-version.txt` in S3 to trigger new version on next Lambda cold start

## Deployment

### Prerequisites

1. AWS CLI configured with appropriate permissions
2. Terraform >= 1.5 installed
3. `jq` installed (for output parsing in deploy.sh)
4. S3 bucket `retailfixit-terraform-state` exists (for Terraform state)
5. Gemini API key stored in AWS Secrets Manager as `ai-vrs/gemini-api-key`

### Quick Start

```bash
# 1. Deploy infrastructure and Lambda
./scripts/deploy.sh

# 2. Seed DynamoDB with test data
python scripts/seed_data.py --vendors 10 --jobs 5

# 3. Start frontend
cd frontend && npm install && npm run dev
```

### Manual Deployment Steps

```bash
# Package Lambda
cd backend/lambda && zip -r ../../infra/terraform/lambda.zip . -x "*.pyc" -x "__pycache__/*"

# Upload to S3
aws s3 cp infra/terraform/lambda.zip s3://ai-vrs-lambda-zip/lambda.zip
echo -n "1.0.0" | aws s3 cp - s3://ai-vrs-lambda-zip/model-version.txt

# Deploy infrastructure
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform apply -var="allowed_cors_origin=https://your-frontend-domain.com"
```

## Development

### Backend

```bash
# Install dependencies
pip install -r backend/lambda/requirements.txt

# Run tests
pytest tests/ -v

# Run specific test file
pytest tests/test_utils_validator.py -v
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # Development server
npm run build    # Production build
```

### Infrastructure

```bash
cd infra/terraform
terraform init
terraform plan -var="allowed_cors_origin=http://localhost:5173"
terraform validate
terraform fmt
```

## Testing

### Unit Tests

Located in `tests/`. Run with `pytest tests/ -v`. Covers:
- `test_utils_logger.py` — structured JSON logger (19 tests)
- `test_utils_validator.py` — input validation (47 tests)
- `test_utils_model_version.py` — S3-backed model version cache (22 tests)
- `test_vendor_scoring.py` — scoring normalization and confidence logic
- `test_override_handler.py` — override validation and HTTP responses
- `test_audit_logger.py` — dual-write audit logging with retry
- `test_pii_masker.py` — PII redaction correctness

### Property-Based Tests

Located in `tests/test_scoring_properties.py`. Uses the Hypothesis library to verify 10 correctness properties:

1. **Score Bounds** — totalScore always in [0.0, 1.0]
2. **Ranking Consistency** — ranked list always sorted descending
3. **Unavailable Vendor Exclusion** — no unavailable vendors in output
4. **Ranked List Size Bound** — 0–5 vendors in output
5. **Model Version Propagation** — all records carry same modelVersion
6. **Tie-Breaking Determinism** — same input → same ranked order
7. **Fallback Structural Equivalence** — fallback output matches AI output structure
8. **Confidence Level Validity** — confidence always High/Medium/Low
9. **Override Reason Length** — ValidationError for len < 10 or len > 500
10. **Audit Log PII Masking** — no PII in DynamoDB records

### Integration Test Scenarios

1. Create job → verify JobCreated_Event published to EventBridge
2. SQS message → verify vendor scoring pipeline completes within 10s
3. Accept recommendation → verify AuditLog record with AI_RECOMMENDATION_ACCEPTED
4. Submit override → verify S3 feedback record + EventBridge event + job status update
5. Gemini unavailable → verify fallback rationale + FallbackBanner in UI

## Known Limitations and Next Steps

### Limitations

1. **Location matching** uses state abbreviation extraction only — not geocoding or distance calculation
2. **No automated retraining pipeline** — override feedback is collected but model weights are static
3. **Gemini dependency** — fallback mode produces lower-quality rationale; no alternative AI provider
4. **Single region** — no multi-region failover or disaster recovery
5. **DynamoDB scan scale** — vendor scoring uses full table scan; will degrade at ~10,000+ vendors

### Next Steps

1. Implement geocoding-based location scoring using AWS Location Service
2. Build automated retraining pipeline using SageMaker and the S3 override feedback
3. Add multi-provider AI fallback (e.g. Claude, GPT-4) for higher availability
4. Implement multi-region active-active deployment with DynamoDB Global Tables
5. Replace DynamoDB scan with GSI-based query for vendor scoring at scale
6. Add role-based access control (RBAC) to distinguish read-only vs. override-capable admins

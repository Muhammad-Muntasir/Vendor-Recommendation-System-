# Architecture — AI Vendor Recommendation System (AI-VRS)

## High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RetailFixIt Admin UI                               │
│                    (React 18 + Vite, React Router v6)                       │
│  AuthPage  Dashboard  JobsPage  RecommendationsPage  OverridePage  AuditLog │
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
│                    AWS Lambda (Single Function — ai-vrs)                    │
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
│  ai-vrs-jobs         │    │  JobCreated rule → SQS → Lambda                  │
│  ai-vrs-vendors      │    │  VendorRecommendationGenerated rule              │
│  ai-vrs-recommendations│  │  VendorOverrideRecorded rule                     │
│  ai-vrs-audit-log    │    │  NoEligibleVendors rule → SNS                    │
│  ai-vrs-users        │    └──────────────────────────────────────────────────┘
└──────────────────────┘                        │
                                                ▼
┌──────────────────────┐    ┌──────────────────────────────────────────────────┐
│      AWS S3          │    │                 AWS SQS                          │
│  ai-vrs-lambda-zip   │    │  ai-vrs-vendor-scoring-queue (main)              │
│  ai-vrs-logs (enc.)  │    │  ai-vrs-vendor-scoring-dlq (Dead Letter Queue)   │
│  ai-vrs-override-    │    └──────────────────────────────────────────────────┘
│    feedback          │
│  model-version.txt   │
└──────────────────────┘
┌──────────────────────┐    ┌──────────────────────────────────────────────────┐
│  AWS Secrets Manager │    │              AWS Cognito                         │
│  gemini-api-key      │    │  User Pool (self-registration + email verify)    │
└──────────────────────┘    │  App Client (JWT issuance, no client secret)     │
                            │  Post-Confirmation Lambda trigger                │
                            └──────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────────┐
│                         AWS CloudWatch                                       │
│  /aws/lambda/ai-vrs (90d)   /ai-vrs/audit-log-exports (365d)               │
│  Alarms: HighLowConfidenceRate, HighOverrideRate, FallbackScorerActivations  │
│  Metrics: VendorProfileDataQualityErrors, RecommendationConfidenceDistrib.   │
└──────────────────────────────────────────────────────────────────────────────┘
```

## AWS Services Table

| Service | Purpose | Key Configuration |
|---|---|---|
| **Lambda** | Single function handling all events | Python 3.12, 512MB, 25s timeout, reserved concurrency=10 |
| **DynamoDB** | Persistent storage for all entities | 5 tables, on-demand billing, PITR enabled |
| **S3** | Lambda zip, audit logs, override feedback | SSE-S3 encryption, versioning on lambda-zip bucket |
| **API Gateway** | REST API with JWT auth | Cognito Authorizer, CORS with explicit origin |
| **Cognito** | User authentication | Self-registration, email verification, JWT tokens |
| **EventBridge** | Event routing | 4 rules: JobCreated, RecommendationGenerated, OverrideRecorded, NoEligibleVendors |
| **SQS** | Reliable job event delivery | Visibility timeout 30s, DLQ after 3 retries |
| **Secrets Manager** | Gemini API key storage | Data source only — key pre-provisioned manually |
| **CloudWatch** | Observability | Log groups (90d/365d), 3 alarms, 2 metric filters |

## Event Flow: Job Created → Recommendation Generated

```
Admin UI
  │ POST /jobs
  ▼
API Gateway → Lambda (query.py)
  │ Creates job in DynamoDB
  │ Publishes JobCreated_Event to EventBridge
  ▼
EventBridge (JobCreated rule)
  ▼
SQS (ai-vrs-vendor-scoring-queue)
  │ Lambda triggered by SQS message
  ▼
Lambda → router.py → job_created.py
  │
  ├─→ vendor_scoring.py
  │     Scans all VendorProfiles from DynamoDB
  │     Validates each profile (excludes invalid, emits VendorProfileDataQualityErrors)
  │     Filters out unavailable vendors
  │     Computes ScoreFactors for each eligible vendor
  │     Ranks top 5 by totalScore (tie-break: activeJobs, vendorId)
  │     Computes Confidence_Level from score distribution
  │
  ├─→ recommendation.py
  │     For each top-5 vendor:
  │       Calls Gemini 2.5 Flash API (8s timeout)
  │       Falls back to fallback_scorer on failure
  │     Assembles Recommendation records
  │     Writes to DynamoDB ai-vrs-recommendations
  │     Emits FallbackScorerActivations metric if fallback used
  │
  ├─→ audit_logger.py
  │     Masks PII via pii_masker.py
  │     Writes AuditLog to DynamoDB (3x retry with backoff)
  │     Writes unmasked record to S3 (SSE-S3)
  │     Emits RecommendationConfidenceDistribution metric
  │
  └─→ EventBridge: publishes VendorRecommendationGenerated_Event
```

## Component Interactions

```
handler.py
    └── router.py
            ├── handlers/job_created.py
            │       ├── utils/validator.py
            │       ├── handlers/vendor_scoring.py
            │       │       ├── services/dynamodb.py
            │       │       ├── utils/validator.py
            │       │       └── utils/model_version.py
            │       ├── handlers/recommendation.py
            │       │       ├── services/ai_client.py
            │       │       │       └── services/secrets.py
            │       │       ├── services/fallback_scorer.py
            │       │       └── services/dynamodb.py
            │       └── services/audit_logger.py
            │               ├── services/pii_masker.py
            │               ├── services/dynamodb.py
            │               └── services/s3.py
            ├── handlers/query.py
            │       ├── services/dynamodb.py
            │       └── services/audit_logger.py
            ├── handlers/override.py
            │       ├── utils/validator.py
            │       ├── services/dynamodb.py
            │       ├── services/s3.py
            │       └── services/audit_logger.py
            └── handlers/auth.py
                    └── services/dynamodb.py
```

## Advisory vs Automated Decisions

| Decision | Who Makes It | System Role |
|---|---|---|
| Vendor ranking | AI scoring engine | Automated — deterministic algorithm |
| Rationale generation | Gemini 2.5 Flash | Automated — AI-generated text |
| Vendor assignment | Admin | Human required — system only suggests |
| Override | Admin | Human required — system records and stores |
| Fallback activation | System | Automated — triggered by Gemini failure |
| DLQ routing | SQS | Automated — after 3 failed retries |
| Alarm triggering | CloudWatch | Automated — threshold-based |

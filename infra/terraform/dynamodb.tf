###############################################################################
# dynamodb.tf — All 5 DynamoDB tables for the AI Vendor Recommendation System
#
# All tables use:
#   billing_mode = "PAY_PER_REQUEST" — no capacity planning needed, scales
#                                      automatically with traffic (Req 15.5)
#   point_in_time_recovery           — enables restore to any point in the
#                                      last 35 days for disaster recovery
#
# GSI (Global Secondary Index) design:
#   Each table has GSIs to support the query patterns used by the API.
#   GSIs allow querying by non-primary-key attributes efficiently.
###############################################################################

# ── Jobs table ────────────────────────────────────────────────────────────────
# Primary key: jobId (partition key only — each job has a unique ID)
# GSIs:
#   status-createdAt-index — supports GET /jobs?status=Pending (filter by status)
#   createdAt-index        — supports date range queries for dashboard metrics
resource "aws_dynamodb_table" "jobs" {
  name         = "ai-vrs-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "jobId"  # Partition key — UUID v4

  # Attributes must be declared for any key used in the table or GSIs
  attribute {
    name = "jobId"
    type = "S"  # String
  }
  attribute {
    name = "status"
    type = "S"  # "Pending", "Recommended", "Assigned", "Override"
  }
  attribute {
    name = "createdAt"
    type = "S"  # ISO 8601 string — lexicographic sort works for date ranges
  }

  # GSI: query jobs by status, sorted by creation time
  # Used by: GET /jobs?status=Pending, dashboard metrics
  global_secondary_index {
    name            = "status-createdAt-index"
    hash_key        = "status"
    range_key       = "createdAt"
    projection_type = "ALL"  # Include all attributes in the index
  }

  # GSI: query jobs by creation date prefix
  # Used by: dashboard metrics (totalJobsToday)
  global_secondary_index {
    name            = "createdAt-index"
    hash_key        = "createdAt"
    range_key       = "jobId"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "ai-vrs-jobs" }
}

# ── Vendors table ─────────────────────────────────────────────────────────────
# Primary key: vendorId
# GSI: availability-index — supports filtering by availability status
# Note: The scoring engine currently uses a full table scan (scan() in dynamodb.py)
# because it needs ALL vendors to score. The GSI is available for future
# optimisation to query only available/busy vendors.
resource "aws_dynamodb_table" "vendors" {
  name         = "ai-vrs-vendors"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "vendorId"

  attribute {
    name = "vendorId"
    type = "S"
  }
  attribute {
    name = "availability"
    type = "S"  # "available", "busy", "unavailable"
  }

  # GSI: query vendors by availability
  # Future use: replace full table scan with targeted query for available vendors
  global_secondary_index {
    name            = "availability-index"
    hash_key        = "availability"
    range_key       = "vendorId"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "ai-vrs-vendors" }
}

# ── Recommendations table ─────────────────────────────────────────────────────
# Primary key: jobId (partition) + rank (sort)
# This composite key allows querying all recommendations for a job in rank order
# with a single Query call: Key("jobId").eq(jobId)
resource "aws_dynamodb_table" "recommendations" {
  name         = "ai-vrs-recommendations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "jobId"
  range_key    = "rank"  # Sort key: 1, 2, 3, 4, 5

  attribute {
    name = "jobId"
    type = "S"
  }
  attribute {
    name = "rank"
    type = "N"  # Number — rank position (1-5)
  }
  attribute {
    name = "vendorId"
    type = "S"
  }
  attribute {
    name = "timestamp"
    type = "S"
  }
  attribute {
    name = "modelVersion"
    type = "S"
  }

  # GSI: query recommendations by vendor (e.g. "how often is vendor X recommended?")
  global_secondary_index {
    name            = "vendorId-timestamp-index"
    hash_key        = "vendorId"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  # GSI: query recommendations by model version (for model comparison analysis)
  # Used by: docs/model_versioning.md rollback and comparison procedures
  global_secondary_index {
    name            = "modelVersion-index"
    hash_key        = "modelVersion"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "ai-vrs-recommendations" }
}

# ── AuditLog table ────────────────────────────────────────────────────────────
# Primary key: logId (UUID v4 — each audit record is unique)
# Three GSIs support the filtering options in GET /audit-logs:
#   jobId-timestamp-index   — find all audit records for a specific job
#   action-timestamp-index  — filter by action type (AI_RECOMMENDATION, etc.)
#   vendorId-timestamp-index — find all records involving a specific vendor
resource "aws_dynamodb_table" "audit_log" {
  name         = "ai-vrs-audit-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "logId"

  attribute {
    name = "logId"
    type = "S"  # UUID v4
  }
  attribute {
    name = "jobId"
    type = "S"
  }
  attribute {
    name = "action"
    type = "S"  # "AI_RECOMMENDATION", "ADMIN_OVERRIDE", etc.
  }
  attribute {
    name = "vendorId"
    type = "S"
  }
  attribute {
    name = "timestamp"
    type = "S"  # ISO 8601 — used as sort key for chronological ordering
  }

  global_secondary_index {
    name            = "jobId-timestamp-index"
    hash_key        = "jobId"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "action-timestamp-index"
    hash_key        = "action"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "vendorId-timestamp-index"
    hash_key        = "vendorId"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "ai-vrs-audit-log" }
}

# ── Users table ───────────────────────────────────────────────────────────────
# Primary key: userId (Cognito sub — UUID assigned by Cognito at registration)
# GSI: email-index — allows checking for duplicate email registrations
# Records are created by handlers/auth.py (Cognito Post-Confirmation trigger)
resource "aws_dynamodb_table" "users" {
  name         = "ai-vrs-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "userId"  # Cognito sub (UUID)

  attribute {
    name = "userId"
    type = "S"
  }
  attribute {
    name = "email"
    type = "S"
  }

  # GSI: look up users by email address
  # Used for: duplicate registration checks, admin lookup
  global_secondary_index {
    name            = "email-index"
    hash_key        = "email"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "ai-vrs-users" }
}

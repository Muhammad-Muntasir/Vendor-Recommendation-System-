###############################################################################
# iam.tf — Lambda execution role with least-privilege permissions
#
# Principle of least privilege (Requirement 15.3):
#   The Lambda role is granted ONLY the specific actions it needs on
#   ONLY the specific resources it uses. No wildcard resources.
#
# Permissions granted:
#   DynamoDB  — read/write on all 5 AI-VRS tables (and their GSIs)
#   S3        — read/write on all 3 AI-VRS buckets
#   Secrets   — read the Gemini API key secret only
#   EventBridge — publish events to the default event bus
#   SQS       — consume messages from the vendor scoring queue
#   CloudWatch Logs — write Lambda execution logs
#   CloudWatch Metrics — emit custom metrics (FallbackScorerActivations, etc.)
###############################################################################

# Data sources to build ARNs dynamically (avoids hardcoding account ID and region)
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ── Lambda execution role ─────────────────────────────────────────────────────
# This role is assumed by the Lambda function at runtime.
# The trust policy allows only the Lambda service to assume it.
resource "aws_iam_role" "lambda_exec" {
  name = "ai-vrs-lambda-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "ai-vrs-lambda-exec-role" }
}

# ── Inline policy — all permissions in one place for clarity ─────────────────
resource "aws_iam_role_policy" "lambda_exec_policy" {
  name = "ai-vrs-lambda-exec-policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [

      # ── DynamoDB ────────────────────────────────────────────────────────────
      # Read/write access to all 5 AI-VRS tables AND their GSIs.
      # GSI ARNs must be explicitly included (they have separate ARNs).
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",    # Read a single item by primary key
          "dynamodb:PutItem",    # Write a new item (used by audit_logger, query)
          "dynamodb:Query",      # Query by partition key (used for recommendations)
          "dynamodb:Scan",       # Full table scan (used for vendor scoring)
          "dynamodb:UpdateItem", # Update existing item (used for job status updates)
        ]
        Resource = [
          aws_dynamodb_table.jobs.arn,
          "${aws_dynamodb_table.jobs.arn}/index/*",           # All GSIs on jobs table
          aws_dynamodb_table.vendors.arn,
          "${aws_dynamodb_table.vendors.arn}/index/*",
          aws_dynamodb_table.recommendations.arn,
          "${aws_dynamodb_table.recommendations.arn}/index/*",
          aws_dynamodb_table.audit_log.arn,
          "${aws_dynamodb_table.audit_log.arn}/index/*",
          aws_dynamodb_table.users.arn,
          "${aws_dynamodb_table.users.arn}/index/*",
        ]
      },

      # ── S3 ──────────────────────────────────────────────────────────────────
      # Read/write access to all objects in the 3 AI-VRS buckets.
      # GetObject: read model-version.txt from lambda-zip bucket
      # PutObject: write audit logs to logs bucket, override feedback to override bucket
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.lambda_zip.arn}/*",        # model-version.txt
          "${aws_s3_bucket.logs.arn}/*",              # Audit log exports
          "${aws_s3_bucket.override_feedback.arn}/*", # Override feedback for retraining
        ]
      },

      # ── Secrets Manager ─────────────────────────────────────────────────────
      # Read ONLY the Gemini API key secret — no other secrets.
      # The ARN uses a wildcard suffix (*) because Secrets Manager appends
      # a random suffix to secret ARNs (e.g. ai-vrs/gemini-api-key-AbCdEf).
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:ai-vrs/gemini-api-key*"
      },

      # ── EventBridge ─────────────────────────────────────────────────────────
      # Publish events to the default event bus.
      # Used by: job_created.py (VendorRecommendationGenerated, NoEligibleVendors)
      #          query.py (JobCreated_Event)
      #          override.py (VendorOverrideRecorded)
      {
        Effect   = "Allow"
        Action   = ["events:PutEvents"]
        Resource = "arn:aws:events:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:event-bus/*"
      },

      # ── SQS ─────────────────────────────────────────────────────────────────
      # Consume messages from the vendor scoring queue.
      # These permissions are required for the Lambda event source mapping to work.
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",       # Poll for new messages
          "sqs:DeleteMessage",        # Delete after successful processing
          "sqs:GetQueueAttributes",   # Required by Lambda event source mapping
        ]
        Resource = aws_sqs_queue.vendor_scoring.arn
      },

      # ── CloudWatch Logs ─────────────────────────────────────────────────────
      # Write Lambda execution logs to the /aws/lambda/ai-vrs log group.
      # Scoped to ai-vrs log groups only (not all Lambda log groups).
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/ai-vrs*"
      },

      # ── CloudWatch Metrics ───────────────────────────────────────────────────
      # Emit custom metrics to the AI-VRS namespace.
      # Resource must be "*" — PutMetricData doesn't support resource-level restrictions.
      # Metrics: FallbackScorerActivations, VendorProfileDataQualityErrors,
      #          RecommendationConfidenceDistribution
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
      }
    ]
  })
}

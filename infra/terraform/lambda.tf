###############################################################################
# lambda.tf — Lambda function definition and event source mappings
#
# Single Lambda function handles ALL event sources:
#   - API Gateway HTTP requests (via proxy integration)
#   - SQS messages (JobCreated_Event from EventBridge)
#   - Cognito Post-Confirmation trigger
#
# The function code is deployed as a zip file stored in S3.
# Environment variables configure table names, bucket names, and the
# Gemini secret name — the actual API key is NEVER stored here.
###############################################################################

resource "aws_lambda_function" "ai_vrs" {
  function_name = "ai-vrs"
  role          = aws_iam_role.lambda_exec.arn

  # Entry point: handler.py → lambda_handler() function
  handler = "handler.lambda_handler"
  runtime = "python3.12"

  # Memory and timeout from variables (defaults: 512MB, 25s)
  memory_size = var.lambda_memory_size
  timeout     = var.lambda_timeout

  # Deployment package: zip file uploaded to S3 by deploy.sh
  # The zip contains the entire backend/lambda/ directory
  s3_bucket = aws_s3_bucket.lambda_zip.id
  s3_key    = var.lambda_zip_key

  # Use unreserved concurrency (-1) — the account doesn't have enough
  # free concurrency to reserve 10 exclusively for this function.
  # In a dedicated production account, set this to var.lambda_reserved_concurrency (10).
  reserved_concurrent_executions = -1

  environment {
    variables = {
      # DynamoDB table names — Lambda reads these at runtime
      JOBS_TABLE            = aws_dynamodb_table.jobs.name
      VENDORS_TABLE         = aws_dynamodb_table.vendors.name
      RECOMMENDATIONS_TABLE = aws_dynamodb_table.recommendations.name
      AUDIT_LOG_TABLE       = aws_dynamodb_table.audit_log.name
      USERS_TABLE           = aws_dynamodb_table.users.name

      # S3 bucket names
      LAMBDA_ZIP_BUCKET        = aws_s3_bucket.lambda_zip.id
      LOGS_BUCKET              = aws_s3_bucket.logs.id
      OVERRIDE_FEEDBACK_BUCKET = aws_s3_bucket.override_feedback.id

      # SECURITY: Only the SECRET NAME is stored here — NOT the API key value.
      # The Lambda fetches the actual key from Secrets Manager at runtime
      # using services/secrets.py (Requirement 15.4).
      GEMINI_SECRET_NAME = var.gemini_secret_name

      # EventBridge bus name for publishing events
      EVENTBRIDGE_BUS_NAME = "default"

      # SQS queue URL (used for reference — actual trigger is via event source mapping)
      SQS_QUEUE_URL = aws_sqs_queue.vendor_scoring.url

      # Environment tag for logging and metrics
      ENVIRONMENT = var.environment
    }
  }

  tags = { Name = "ai-vrs" }
}

# ── SQS event source mapping ──────────────────────────────────────────────────
# Connects the SQS vendor-scoring-queue to the Lambda function.
# batch_size=1 ensures each SQS message is processed independently —
# if one fails, only that message goes to the DLQ (not the whole batch).
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.vendor_scoring.arn
  function_name    = aws_lambda_function.ai_vrs.arn
  batch_size       = 1      # Process one JobCreated_Event at a time
  enabled          = true
}

# ── API Gateway invoke permission ─────────────────────────────────────────────
# Grants API Gateway permission to invoke the Lambda function.
# Without this, API Gateway would receive a 403 when trying to call Lambda.
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ai_vrs.function_name
  principal     = "apigateway.amazonaws.com"
  # Restrict to this specific API Gateway (not all API Gateways in the account)
  source_arn    = "${aws_api_gateway_rest_api.ai_vrs.execution_arn}/*/*"
}

# ── Cognito invoke permission ─────────────────────────────────────────────────
# Grants Cognito permission to invoke Lambda for the Post-Confirmation trigger.
# Triggered when a user confirms their email address after registration.
resource "aws_lambda_permission" "cognito" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ai_vrs.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.ai_vrs.arn
}

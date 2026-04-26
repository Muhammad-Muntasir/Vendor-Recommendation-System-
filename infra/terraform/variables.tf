###############################################################################
# variables.tf — All input variables for the AI-VRS Terraform configuration
#
# Variables with defaults can be overridden via:
#   - terraform.tfvars file (gitignored — never commit secrets)
#   - -var="name=value" CLI flag
#   - TF_VAR_name environment variables
#
# Variables WITHOUT defaults (allowed_cors_origin) MUST be provided.
###############################################################################

variable "aws_region" {
  description = "AWS region where all AI-VRS resources will be deployed"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name — used in resource tags and naming"
  type        = string
  default     = "production"
}

variable "lambda_zip_key" {
  description = "S3 object key for the Lambda deployment zip file in ai-vrs-lambda-zip bucket"
  type        = string
  default     = "lambda.zip"
  # Updated by deploy.sh step [2/5] before terraform apply
}

variable "lambda_reserved_concurrency" {
  description = <<-EOT
    Reserved concurrent executions for the Lambda function.
    Prevents unbounded scaling and cost overruns (Requirement 15.2).
    Set to -1 to use unreserved concurrency (not recommended for production).
  EOT
  type    = number
  default = 10
}

variable "lambda_timeout" {
  description = <<-EOT
    Lambda function timeout in seconds.
    Must be less than the SQS visibility timeout (sqs_visibility_timeout).
    The scoring pipeline must complete within 10s (Requirement 1.7) plus
    Gemini API latency — 25s provides sufficient headroom.
  EOT
  type    = number
  default = 25
}

variable "lambda_memory_size" {
  description = "Lambda function memory in MB — also affects CPU allocation"
  type        = number
  default     = 512
}

variable "allowed_cors_origin" {
  description = <<-EOT
    Explicit CORS allowed origin for API Gateway responses.
    NO DEFAULT — must be set explicitly for each environment.
    Wildcard (*) is NOT permitted in production (Requirement 15.4).
    Example: "https://admin.retailfixit.com"
    For local development: "http://localhost:5173"
  EOT
  type = string
  # No default — intentionally forces explicit configuration
}

variable "gemini_secret_name" {
  description = <<-EOT
    AWS Secrets Manager secret name for the Gemini API key.
    The secret must be pre-provisioned manually before deployment.
    The Lambda reads this name from the GEMINI_SECRET_NAME env var at runtime
    and fetches the actual key from Secrets Manager (never stored in code).
  EOT
  type    = string
  default = "ai-vrs/gemini-api-key"
}

variable "sqs_visibility_timeout" {
  description = <<-EOT
    SQS message visibility timeout in seconds.
    Must be GREATER than lambda_timeout to prevent duplicate processing.
    If Lambda takes longer than this, SQS makes the message visible again
    and another Lambda instance may process it concurrently.
  EOT
  type    = number
  default = 30  # 30s > 25s Lambda timeout
}

variable "sqs_max_receive_count" {
  description = <<-EOT
    Maximum number of times SQS delivers a message before routing to DLQ.
    After this many failed attempts, the message goes to the Dead Letter Queue
    and audit_logger.log_dlq_failure() records the failure (Requirement 4.3).
  EOT
  type    = number
  default = 3
}

variable "cognito_access_token_validity" {
  description = "Cognito access token validity period in hours (1 hour = short-lived for security)"
  type        = number
  default     = 1
}

variable "cognito_refresh_token_validity" {
  description = "Cognito refresh token validity period in days (30 days = reasonable session length)"
  type        = number
  default     = 30
}

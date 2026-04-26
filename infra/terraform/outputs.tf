###############################################################################
# outputs.tf — Terraform output values
#
# These values are printed after "terraform apply" and used by deploy.sh
# to configure the frontend .env file.
#
# Access outputs after deployment:
#   terraform -chdir=infra/terraform output api_gateway_url
#   terraform -chdir=infra/terraform output -json
###############################################################################

output "api_gateway_url" {
  description = <<-EOT
    API Gateway endpoint URL for the prod stage.
    Set this as VITE_API_URL in frontend/.env.
    Example: https://abc123.execute-api.us-east-1.amazonaws.com/prod
  EOT
  value = "${aws_api_gateway_stage.prod.invoke_url}"
}

output "cognito_user_pool_id" {
  description = <<-EOT
    Cognito User Pool ID.
    Set this as VITE_COGNITO_USER_POOL_ID in frontend/.env.
    Example: us-east-1_AbCdEfGhI
  EOT
  value = aws_cognito_user_pool.ai_vrs.id
}

output "cognito_client_id" {
  description = <<-EOT
    Cognito App Client ID (no client secret — SPA configuration).
    Set this as VITE_COGNITO_CLIENT_ID in frontend/.env.
    Example: 1a2b3c4d5e6f7g8h9i0j1k2l3m
  EOT
  value = aws_cognito_user_pool_client.ai_vrs.id
}

output "sqs_queue_url" {
  description = "Vendor scoring SQS queue URL — used by Lambda event source mapping"
  value       = aws_sqs_queue.vendor_scoring.url
}

output "dlq_url" {
  description = "Dead Letter Queue URL — monitor this for failed job processing events"
  value       = aws_sqs_queue.vendor_scoring_dlq.url
}

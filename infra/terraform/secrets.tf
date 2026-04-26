###############################################################################
# Secrets Manager — data source reference only
# The secret is pre-provisioned manually and must NOT be created by Terraform.
###############################################################################

data "aws_secretsmanager_secret" "gemini_api_key" {
  name = var.gemini_secret_name
}

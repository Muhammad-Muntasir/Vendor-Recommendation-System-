###############################################################################
# main.tf — Terraform backend and provider configuration
#
# This file configures:
#   1. The Terraform backend (where state is stored)
#   2. Required provider versions
#   3. The AWS provider with default tags
#
# IMPORTANT: The S3 bucket "retailfixit-terraform-state" must exist BEFORE
# running terraform init. Create it manually:
#   aws s3 mb s3://retailfixit-terraform-state --region us-east-1
#   aws s3api put-bucket-versioning \
#     --bucket retailfixit-terraform-state \
#     --versioning-configuration Status=Enabled
###############################################################################

terraform {
  # Minimum Terraform version required
  required_version = "~> 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"  # AWS provider v5.x — supports all resources used here
    }
  }

  # Remote state backend — stores terraform.tfstate in S3 with encryption
  # This allows multiple team members to share state safely
  backend "s3" {
    bucket  = "retailfixit-terraform-state"  # Must exist before terraform init
    key     = "ai-vrs/terraform.tfstate"     # Path within the bucket
    region  = "us-east-1"
    encrypt = true  # Server-side encryption for the state file
  }
}

provider "aws" {
  region = var.aws_region  # Defaults to "us-east-1" (see variables.tf)

  # Default tags applied to ALL resources created by this configuration
  # Makes it easy to filter AI-VRS resources in the AWS console
  default_tags {
    tags = {
      Project     = "ai-vrs"
      Environment = var.environment  # "production" by default
    }
  }
}

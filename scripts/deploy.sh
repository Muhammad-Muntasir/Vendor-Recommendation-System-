#!/usr/bin/env bash
###############################################################################
# deploy.sh — Build, upload, and deploy the AI Vendor Recommendation System
#
# This script automates the complete deployment process:
#   [1/5] Package Lambda   — zip the backend/lambda/ directory
#   [2/5] Upload to S3     — upload lambda.zip to the ai-vrs-lambda-zip bucket
#   [3/5] Upload version   — write "1.0.0" to model-version.txt in S3
#   [4/5] Terraform init   — download providers and initialise backend
#   [5/5] Terraform apply  — create/update all AWS infrastructure
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - Terraform >= 1.5 installed
#   - jq installed (for parsing Terraform outputs)
#   - S3 bucket "retailfixit-terraform-state" exists (for Terraform state)
#   - Gemini API key stored in Secrets Manager as "ai-vrs/gemini-api-key"
#
# Usage:
#   ./scripts/deploy.sh
#
# After deployment:
#   1. Copy the printed output values to frontend/.env
#   2. Run: python scripts/seed_data.py --vendors 10 --jobs 5
#   3. Run: cd frontend && npm install && npm run dev
###############################################################################

# Exit immediately if any command fails (prevents partial deployments)
set -e

echo "=== AI-VRS Deployment ==="
echo ""

# ── [1/5] Package Lambda ──────────────────────────────────────────────────────
# Create a zip file containing the entire backend/lambda/ directory.
# Excludes:
#   *.pyc         — compiled Python bytecode (regenerated at runtime)
#   __pycache__/* — Python cache directories
echo "[1/5] Packaging Lambda function..."
(cd backend/lambda && zip -r ../../infra/terraform/lambda.zip . -x "*.pyc" -x "__pycache__/*")
echo "      ✓ lambda.zip created ($(du -h infra/terraform/lambda.zip | cut -f1))"

# ── [2/5] Upload Lambda zip to S3 ─────────────────────────────────────────────
# The Lambda function (lambda.tf) references this S3 object as its source.
# Terraform does NOT upload the zip — we do it manually here.
echo "[2/5] Uploading Lambda zip to S3..."
aws s3 cp infra/terraform/lambda.zip s3://ai-vrs-lambda-zip/lambda.zip
echo "      ✓ lambda.zip uploaded to s3://ai-vrs-lambda-zip/lambda.zip"

# ── [3/5] Upload model version ────────────────────────────────────────────────
# The model version is stored as a plain text file in S3.
# Lambda reads this at cold start via utils/model_version.py and caches it.
# To deploy a new model version, update this file and force a Lambda cold start.
echo "[3/5] Uploading model version..."
TMPFILE=$(mktemp)
echo -n "1.0.0" > "$TMPFILE"
aws s3 cp "$TMPFILE" s3://ai-vrs-lambda-zip/model-version.txt
rm -f "$TMPFILE"
echo "      ✓ model-version.txt (1.0.0) uploaded"

# ── [4/5] Terraform init ──────────────────────────────────────────────────────
# Downloads the AWS provider and initialises the S3 backend.
# Safe to run multiple times — idempotent.
echo "[4/5] Initialising Terraform..."
terraform -chdir=infra/terraform init
echo "      ✓ Terraform initialised"

# ── [5/5] Terraform apply ─────────────────────────────────────────────────────
# Creates or updates all AWS resources defined in infra/terraform/*.tf.
# -auto-approve skips the interactive confirmation prompt.
# WARNING: This will create real AWS resources and incur costs.
echo "[5/5] Applying Terraform configuration..."
terraform -chdir=infra/terraform apply -auto-approve
echo "      ✓ Infrastructure deployed"

# ── Print outputs ─────────────────────────────────────────────────────────────
# Extract the three values needed for frontend/.env using jq.
echo ""
echo "=== Deployment Outputs ==="
OUTPUTS=$(terraform -chdir=infra/terraform output -json)

API_URL=$(echo "$OUTPUTS" | jq -r '.api_gateway_url.value')
POOL_ID=$(echo "$OUTPUTS" | jq -r '.cognito_user_pool_id.value')
CLIENT_ID=$(echo "$OUTPUTS" | jq -r '.cognito_client_id.value')

echo "  API Gateway URL:       $API_URL"
echo "  Cognito User Pool ID:  $POOL_ID"
echo "  Cognito Client ID:     $CLIENT_ID"

# ── Next steps ────────────────────────────────────────────────────────────────
echo ""
echo "=== Next Steps ==="
echo "  1. Update frontend/.env with the values above:"
echo "       VITE_API_URL=$API_URL"
echo "       VITE_COGNITO_USER_POOL_ID=$POOL_ID"
echo "       VITE_COGNITO_CLIENT_ID=$CLIENT_ID"
echo ""
echo "  2. Seed DynamoDB with test data:"
echo "       python scripts/seed_data.py --vendors 10 --jobs 5"
echo ""
echo "  3. Start the frontend development server:"
echo "       cd frontend && npm install && npm run dev"
echo ""
echo "=== Deployment complete ==="

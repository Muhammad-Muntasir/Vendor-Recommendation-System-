###############################################################################
# S3 Buckets — AI Vendor Recommendation System
###############################################################################

# ---------------------------------------------------------------------------
# Lambda zip bucket (stores deployment zip + model-version.txt)
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "lambda_zip" {
  bucket = "ai-vrs-lambda-zip"
  tags   = { Name = "ai-vrs-lambda-zip" }
}

resource "aws_s3_bucket_public_access_block" "lambda_zip" {
  bucket                  = aws_s3_bucket.lambda_zip.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_zip" {
  bucket = aws_s3_bucket.lambda_zip.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "lambda_zip" {
  bucket = aws_s3_bucket.lambda_zip.id
  versioning_configuration {
    status = "Enabled"
  }
}

# ---------------------------------------------------------------------------
# Logs bucket (audit log exports — SSE-S3, lifecycle to Glacier then expire)
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "logs" {
  bucket = "ai-vrs-logs"
  tags   = { Name = "ai-vrs-logs" }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    id     = "archive-and-expire"
    status = "Enabled"
    filter {
      prefix = ""
    }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration {
      days = 365
    }
  }
}

# ---------------------------------------------------------------------------
# Override feedback bucket (retraining data — 2-year retention, date-partitioned)
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "override_feedback" {
  bucket = "ai-vrs-override-feedback"
  tags   = { Name = "ai-vrs-override-feedback" }
}

resource "aws_s3_bucket_public_access_block" "override_feedback" {
  bucket                  = aws_s3_bucket.override_feedback.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "override_feedback" {
  bucket = aws_s3_bucket.override_feedback.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "override_feedback" {
  bucket = aws_s3_bucket.override_feedback.id
  rule {
    id     = "expire-after-2-years"
    status = "Enabled"
    # Key prefix pattern: year={YYYY}/month={MM}/day={DD}/
    filter {
      prefix = "year="
    }
    expiration {
      days = 730
    }
  }
}

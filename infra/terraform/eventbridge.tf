###############################################################################
# EventBridge Rules — AI Vendor Recommendation System
###############################################################################

# SNS topic for alerts (used by NoEligibleVendors rule)
resource "aws_sns_topic" "alerts" {
  name = "ai-vrs-alerts"
  tags = { Name = "ai-vrs-alerts" }
}

# ---------------------------------------------------------------------------
# JobCreated rule → SQS vendor-scoring-queue
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "job_created" {
  name        = "ai-vrs-job-created"
  description = "Routes JobCreated events to the vendor scoring SQS queue"

  event_pattern = jsonencode({
    source        = ["retailfixit.jobs"]
    "detail-type" = ["JobCreated"]
  })

  tags = { Name = "ai-vrs-job-created" }
}

resource "aws_cloudwatch_event_target" "job_created_sqs" {
  rule      = aws_cloudwatch_event_rule.job_created.name
  target_id = "VendorScoringQueue"
  arn       = aws_sqs_queue.vendor_scoring.arn
}

# ---------------------------------------------------------------------------
# VendorRecommendationGenerated rule → CloudWatch log group
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "vendor_recommendation_generated" {
  name        = "ai-vrs-vendor-recommendation-generated"
  description = "Logs VendorRecommendationGenerated events"

  event_pattern = jsonencode({
    "detail-type" = ["VendorRecommendationGenerated"]
  })
}

resource "aws_cloudwatch_event_target" "vendor_recommendation_generated_log" {
  rule      = aws_cloudwatch_event_rule.vendor_recommendation_generated.name
  target_id = "CloudWatchLogs"
  arn       = aws_cloudwatch_log_group.audit_log_exports.arn
}

# ---------------------------------------------------------------------------
# VendorOverrideRecorded rule → CloudWatch log group
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "vendor_override_recorded" {
  name        = "ai-vrs-vendor-override-recorded"
  description = "Logs VendorOverrideRecorded events"

  event_pattern = jsonencode({
    "detail-type" = ["VendorOverrideRecorded"]
  })
}

resource "aws_cloudwatch_event_target" "vendor_override_recorded_log" {
  rule      = aws_cloudwatch_event_rule.vendor_override_recorded.name
  target_id = "CloudWatchLogs"
  arn       = aws_cloudwatch_log_group.audit_log_exports.arn
}

# ---------------------------------------------------------------------------
# NoEligibleVendors rule → CloudWatch log group + SNS alert
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "no_eligible_vendors" {
  name        = "ai-vrs-no-eligible-vendors"
  description = "Alerts when no eligible vendors are found for a job"

  event_pattern = jsonencode({
    "detail-type" = ["NoEligibleVendors"]
  })
}

resource "aws_cloudwatch_event_target" "no_eligible_vendors_log" {
  rule      = aws_cloudwatch_event_rule.no_eligible_vendors.name
  target_id = "CloudWatchLogs"
  arn       = aws_cloudwatch_log_group.audit_log_exports.arn
}

resource "aws_cloudwatch_event_target" "no_eligible_vendors_sns" {
  rule      = aws_cloudwatch_event_rule.no_eligible_vendors.name
  target_id = "SNSAlert"
  arn       = aws_sns_topic.alerts.arn
}

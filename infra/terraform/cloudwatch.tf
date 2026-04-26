###############################################################################
# CloudWatch — Log Groups, Metric Filters, and Alarms
###############################################################################

# ---------------------------------------------------------------------------
# Log Groups
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/ai-vrs"
  retention_in_days = 90
  tags              = { Name = "ai-vrs-lambda-logs" }
}

resource "aws_cloudwatch_log_group" "audit_log_exports" {
  name              = "/ai-vrs/audit-log-exports"
  retention_in_days = 365
  tags              = { Name = "ai-vrs-audit-log-exports" }
}

# ---------------------------------------------------------------------------
# Metric Filters — extract counts from Lambda log output
# ---------------------------------------------------------------------------

# VendorProfileDataQualityErrors
resource "aws_cloudwatch_log_metric_filter" "vendor_data_quality_errors" {
  name           = "VendorProfileDataQualityErrors"
  log_group_name = aws_cloudwatch_log_group.lambda.name
  pattern        = "VendorProfileDataQualityErrors"

  metric_transformation {
    name          = "VendorProfileDataQualityErrors"
    namespace     = "AI-VRS"
    value         = "1"
    default_value = "0"
  }
}

# FallbackScorerActivations
resource "aws_cloudwatch_log_metric_filter" "fallback_scorer_activations" {
  name           = "FallbackScorerActivations"
  log_group_name = aws_cloudwatch_log_group.lambda.name
  pattern        = "FallbackScorerActivations"

  metric_transformation {
    name          = "FallbackScorerActivations"
    namespace     = "AI-VRS"
    value         = "1"
    default_value = "0"
  }
}

# ---------------------------------------------------------------------------
# SNS topic for alarm actions (reuse from eventbridge.tf)
# ---------------------------------------------------------------------------
# aws_sns_topic.alerts is defined in eventbridge.tf

# ---------------------------------------------------------------------------
# Alarms
# ---------------------------------------------------------------------------

# HighLowConfidenceRate — >30% Low-confidence recommendations in 24h
resource "aws_cloudwatch_metric_alarm" "high_low_confidence_rate" {
  alarm_name          = "HighLowConfidenceRate"
  alarm_description   = "Low-confidence recommendation rate exceeded 30% in a 24-hour window"
  namespace           = "AI-VRS"
  metric_name         = "RecommendationConfidenceDistribution"
  dimensions          = { ConfidenceLevel = "Low" }
  statistic           = "Sum"
  period              = 86400 # 24 hours
  evaluation_periods  = 1
  threshold           = 0.30
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = { Name = "HighLowConfidenceRate" }
}

# HighOverrideRate — >40% override rate in 7-day window
resource "aws_cloudwatch_metric_alarm" "high_override_rate" {
  alarm_name          = "HighOverrideRate"
  alarm_description   = "AI recommendation override rate exceeded 40% in a 7-day window"
  namespace           = "AI-VRS"
  metric_name         = "OverrideRate"
  statistic           = "Average"
  period              = 604800 # 7 days
  evaluation_periods  = 1
  threshold           = 0.40
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = { Name = "HighOverrideRate" }
}

# FallbackScorerActivations — >10 activations in 1 hour
resource "aws_cloudwatch_metric_alarm" "fallback_scorer_activations" {
  alarm_name          = "FallbackScorerActivations"
  alarm_description   = "Fallback scorer activated more than 10 times in 1 hour"
  namespace           = "AI-VRS"
  metric_name         = "FallbackScorerActivations"
  statistic           = "Sum"
  period              = 3600 # 1 hour
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = { Name = "FallbackScorerActivations" }
}

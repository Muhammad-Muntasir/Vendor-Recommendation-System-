###############################################################################
# SQS — Vendor Scoring Queue and Dead Letter Queue
###############################################################################

# Dead Letter Queue
resource "aws_sqs_queue" "vendor_scoring_dlq" {
  name                      = "ai-vrs-vendor-scoring-dlq"
  message_retention_seconds = 1209600 # 14 days

  tags = { Name = "ai-vrs-vendor-scoring-dlq" }
}

# Main vendor scoring queue
resource "aws_sqs_queue" "vendor_scoring" {
  name                       = "ai-vrs-vendor-scoring-queue"
  visibility_timeout_seconds = var.sqs_visibility_timeout # 30s — must exceed Lambda timeout
  message_retention_seconds  = 345600                     # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.vendor_scoring_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count # 3
  })

  tags = { Name = "ai-vrs-vendor-scoring-queue" }
}

# Allow EventBridge to send messages to the queue
resource "aws_sqs_queue_policy" "vendor_scoring" {
  queue_url = aws_sqs_queue.vendor_scoring.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.vendor_scoring.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_cloudwatch_event_rule.job_created.arn
        }
      }
    }]
  })
}

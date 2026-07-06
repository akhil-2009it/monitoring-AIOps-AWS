# Billing module — must be applied with a us-east-1 provider alias because
# AWS Billing metrics + AWS Budgets only emit/are queryable from us-east-1.
terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      configuration_aliases = [aws.useast1]
    }
  }
}

locals {
  prefix = "${var.project}-${var.environment}"
}

# ─── SNS topic in us-east-1 ──────────────────────────────────────────────────
resource "aws_sns_topic" "billing" {
  provider = aws.useast1
  name     = "${local.prefix}-billing-alerts"
  tags     = var.tags
}

resource "aws_sns_topic_subscription" "billing_email" {
  provider  = aws.useast1
  topic_arn = aws_sns_topic.billing.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ─── AWS Budget — one budget, multiple thresholds ────────────────────────────
resource "aws_budgets_budget" "monthly" {
  provider = aws.useast1

  name              = "${local.prefix}-monthly-cost"
  budget_type       = "COST"
  limit_amount      = tostring(var.monthly_budget_usd)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  cost_filter {
    name = "TagKeyValue"
    values = [
      "user:Project$${var.project}",
    ]
  }

  dynamic "notification" {
    for_each = var.thresholds_pct
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value <= 100 ? "ACTUAL" : "FORECASTED"
      subscriber_email_addresses = [var.alert_email]
      subscriber_sns_topic_arns  = [aws_sns_topic.billing.arn]
    }
  }
}

# ─── Classic billing CloudWatch alarms ───────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "estimated_charges" {
  provider = aws.useast1

  for_each = { for v in var.thresholds_pct : tostring(v) => (var.monthly_budget_usd * v / 100) }

  alarm_name          = "${local.prefix}/billing/estimated-charges-${each.key}pct"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600 # 6h — billing metrics update slowly
  statistic           = "Maximum"
  threshold           = each.value

  dimensions = { Currency = "USD" }

  alarm_actions = [aws_sns_topic.billing.arn]
  ok_actions    = [aws_sns_topic.billing.arn]
  tags          = var.tags
}

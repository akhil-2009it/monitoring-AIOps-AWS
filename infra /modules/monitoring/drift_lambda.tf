# Drift detection Lambda — runs the ml/monitoring/lambda_handler.py code.
# This file lives alongside main.tf in the monitoring module.
#
# The Lambda artifact (zip) is built and pushed by GitHub Actions; this TF
# resource references a placeholder S3 key. CI updates the function code
# via `aws lambda update-function-code` after every successful build.

variable "drift_lambda_s3_bucket" {
  description = "S3 bucket where the drift-detector Lambda zip is uploaded by CI"
  type        = string
  default     = ""
}

variable "drift_lambda_s3_key" {
  description = "S3 key for the drift-detector Lambda zip"
  type        = string
  default     = "lambda/drift-detector/latest.zip"
}

variable "features_bucket_for_drift" {
  description = "Features bucket name for the drift Lambda to read"
  type        = string
  default     = ""
}

# ─── IAM ──────────────────────────────────────────────────────────────────────
resource "aws_iam_role" "drift_lambda" {
  count = var.drift_lambda_s3_bucket != "" ? 1 : 0
  name  = "${local.prefix}-drift-detector-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "drift_lambda_basic" {
  count      = var.drift_lambda_s3_bucket != "" ? 1 : 0
  role       = aws_iam_role.drift_lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "drift_lambda" {
  count = var.drift_lambda_s3_bucket != "" ? 1 : 0
  name  = "${local.prefix}-drift-detector-policy"
  role  = aws_iam_role.drift_lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.features_bucket_for_drift}",
          "arn:aws:s3:::${var.features_bucket_for_drift}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = { "cloudwatch:namespace" = "mlops-learning/drift" }
        }
      }
    ]
  })
}

# ─── Lambda function ─────────────────────────────────────────────────────────
resource "aws_lambda_function" "drift_detector" {
  for_each = var.drift_lambda_s3_bucket != "" ? toset(local.model_endpoints) : toset([])

  function_name = "${local.prefix}-drift-detector-${each.key}"
  role          = aws_iam_role.drift_lambda[0].arn
  handler       = "ml.monitoring.lambda_handler.handler"
  runtime       = "python3.11"
  timeout       = 300
  memory_size   = 1024
  s3_bucket     = var.drift_lambda_s3_bucket
  s3_key        = var.drift_lambda_s3_key

  environment {
    variables = {
      MODEL_NAME           = each.key
      ENVIRONMENT          = var.environment
      FEATURES_BUCKET      = var.features_bucket_for_drift
      BASELINE_PREFIX      = "baselines/${each.key}/"
      CURRENT_FEATURES_KEY = "features/${each.key}/current.parquet"
      PSI_WARN             = tostring(local.drift.psi_warning)
      PSI_ALERT            = tostring(local.drift.psi_alert)
    }
  }

  tags = merge(var.tags, { Name = "${local.prefix}-drift-detector-${each.key}" })

  lifecycle {
    # CI updates the code; Terraform should not revert it.
    ignore_changes = [s3_key, source_code_hash]
  }
}

resource "aws_cloudwatch_log_group" "drift_detector" {
  for_each          = aws_lambda_function.drift_detector
  name              = "/aws/lambda/${each.value.function_name}"
  retention_in_days = 14
  tags              = var.tags
}

# ─── Schedule (hourly) ───────────────────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "drift_schedule" {
  for_each = aws_lambda_function.drift_detector

  name                = "${local.prefix}-drift-schedule-${each.key}"
  description         = "Hourly drift check for ${each.key}"
  schedule_expression = "rate(1 hour)"
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "drift_schedule" {
  for_each  = aws_lambda_function.drift_detector
  rule      = aws_cloudwatch_event_rule.drift_schedule[each.key].name
  target_id = "DriftLambda-${each.key}"
  arn       = each.value.arn
}

resource "aws_lambda_permission" "drift_schedule" {
  for_each      = aws_lambda_function.drift_detector
  statement_id  = "AllowEventBridgeDrift-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = each.value.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.drift_schedule[each.key].arn
}

# ─── Per-feature PSI alarm (fans into existing retrain rule) ─────────────────
locals {
  drift_canary_features = {
    "engagement_score"     = "engagement-score"
    "accuracy"             = "accuracy"
    "topic_weakness_score" = "topic-weakness"
  }
}

resource "aws_cloudwatch_metric_alarm" "drift_psi_alarm" {
  for_each = aws_lambda_function.drift_detector != {} ? merge([
    for model, _ in aws_lambda_function.drift_detector : {
      for feature, slug in local.drift_canary_features :
      "${model}-${slug}" => { model = model, feature = feature, slug = slug }
    }
  ]...) : {}

  alarm_name          = "${local.prefix}/L7/feature-drift-${each.value.model}-${each.value.slug}-alarm"
  alarm_description   = "PSI for ${each.value.feature} on ${each.value.model} > ${local.drift.psi_alert} — trigger retrain"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "PSI"
  namespace           = "mlops-learning/drift"
  period              = 3600
  statistic           = "Maximum"
  threshold           = local.drift.psi_alert

  dimensions = {
    Model       = each.value.model
    Environment = var.environment
    Feature     = each.value.feature
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

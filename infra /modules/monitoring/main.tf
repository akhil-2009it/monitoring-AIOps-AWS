locals {
  prefix = "${var.project}-${var.environment}"

  # Drift thresholds from CLAUDE.md — do not change without team review
  drift = {
    psi_warning         = 0.10
    psi_alert           = 0.20
    kl_divergence_alert = 0.15
    data_quality_pct    = 0.05
    bias_accuracy_delta = 0.10
    endpoint_p99_ms     = 300
    endpoint_error_rate = 0.01
  }

  # Models that have SageMaker endpoints
  model_endpoints = ["perf-predictor", "knowledge-tracing", "dropout-risk"]

  # EventBridge retrain rule pattern from CLAUDE.md
  retrain_models = {
    "perf-predictor"    = "perf-predictor-${var.environment}-pipeline"
    "knowledge-tracing" = "knowledge-tracing-${var.environment}-pipeline"
    "dropout-risk"      = "dropout-risk-${var.environment}-pipeline"
  }
}

# ─── SNS Topic for Alerts ─────────────────────────────────────────────────────
resource "aws_sns_topic" "alerts" {
  name = "${local.prefix}-mlops-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.billing_alert_email
}

# ─── Billing Alarms (must be in us-east-1) ───────────────────────────────────
# NOTE: Billing metrics are only available in us-east-1.
# These are configured separately via a provider alias.
# Here we create the SNS topics and alarm logic in ap-south-1
# and note that the billing alarm itself needs the us-east-1 provider.

resource "aws_sns_topic" "billing_alerts" {
  # This must be in us-east-1 for billing alarms — configure via separate provider if needed
  name = "${local.prefix}-billing-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "billing_email" {
  topic_arn = aws_sns_topic.billing_alerts.arn
  protocol  = "email"
  endpoint  = var.billing_alert_email
}

# ─── Kinesis Consumer Lag Alarm (L2) ─────────────────────────────────────────
# Alarm: mlops-learning/{env}/L2/kinesis-consumer-lag-alarm
resource "aws_cloudwatch_metric_alarm" "kinesis_consumer_lag" {
  alarm_name          = "${local.prefix}/L2/kinesis-consumer-lag-alarm"
  alarm_description   = "Kinesis consumer iterator age > 5 min — processing falling behind"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  namespace           = "AWS/Kinesis"
  period              = 60
  statistic           = "Maximum"
  threshold           = 300000 # 5 minutes in ms

  dimensions = {
    StreamName = var.kinesis_stream_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

# ─── SageMaker Endpoint Latency Alarms (L6) ──────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "endpoint_latency_p99" {
  for_each = toset(local.model_endpoints)

  alarm_name          = "${local.prefix}/L6/endpoint-${each.key}-latency-p99-alarm"
  alarm_description   = "Endpoint ${each.key} p99 latency > ${local.drift.endpoint_p99_ms}ms — SLO breach"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "ModelLatency"
  namespace           = "AWS/SageMaker"
  period              = 60
  extended_statistic  = "p99"
  threshold           = local.drift.endpoint_p99_ms * 1000 # microseconds

  dimensions = {
    EndpointName = "${each.key}-${var.environment}"
    VariantName  = "AllTraffic"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

# ─── SageMaker Endpoint Error Rate Alarms (L6) ───────────────────────────────
resource "aws_cloudwatch_metric_alarm" "endpoint_error_rate" {
  for_each = toset(local.model_endpoints)

  alarm_name          = "${local.prefix}/L6/endpoint-${each.key}-error-rate-alarm"
  alarm_description   = "Endpoint ${each.key} error rate > 1% — P1 alert"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Invocation5XXErrors"
  namespace           = "AWS/SageMaker"
  period              = 60
  statistic           = "Sum"
  threshold           = 5 # >5 errors per minute ≈ 1% at 500 rps

  dimensions = {
    EndpointName = "${each.key}-${var.environment}"
    VariantName  = "AllTraffic"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

# ─── Feature Drift Alarms (L7) ───────────────────────────────────────────────
# PSI alarm for engagement_score (the primary drift canary feature)
resource "aws_cloudwatch_metric_alarm" "feature_drift_engagement" {
  alarm_name          = "${local.prefix}/L7/feature-drift-engagement-score-alarm"
  alarm_description   = "PSI for engagement_score > ${local.drift.psi_alert} — trigger retrain"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "feature_baseline_drift_check.violations.count"
  namespace           = "aws/sagemaker/Endpoints/data-metrics"
  period              = 3600 # hourly
  statistic           = "Maximum"
  threshold           = local.drift.psi_alert

  dimensions = {
    MonitoringSchedule = "${local.prefix}-perf-predictor-data-quality-schedule"
    Feature            = "engagement_score"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
  tags          = var.tags
}

# ─── CloudWatch Dashboard ─────────────────────────────────────────────────────
resource "aws_cloudwatch_dashboard" "mlops" {
  dashboard_name = "${local.prefix}-mlops-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "text"
        x      = 0
        y      = 0
        width  = 24
        height = 2
        properties = {
          markdown = "# MLOps Learning Platform — ${upper(var.environment)}\nRegion: ${var.aws_region} | Project: ${var.project}"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 2
        width  = 8
        height = 6
        properties = {
          title  = "Kinesis — Iterator Age (ms)"
          period = 60
          stat   = "Maximum"
          metrics = [[
            "AWS/Kinesis",
            "GetRecords.IteratorAgeMilliseconds",
            "StreamName", var.kinesis_stream_name
          ]]
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 2
        width  = 8
        height = 6
        properties = {
          title  = "SageMaker Endpoints — Invocations"
          period = 60
          stat   = "Sum"
          metrics = [
            for ep in local.model_endpoints : [
              "AWS/SageMaker",
              "Invocations",
              "EndpointName", "${ep}-${var.environment}",
              "VariantName", "AllTraffic",
              { label = ep }
            ]
          ]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 2
        width  = 8
        height = 6
        properties = {
          title  = "Endpoints — p99 Latency (µs)"
          period = 60
          stat   = "p99"
          metrics = [
            for ep in local.model_endpoints : [
              "AWS/SageMaker",
              "ModelLatency",
              "EndpointName", "${ep}-${var.environment}",
              "VariantName", "AllTraffic",
              { label = ep }
            ]
          ]
        }
      },
      {
        type   = "alarm"
        x      = 0
        y      = 8
        width  = 24
        height = 4
        properties = {
          title = "Active Alarms"
          alarms = concat(
            [aws_cloudwatch_metric_alarm.kinesis_consumer_lag.arn,
            aws_cloudwatch_metric_alarm.feature_drift_engagement.arn],
            [for k, v in aws_cloudwatch_metric_alarm.endpoint_latency_p99 : v.arn],
            [for k, v in aws_cloudwatch_metric_alarm.endpoint_error_rate : v.arn]
          )
        }
      }
    ]
  })
}

# ─── Lambda — Auto-retrain Trigger ───────────────────────────────────────────
resource "aws_iam_role" "retrain_lambda" {
  name = "${local.prefix}-retrain-trigger-role"

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

resource "aws_iam_role_policy_attachment" "retrain_lambda_basic" {
  role       = aws_iam_role.retrain_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "retrain_sagemaker" {
  name = "${local.prefix}-retrain-sagemaker-policy"
  role = aws_iam_role.retrain_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sagemaker:StartPipelineExecution", "sagemaker:DescribePipeline"]
      Resource = "arn:aws:sagemaker:${var.aws_region}:${var.account_id}:pipeline/*-${var.environment}-pipeline"
    }]
  })
}

data "archive_file" "retrain_lambda" {
  type        = "zip"
  output_path = "${path.module}/retrain_lambda.zip"

  source {
    content  = <<-PYTHON
      import json, boto3, datetime, os

      sm = boto3.client('sagemaker', region_name=os.environ['AWS_REGION'])
      ENV = os.environ['ENVIRONMENT']

      # Naming convention from CLAUDE.md rule #6
      PIPELINE_MAP = {
          'perf-predictor':    f'perf-predictor-{ENV}-pipeline',
          'knowledge-tracing': f'knowledge-tracing-{ENV}-pipeline',
          'dropout-risk':      f'dropout-risk-{ENV}-pipeline',
      }

      def handler(event, context):
          """Triggered by EventBridge when a drift alarm fires."""
          alarm_name = event.get('detail', {}).get('alarmName', '')
          print(f"Alarm triggered: {alarm_name}")

          model = None
          for key in PIPELINE_MAP:
              if key in alarm_name:
                  model = key
                  break

          if not model:
              print(f"Could not identify model from alarm name: {alarm_name}")
              return {"statusCode": 400}

          pipeline_name = PIPELINE_MAP[model]
          execution_name = f"auto-retrain-{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

          resp = sm.start_pipeline_execution(
              PipelineName=pipeline_name,
              PipelineExecutionDisplayName=execution_name,
              PipelineParameters=[
                  {"Name": "trigger", "Value": "drift-alarm"},
                  {"Name": "alarm_name", "Value": alarm_name},
              ]
          )
          print(f"Started pipeline execution: {resp['PipelineExecutionArn']}")
          return {"statusCode": 200, "pipelineExecutionArn": resp['PipelineExecutionArn']}
      PYTHON
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "retrain_trigger" {
  function_name    = "${local.prefix}-retrain-trigger"
  role             = aws_iam_role.retrain_lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.11"
  timeout          = 30
  filename         = data.archive_file.retrain_lambda.output_path
  source_code_hash = data.archive_file.retrain_lambda.output_base64sha256

  environment {
    variables = {
      ENVIRONMENT = var.environment
      AWS_REGION  = var.aws_region
    }
  }

  tags = merge(var.tags, { Name = "${local.prefix}-retrain-trigger" })
}

resource "aws_cloudwatch_log_group" "retrain_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.retrain_trigger.function_name}"
  retention_in_days = 14
  tags              = var.tags
}

# ─── EventBridge Rules — Drift → Retrain ─────────────────────────────────────
# Rule name pattern from CLAUDE.md: mlops-learning-{model}-drift-retrain-rule
resource "aws_cloudwatch_event_rule" "drift_retrain" {
  for_each = local.retrain_models

  name        = "${var.project}-${each.key}-drift-retrain-rule"
  description = "Trigger auto-retrain for ${each.key} when drift alarm fires"

  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    detail-type = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [{ prefix = "${local.prefix}/L7" }]
      state     = { value = ["ALARM"] }
    }
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "drift_retrain" {
  for_each = local.retrain_models

  rule      = aws_cloudwatch_event_rule.drift_retrain[each.key].name
  target_id = "RetrainLambda-${each.key}"
  arn       = aws_lambda_function.retrain_trigger.arn
}

resource "aws_lambda_permission" "eventbridge_retrain" {
  for_each = local.retrain_models

  statement_id  = "AllowEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.retrain_trigger.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.drift_retrain[each.key].arn
}

# ─── SNS → CloudWatch Alarm Actions ──────────────────────────────────────────
resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudwatch.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.alerts.arn
    }]
  })
}

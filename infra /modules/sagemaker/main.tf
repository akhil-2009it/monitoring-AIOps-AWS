locals {
  prefix = "${var.project}-${var.environment}"

  # Naming convention: {model}-{environment}
  model_groups = {
    rcf_metrics           = "RCFMetricsModelGroup"
    iforest_logs          = "IForestLogsModelGroup"
    lstm_ae_traces        = "LSTMAETracesModelGroup"
    log_embedding_anomaly = "LogEmbeddingAnomalyModelGroup"
  }

  endpoints = {
    rcf_metrics           = "rcf-metrics-${var.environment}"
    iforest_logs          = "iforest-logs-${var.environment}"
    lstm_ae_traces        = "lstm-ae-traces-${var.environment}"
    log_embedding_anomaly = "log-embedding-anomaly-${var.environment}"
  }
}

# ─── SageMaker Execution Role ─────────────────────────────────────────────────
resource "aws_iam_role" "sagemaker_exec" {
  name = "${local.prefix}-sagemaker-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sagemaker.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "sagemaker_full" {
  role       = aws_iam_role.sagemaker_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy" "sagemaker_s3_access" {
  name = "${local.prefix}-sagemaker-s3-policy"
  role = aws_iam_role.sagemaker_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Least-privilege S3: only project buckets
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          "arn:aws:s3:::${var.project}-${var.environment}-*",
          "arn:aws:s3:::${var.project}-${var.environment}-*/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:${var.project}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "mlops-learning/models"
          }
        }
      }
    ]
  })
}

# ─── Feature Group: log-features-v1 ──────────────────────────────────────────
resource "aws_sagemaker_feature_group" "log_features" {
  feature_group_name             = "${var.project}-log-features-v1"
  record_identifier_feature_name = "feature_key"
  event_time_feature_name        = "feature_timestamp"
  role_arn                       = aws_iam_role.sagemaker_exec.arn
  description                    = "Per-(source, host, window) tabular log features for IForest detector"

  online_store_config {
    enable_online_store = true
  }

  offline_store_config {
    s3_storage_config {
      s3_uri = "s3://${var.feature_store_bucket}/feature-store/log-features/"
    }
    disable_glue_table_creation = false
  }

  # feature_key = "{source}|{host}|{window_start_iso}"
  feature_definition {
    feature_name = "feature_key"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "feature_timestamp"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "request_count"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "rate_4xx"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "rate_5xx"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "distinct_ips"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "distinct_paths"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "auth_failure_rate"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "p99_latency_ms"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "p50_latency_ms"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "avg_bytes"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "entropy_path"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "entropy_src_ip"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "user_agent_distinct"
    feature_type = "Fractional"
  }

  tags = var.tags
}

# ─── Feature Group: metric-features-v1 ───────────────────────────────────────
resource "aws_sagemaker_feature_group" "metric_features" {
  feature_group_name             = "${var.project}-metric-features-v1"
  record_identifier_feature_name = "feature_key"
  event_time_feature_name        = "feature_timestamp"
  role_arn                       = aws_iam_role.sagemaker_exec.arn
  description                    = "Per-(host, metric, window) numeric features for RCF detector"

  online_store_config {
    enable_online_store = true
  }

  offline_store_config {
    s3_storage_config {
      s3_uri = "s3://${var.feature_store_bucket}/feature-store/metric-features/"
    }
    disable_glue_table_creation = false
  }

  feature_definition {
    feature_name = "feature_key"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "feature_timestamp"
    feature_type = "String"
  }
  feature_definition {
    feature_name = "value_p50"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "value_p95"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "value_p99"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "value_max"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "delta_p50"
    feature_type = "Fractional"
  }
  feature_definition {
    feature_name = "slope"
    feature_type = "Fractional"
  }

  tags = var.tags
}

# ─── Model Registry Groups ────────────────────────────────────────────────────
resource "aws_sagemaker_model_package_group" "groups" {
  for_each = local.model_groups

  model_package_group_name        = each.value
  model_package_group_description = "Model Registry group for ${each.key} — ${var.environment}"

  tags = var.tags
}

# ─── SageMaker Domain (Studio) ───────────────────────────────────────────────
# NOTE: This requires a VPC + subnets. Created in the root module's VPC.
# Studio domain is managed separately to avoid accidental deletion of EFS.

# ─── Endpoint Configurations ─────────────────────────────────────────────────
# NOTE: The actual model artifacts are populated by CodePipeline after first training.
# These endpoint configs use a placeholder. Real configs are upserted by the CI/CD module.

# We create the endpoint configs here as shells; the CI/CD pipeline updates them.
# This ensures the endpoints exist for smoke tests and monitoring alarms.

# Model Monitor baseline schedule — RCF metrics detector
resource "aws_sagemaker_monitoring_schedule" "rcf_metrics_data_quality" {
  name = "${local.prefix}-rcf-metrics-data-quality-schedule"

  monitoring_schedule_config {
    monitoring_type = "DataQuality"

    monitoring_job_definition_name = "${local.prefix}-rcf-metrics-baseline"
    schedule_config {
      schedule_expression = "cron(0 * ? * * *)" # hourly
    }
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [monitoring_schedule_config[0].monitoring_job_definition_name]
  }
}

# ─── Secrets Manager — no plaintext secrets in code ──────────────────────────
resource "aws_secretsmanager_secret" "sagemaker_config" {
  name                    = "${var.project}/${var.environment}/sagemaker-config"
  description             = "SageMaker runtime configuration (populated by CI/CD)"
  recovery_window_in_days = 7
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "sagemaker_config" {
  secret_id = aws_secretsmanager_secret.sagemaker_config.id
  secret_string = jsonencode({
    log_feature_group_name    = aws_sagemaker_feature_group.log_features.feature_group_name
    metric_feature_group_name = aws_sagemaker_feature_group.metric_features.feature_group_name
    environment               = var.environment
    # endpoint_names populated after first deploy
  })
}

# ─── CloudWatch Log Groups for SageMaker ─────────────────────────────────────
resource "aws_cloudwatch_log_group" "sagemaker_training" {
  name              = "/aws/sagemaker/TrainingJobs"
  retention_in_days = 30
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "sagemaker_processing" {
  name              = "/aws/sagemaker/ProcessingJobs"
  retention_in_days = 30
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "sagemaker_endpoints" {
  name              = "/aws/sagemaker/Endpoints"
  retention_in_days = 30
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "sagemaker_pipelines" {
  name              = "/aws/sagemaker/Pipelines"
  retention_in_days = 30
  tags              = var.tags
}

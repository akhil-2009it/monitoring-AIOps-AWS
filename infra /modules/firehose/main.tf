locals {
  prefix = "${var.project}-${var.environment}"

  # One delivery stream per source. Each writes to its own S3 prefix and
  # has its own role (least privilege per source).
  sources = toset([
    "cloudfront",
    "alb",
    "waf",
    "app",
    "eks",
    "nginx",
    "mysql",
  ])
}

# ─── IAM role for Firehose to write to S3 (one role, per-source policies) ────
resource "aws_iam_role" "firehose" {
  for_each = local.sources
  name     = "${local.prefix}-fh-${each.key}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "firehose" {
  for_each = local.sources
  name     = "${local.prefix}-fh-${each.key}-policy"
  role     = aws_iam_role.firehose[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:PutObject",
        ]
        Resource = [
          var.raw_bucket_arn,
          "${var.raw_bucket_arn}/raw/source=${each.key}/*",
          "${var.raw_bucket_arn}/errors/source=${each.key}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = var.kms_key_arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:PutLogEvents",
          "logs:CreateLogStream",
        ]
        Resource = "*"
      },
    ]
  })
}

# ─── CloudWatch log group for Firehose error logs ────────────────────────────
resource "aws_cloudwatch_log_group" "firehose" {
  for_each          = local.sources
  name              = "/aws/kinesisfirehose/${local.prefix}-${each.key}"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_cloudwatch_log_stream" "firehose" {
  for_each       = local.sources
  name           = "S3Delivery"
  log_group_name = aws_cloudwatch_log_group.firehose[each.key].name
}

# ─── Firehose delivery streams ──────────────────────────────────────────────
resource "aws_kinesis_firehose_delivery_stream" "stream" {
  for_each    = local.sources
  name        = "${local.prefix}-${each.key}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose[each.key].arn
    bucket_arn = var.raw_bucket_arn

    prefix              = "raw/source=${each.key}/year=!{partitionKeyFromQuery:year}/month=!{partitionKeyFromQuery:month}/day=!{partitionKeyFromQuery:day}/hour=!{partitionKeyFromQuery:hour}/"
    error_output_prefix = "errors/source=${each.key}/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"

    buffering_size     = var.buffer_size_mb
    buffering_interval = var.buffer_interval_sec

    compression_format = "UNCOMPRESSED" # Parquet is internally compressed

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose[each.key].name
      log_stream_name = aws_cloudwatch_log_stream.firehose[each.key].name
    }

    dynamic "dynamic_partitioning_configuration" {
      for_each = var.enable_dynamic_partitioning ? [1] : []
      content {
        enabled = true
      }
    }

    # Extract partition keys from the JSON record
    dynamic "processing_configuration" {
      for_each = var.enable_dynamic_partitioning ? [1] : []
      content {
        enabled = true

        processors {
          type = "MetadataExtraction"
          parameters {
            parameter_name  = "JsonParsingEngine"
            parameter_value = "JQ-1.6"
          }
          parameters {
            parameter_name  = "MetadataExtractionQuery"
            parameter_value = "{year:.ts|fromdate|strftime(\"%Y\"),month:.ts|fromdate|strftime(\"%m\"),day:.ts|fromdate|strftime(\"%d\"),hour:.ts|fromdate|strftime(\"%H\")}"
          }
        }

        processors {
          type = "AppendDelimiterToRecord"
          parameters {
            parameter_name  = "Delimiter"
            parameter_value = "\\n"
          }
        }
      }
    }
  }

  server_side_encryption {
    enabled  = true
    key_type = "CUSTOMER_MANAGED_CMK"
    key_arn  = var.kms_key_arn
  }

  tags = merge(var.tags, { Name = "${local.prefix}-${each.key}", Source = each.key })
}

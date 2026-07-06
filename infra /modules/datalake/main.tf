locals {
  prefix = "${var.project}-${var.environment}"

  buckets = {
    raw           = "${local.prefix}-raw"           # per-source: raw/source=<src>/year=…/…
    processed     = "${local.prefix}-processed"     # Glue-ETL-cleaned, common-schema parquet
    features      = "${local.prefix}-features"      # SageMaker Feature Store offline + parquet
    models        = "${local.prefix}-models"        # trained model artifacts + Lambda zips
    anomalies     = "${local.prefix}-anomalies"     # detector outputs: anomalies/{detector}/year=…/
    security_lake = "${local.prefix}-security-lake" # OCSF-shaped security findings (GuardDuty, Sec Hub)
  }

  # Per-log-source raw partitions to seed in Glue
  log_sources = [
    "cloudfront", "alb", "waf", "app", "eks",
    "nginx", "kafka", "mysql", "mongodb", "redis",
    "node-metrics", "container-metrics", "prometheus", "otel-traces",
  ]
}

# ─── KMS Key for bucket encryption ───────────────────────────────────────────
resource "aws_kms_key" "datalake" {
  description             = "${local.prefix} data lake encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = merge(var.tags, { Name = "${local.prefix}-datalake-kms" })
}

resource "aws_kms_alias" "datalake" {
  name          = "alias/${local.prefix}-datalake"
  target_key_id = aws_kms_key.datalake.key_id
}

# ─── S3 Buckets ──────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "buckets" {
  for_each = local.buckets

  bucket        = each.value
  force_destroy = var.environment != "prod"

  tags = merge(var.tags, {
    Name    = each.value
    Purpose = each.key
  })
}

# Versioning on all buckets
resource "aws_s3_bucket_versioning" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.datalake.arn
    }
    bucket_key_enabled = true
  }
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle rules — raw bucket: Glacier after 90d
resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.buckets["raw"].id

  rule {
    id     = "raw-to-glacier"
    status = "Enabled"

    filter {}

    transition {
      days          = var.raw_retention_days
      storage_class = "GLACIER"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# Lifecycle rules — processed bucket: expire after 365d
resource "aws_s3_bucket_lifecycle_configuration" "processed" {
  bucket = aws_s3_bucket.buckets["processed"].id

  rule {
    id     = "processed-expire"
    status = "Enabled"

    filter {}

    expiration {
      days = var.processed_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# ─── Glue Database (Data Catalog) ────────────────────────────────────────────
resource "aws_glue_catalog_database" "main" {
  name        = replace(local.prefix, "-", "_")
  description = "Glue catalog for ${local.prefix} data lake"
}

# Glue crawler IAM role
resource "aws_iam_role" "glue_crawler" {
  name = "${local.prefix}-glue-crawler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3" {
  name = "${local.prefix}-glue-s3-access"
  role = aws_iam_role.glue_crawler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.buckets["raw"].arn,
          "${aws_s3_bucket.buckets["raw"].arn}/*",
          aws_s3_bucket.buckets["processed"].arn,
          "${aws_s3_bucket.buckets["processed"].arn}/*",
          aws_s3_bucket.buckets["anomalies"].arn,
          "${aws_s3_bucket.buckets["anomalies"].arn}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.datalake.arn
      }
    ]
  })
}

# Per-source crawler — one per log source so we get a clean Glue table each.
resource "aws_glue_crawler" "raw_per_source" {
  for_each      = toset(local.log_sources)
  name          = "${local.prefix}-raw-${each.key}-crawler"
  database_name = aws_glue_catalog_database.main.name
  role          = aws_iam_role.glue_crawler.arn
  schedule      = "cron(0 2 * * ? *)" # daily at 02:00 UTC

  s3_target {
    path = "s3://${aws_s3_bucket.buckets["raw"].bucket}/raw/source=${each.key}/"
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
    }
  })

  schema_change_policy {
    delete_behavior = "LOG"
    update_behavior = "UPDATE_IN_DATABASE"
  }

  tags = merge(var.tags, { Source = each.key })
}

# Anomalies bucket crawler — for SOC analysts querying historical anomalies via Athena
resource "aws_glue_crawler" "anomalies" {
  name          = "${local.prefix}-anomalies-crawler"
  database_name = aws_glue_catalog_database.main.name
  role          = aws_iam_role.glue_crawler.arn
  schedule      = "cron(0 3 * * ? *)"

  s3_target {
    path = "s3://${aws_s3_bucket.buckets["anomalies"].bucket}/anomalies/"
  }

  schema_change_policy {
    delete_behavior = "LOG"
    update_behavior = "UPDATE_IN_DATABASE"
  }

  tags = var.tags
}

# ─── Lake Formation (data governance) ────────────────────────────────────────
resource "aws_lakeformation_data_lake_settings" "main" {
  admins = ["arn:aws:iam::${var.account_id}:root"]
}

resource "aws_lakeformation_resource" "buckets" {
  for_each = toset(["raw", "processed", "features"])
  arn      = aws_s3_bucket.buckets[each.key].arn
}

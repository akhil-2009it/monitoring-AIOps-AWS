locals {
  prefix      = "${var.project}-${var.environment}"
  bucket_name = "${local.prefix}-cloudtrail-${var.account_id}"
}

# ─── KMS key for CloudTrail logs ─────────────────────────────────────────────
resource "aws_kms_key" "trail" {
  description             = "${local.prefix} CloudTrail log encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudTrailEncrypt"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "kms:GenerateDataKey*"
        Resource  = "*"
        Condition = {
          StringLike = { "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:aws:cloudtrail:*:${var.account_id}:trail/*" }
        }
      },
      {
        Sid       = "AllowCloudTrailDescribeKey"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "kms:DescribeKey"
        Resource  = "*"
      }
    ]
  })

  tags = var.tags
}

resource "aws_kms_alias" "trail" {
  name          = "alias/${local.prefix}-cloudtrail"
  target_key_id = aws_kms_key.trail.key_id
}

# ─── S3 bucket for CloudTrail logs ───────────────────────────────────────────
resource "aws_s3_bucket" "trail" {
  bucket        = local.bucket_name
  force_destroy = var.environment != "prod"
  tags          = merge(var.tags, { Name = local.bucket_name })
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket                  = aws_s3_bucket.trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "trail" {
  bucket = aws_s3_bucket.trail.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.trail.arn
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id
  rule {
    id     = "expire-after-1y"
    status = "Enabled"

    filter {}

    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.trail.arn
      },
      {
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.trail.arn}/AWSLogs/${var.account_id}/*"
        Condition = {
          StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" }
        }
      }
    ]
  })
}

# ─── CloudTrail ──────────────────────────────────────────────────────────────
resource "aws_cloudtrail" "main" {
  name           = "${local.prefix}-trail"
  s3_bucket_name = aws_s3_bucket.trail.id
  s3_key_prefix  = "AWSLogs"

  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  kms_key_id                    = aws_kms_key.trail.arn

  cloud_watch_logs_role_arn  = aws_iam_role.cloudtrail_cw.arn
  cloud_watch_logs_group_arn = "${aws_cloudwatch_log_group.trail.arn}:*"

  dynamic "event_selector" {
    for_each = var.include_data_events ? [1] : []
    content {
      read_write_type           = "All"
      include_management_events = true

      data_resource {
        type   = "AWS::S3::Object"
        values = ["arn:aws:s3:::${local.prefix}-*/"]
      }
    }
  }

  tags = var.tags

  depends_on = [aws_s3_bucket_policy.trail]
}

# ─── CloudWatch Logs sink (for alarms, queries) ──────────────────────────────
resource "aws_cloudwatch_log_group" "trail" {
  name              = "/aws/cloudtrail/${local.prefix}"
  retention_in_days = 90
  kms_key_id        = aws_kms_key.trail.arn
  tags              = var.tags
}

resource "aws_iam_role" "cloudtrail_cw" {
  name = "${local.prefix}-cloudtrail-cwlogs"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "cloudtrail_cw" {
  name = "${local.prefix}-cloudtrail-cwlogs"
  role = aws_iam_role.cloudtrail_cw.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.trail.arn}:*"
    }]
  })
}

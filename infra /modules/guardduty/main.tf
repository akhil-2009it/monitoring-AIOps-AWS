locals {
  prefix = "${var.project}-${var.environment}"
}

resource "aws_guardduty_detector" "main" {
  enable                       = true
  finding_publishing_frequency = "FIFTEEN_MINUTES"

  datasources {
    s3_logs {
      enable = var.enable_s3_protection
    }
    kubernetes {
      audit_logs {
        enable = var.enable_eks_protection
      }
    }
    malware_protection {
      scan_ec2_instance_with_findings {
        ebs_volumes {
          enable = var.enable_malware_protection
        }
      }
    }
  }

  tags = merge(var.tags, { Name = "${local.prefix}-guardduty" })
}

# Newer GuardDuty features (RDS, Lambda) use the v2 features API
resource "aws_guardduty_detector_feature" "rds_login" {
  count       = var.enable_rds_protection ? 1 : 0
  detector_id = aws_guardduty_detector.main.id
  name        = "RDS_LOGIN_EVENTS"
  status      = "ENABLED"
}

resource "aws_guardduty_detector_feature" "lambda_network" {
  count       = var.enable_lambda_protection ? 1 : 0
  detector_id = aws_guardduty_detector.main.id
  name        = "LAMBDA_NETWORK_LOGS"
  status      = "ENABLED"
}

resource "aws_guardduty_detector_feature" "eks_runtime" {
  count       = var.enable_eks_protection ? 1 : 0
  detector_id = aws_guardduty_detector.main.id
  name        = "EKS_RUNTIME_MONITORING"
  status      = "ENABLED"

  additional_configuration {
    name   = "EKS_ADDON_MANAGEMENT"
    status = "ENABLED"
  }
}

# ─── Findings export to S3 (optional) ────────────────────────────────────────
resource "aws_guardduty_publishing_destination" "s3" {
  count            = var.findings_export_bucket_arn != "" ? 1 : 0
  detector_id      = aws_guardduty_detector.main.id
  destination_arn  = var.findings_export_bucket_arn
  kms_key_arn      = aws_kms_key.gd[0].arn
  destination_type = "S3"

  depends_on = [aws_kms_key.gd]
}

resource "aws_kms_key" "gd" {
  count                   = var.findings_export_bucket_arn != "" ? 1 : 0
  description             = "${local.prefix} GuardDuty findings export"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowGuardDuty"
        Effect    = "Allow"
        Principal = { Service = "guardduty.amazonaws.com" }
        Action    = ["kms:GenerateDataKey"]
        Resource  = "*"
      },
      {
        Sid       = "AllowAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
    ]
  })

  tags = var.tags
}

data "aws_caller_identity" "current" {}

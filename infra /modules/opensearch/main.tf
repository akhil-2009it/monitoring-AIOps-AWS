locals {
  prefix      = "${var.project}-${var.environment}"
  domain_name = substr("${local.prefix}-aos", 0, 28) # max 28 chars
}

# ─── KMS for encryption at rest ──────────────────────────────────────────────
resource "aws_kms_key" "aos" {
  description             = "${local.domain_name} encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = var.tags
}

# ─── Security group ──────────────────────────────────────────────────────────
resource "aws_security_group" "aos" {
  name        = "${local.domain_name}-sg"
  description = "OpenSearch SG: allow HTTPS from VPC"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS to OpenSearch"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.domain_name}-sg" })
}

# ─── Master user secret ──────────────────────────────────────────────────────
resource "random_password" "master" {
  length           = 32
  special          = true
  override_special = "!@#$%&*()-_=+"
}

resource "aws_secretsmanager_secret" "master" {
  name                    = "${var.project}/${var.environment}/opensearch-master"
  description             = "OpenSearch fine-grained-access master credentials"
  recovery_window_in_days = 7
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "master" {
  secret_id = aws_secretsmanager_secret.master.id
  secret_string = jsonencode({
    username = var.master_user_name
    password = random_password.master.result
    endpoint = aws_opensearch_domain.main.endpoint
  })

  depends_on = [aws_opensearch_domain.main]
}

# ─── OpenSearch domain ───────────────────────────────────────────────────────
resource "aws_opensearch_domain" "main" {
  domain_name    = local.domain_name
  engine_version = var.engine_version

  cluster_config {
    instance_type          = var.instance_type
    instance_count         = var.instance_count
    zone_awareness_enabled = var.instance_count >= 2

    dynamic "zone_awareness_config" {
      for_each = var.instance_count >= 2 ? [1] : []
      content {
        availability_zone_count = min(var.instance_count, length(var.private_subnet_ids))
      }
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.ebs_volume_size_gb
    iops        = 3000
    throughput  = 125
  }

  vpc_options {
    subnet_ids         = slice(var.private_subnet_ids, 0, min(var.instance_count, length(var.private_subnet_ids)))
    security_group_ids = [aws_security_group.aos.id]
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = aws_kms_key.aos.arn
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = true

    master_user_options {
      master_user_name     = var.master_user_name
      master_user_password = random_password.master.result
    }
  }

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.aos_index.arn
    log_type                 = "INDEX_SLOW_LOGS"
  }
  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.aos_search.arn
    log_type                 = "SEARCH_SLOW_LOGS"
  }
  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.aos_audit.arn
    log_type                 = "AUDIT_LOGS"
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [{
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action    = "es:*"
        Resource  = "arn:aws:es:*:*:domain/${local.domain_name}/*"
      }],
      [
        for arn in var.allowed_iam_role_arns : {
          Effect    = "Allow"
          Principal = { AWS = arn }
          Action    = "es:*"
          Resource  = "arn:aws:es:*:*:domain/${local.domain_name}/*"
        }
      ],
    )
  })

  tags = merge(var.tags, { Name = local.domain_name })
}

resource "aws_cloudwatch_log_group" "aos_index" {
  name              = "/aws/opensearch/${local.domain_name}/index-slow"
  retention_in_days = 14
  tags              = var.tags
}
resource "aws_cloudwatch_log_group" "aos_search" {
  name              = "/aws/opensearch/${local.domain_name}/search-slow"
  retention_in_days = 14
  tags              = var.tags
}
resource "aws_cloudwatch_log_group" "aos_audit" {
  name              = "/aws/opensearch/${local.domain_name}/audit"
  retention_in_days = 90
  tags              = var.tags
}

resource "aws_cloudwatch_log_resource_policy" "aos" {
  policy_name = "${local.domain_name}-log-policy"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "es.amazonaws.com" }
      Action    = ["logs:PutLogEvents", "logs:CreateLogStream"]
      Resource  = "arn:aws:logs:*:*:log-group:/aws/opensearch/*"
    }]
  })
}

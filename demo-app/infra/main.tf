terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.30" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = local.common_tags }
}

data "aws_caller_identity" "current" {}

locals {
  prefix = "${var.project}-${var.environment}-demo"
  common_tags = merge(var.tags, {
    Project     = var.project
    Environment = var.environment
    Component   = "demo-app"
    ManagedBy   = "terraform"
  })
  account_id = data.aws_caller_identity.current.account_id
}

# ─── ECR repos for the 3 services ────────────────────────────────────────────
resource "aws_ecr_repository" "demo" {
  for_each = toset(["demo-api", "demo-worker", "demo-web"])
  name     = "${var.project}/${each.key}"

  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "KMS" }

  tags = merge(local.common_tags, { Name = each.key })
}

resource "aws_ecr_lifecycle_policy" "demo" {
  for_each   = aws_ecr_repository.demo
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 20 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}

# ─── RDS MySQL ────────────────────────────────────────────────────────────────
resource "random_password" "rds" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_kms_key" "rds" {
  description             = "${local.prefix} RDS encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret" "rds" {
  name                    = "${var.project}/${var.environment}/demo-app/rds-master"
  kms_key_id              = aws_kms_key.rds.arn
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "rds" {
  secret_id = aws_secretsmanager_secret.rds.id
  secret_string = jsonencode({
    username = "demo"
    password = random_password.rds.result
    engine   = "mysql"
    host     = aws_db_instance.demo.address
    port     = 3306
    dbname   = "demoapp"
  })
  depends_on = [aws_db_instance.demo]
}

resource "aws_db_subnet_group" "demo" {
  name       = "${local.prefix}-mysql-subnet-group"
  subnet_ids = var.private_subnet_ids
  tags       = local.common_tags
}

resource "aws_security_group" "rds" {
  name        = "${local.prefix}-mysql-sg"
  description = "Demo RDS — allow MySQL from EKS nodes only"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [var.eks_node_security_group_id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.common_tags
}

resource "aws_db_parameter_group" "demo" {
  name   = "${local.prefix}-mysql-params"
  family = "mysql8.0"

  # Slow-query log enabled — > 0.5s queries get logged.
  parameter {
    name  = "slow_query_log"
    value = "1"
  }
  parameter {
    name  = "long_query_time"
    value = "0.5"
  }
  parameter {
    name  = "log_output"
    value = "FILE"
  }
  parameter {
    name  = "general_log"
    value = "0" # noisy; off by default
  }
}

resource "aws_db_instance" "demo" {
  identifier        = "${local.prefix}-mysql"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = var.rds_instance_class
  allocated_storage = var.rds_allocated_storage

  db_name  = "demoapp"
  username = "demo"
  password = random_password.rds.result

  db_subnet_group_name   = aws_db_subnet_group.demo.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.demo.name

  storage_encrypted = true
  kms_key_id        = aws_kms_key.rds.arn

  multi_az              = var.environment == "prod"
  storage_type          = "gp3"
  max_allocated_storage = 100

  backup_retention_period = 7
  publicly_accessible     = false
  deletion_protection     = var.environment == "prod"
  skip_final_snapshot     = var.environment != "prod"

  # Export slow-query + error logs to CloudWatch — that's how they reach Firehose.
  enabled_cloudwatch_logs_exports = ["error", "slowquery"]

  tags = merge(local.common_tags, { Name = "${local.prefix}-mysql" })

  lifecycle {
    ignore_changes = [password]
  }
}

# ─── CloudWatch → Firehose subscription for slow-query log ───────────────────
# RDS writes slow-query log to CloudWatch under /aws/rds/instance/<id>/slowquery.
# The subscription forwards every log line to the monitoring-mlops mysql Firehose.

data "aws_iam_policy_document" "cwlogs_to_firehose_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cwlogs_to_firehose" {
  name               = "${local.prefix}-cwlogs-to-firehose"
  assume_role_policy = data.aws_iam_policy_document.cwlogs_to_firehose_assume.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "cwlogs_to_firehose" {
  name = "${local.prefix}-cwlogs-to-firehose"
  role = aws_iam_role.cwlogs_to_firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["firehose:PutRecord", "firehose:PutRecordBatch"]
      Resource = "arn:aws:firehose:${var.aws_region}:${local.account_id}:deliverystream/${var.firehose_app_stream_name}"
    }]
  })
}

# Wait for RDS to start writing logs — log group is auto-created on first write.
# We create the group ourselves so the subscription can attach immediately.
resource "aws_cloudwatch_log_group" "rds_slow" {
  name              = "/aws/rds/instance/${aws_db_instance.demo.identifier}/slowquery"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_subscription_filter" "rds_slow_to_firehose" {
  name            = "${local.prefix}-rds-slow-to-firehose"
  log_group_name  = aws_cloudwatch_log_group.rds_slow.name
  filter_pattern  = "" # all events
  destination_arn = "arn:aws:firehose:${var.aws_region}:${local.account_id}:deliverystream/${var.firehose_app_stream_name}"
  role_arn        = aws_iam_role.cwlogs_to_firehose.arn

  depends_on = [aws_iam_role_policy.cwlogs_to_firehose]
}

# ─── Redis (for the worker queue) — ElastiCache ──────────────────────────────
resource "aws_security_group" "redis" {
  name        = "${local.prefix}-redis-sg"
  description = "Redis — allow from EKS nodes"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [var.eks_node_security_group_id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.common_tags
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${local.prefix}-redis"
  subnet_ids = var.private_subnet_ids
  tags       = local.common_tags
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${local.prefix}-redis"
  description                = "${local.prefix} Redis (worker queue)"
  engine                     = "redis"
  node_type                  = "cache.t3.micro"
  num_cache_clusters         = 1
  parameter_group_name       = "default.redis7"
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = false # toggle on if your client supports TLS to ElastiCache
  automatic_failover_enabled = false
  tags                       = local.common_tags
}

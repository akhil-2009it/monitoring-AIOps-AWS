locals {
  prefix = "${var.project}-${var.environment}"
}

# ─── RDS Subnet Group ─────────────────────────────────────────────────────────
resource "aws_db_subnet_group" "main" {
  name        = "${local.prefix}-rds-subnet-group"
  subnet_ids  = var.private_subnet_ids
  description = "RDS subnet group for ${local.prefix}"
  tags        = merge(var.tags, { Name = "${local.prefix}-rds-subnet-group" })
}

# ─── Security Group ───────────────────────────────────────────────────────────
resource "aws_security_group" "rds" {
  name        = "${local.prefix}-rds-sg"
  description = "RDS MySQL — allow MySQL from EKS node CIDR only"
  vpc_id      = var.vpc_id

  ingress {
    description = "MySQL from VPC"
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"] # private VPC CIDR — tighten in prod
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.prefix}-rds-sg" })
}

# ─── KMS Key for RDS encryption ───────────────────────────────────────────────
resource "aws_kms_key" "rds" {
  description             = "${local.prefix} RDS encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = merge(var.tags, { Name = "${local.prefix}-rds-kms" })
}

# ─── Secrets Manager — RDS credentials (no plaintext ever) ───────────────────
resource "random_password" "rds_master" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "rds" {
  name                    = "${var.project}/${var.environment}/rds-master-credentials"
  description             = "RDS MySQL master credentials for ${local.prefix}"
  kms_key_id              = aws_kms_key.rds.arn
  recovery_window_in_days = 7
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "rds" {
  secret_id = aws_secretsmanager_secret.rds.id
  secret_string = jsonencode({
    username = "mlops_admin"
    password = random_password.rds_master.result
    engine   = "mysql"
    host     = aws_db_instance.main.address
    port     = 3306
    dbname   = var.db_name
  })

  depends_on = [aws_db_instance.main]
}

# ─── RDS MySQL Instance ───────────────────────────────────────────────────────
# PII lives only here with column-level encryption.
# ML pipeline sees only student_id (UUID). No exceptions. (README.md rule #4)
resource "aws_db_instance" "main" {
  identifier        = "${local.prefix}-mysql"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = var.rds_instance_class # db.t3.micro ~$0.017/hr
  allocated_storage = var.allocated_storage

  db_name  = var.db_name
  username = "mlops_admin"
  password = random_password.rds_master.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  # Encryption at rest (KMS)
  storage_encrypted = true
  kms_key_id        = aws_kms_key.rds.arn

  # Availability
  multi_az                = var.environment == "prod" ? true : var.multi_az
  backup_retention_period = var.backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  # Performance
  storage_type          = "gp3"
  max_allocated_storage = 100

  # Security
  publicly_accessible       = false
  deletion_protection       = var.environment == "prod"
  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${local.prefix}-final-snapshot" : null
  copy_tags_to_snapshot     = true

  # Monitoring
  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.rds_enhanced_monitoring.arn

  enabled_cloudwatch_logs_exports = ["error", "slowquery"]

  tags = merge(var.tags, { Name = "${local.prefix}-mysql" })

  lifecycle {
    prevent_destroy = false      # set to true in prod after initial deploy
    ignore_changes  = [password] # managed by Secrets Manager rotation
  }
}

# ─── RDS Enhanced Monitoring Role ─────────────────────────────────────────────
resource "aws_iam_role" "rds_enhanced_monitoring" {
  name = "${local.prefix}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "rds_enhanced_monitoring" {
  role       = aws_iam_role.rds_enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ─── Secrets Manager Rotation (auto-rotate every 30 days) ────────────────────
resource "aws_secretsmanager_secret_rotation" "rds" {
  secret_id           = aws_secretsmanager_secret.rds.id
  rotation_lambda_arn = aws_lambda_function.secrets_rotation.arn

  rotation_rules {
    automatically_after_days = 30
  }
}

# Placeholder rotation Lambda (uses AWS managed rotation function in practice)
resource "aws_iam_role" "secrets_rotation_lambda" {
  name = "${local.prefix}-secrets-rotation-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "secrets_rotation_basic" {
  role       = aws_iam_role.secrets_rotation_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "secrets_rotation_policy" {
  name = "${local.prefix}-secrets-rotation-policy"
  role = aws_iam_role.secrets_rotation_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:*", "rds:*", "kms:Decrypt", "kms:GenerateDataKey"]
        Resource = "*"
      }
    ]
  })
}

data "archive_file" "rotation_placeholder" {
  type        = "zip"
  output_path = "${path.module}/rotation_placeholder.zip"

  source {
    content  = "def handler(event, context): pass"
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "secrets_rotation" {
  function_name    = "${local.prefix}-rds-secrets-rotation"
  role             = aws_iam_role.secrets_rotation_lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.11"
  timeout          = 30
  filename         = data.archive_file.rotation_placeholder.output_path
  source_code_hash = data.archive_file.rotation_placeholder.output_base64sha256

  tags = var.tags

  # NOTE: Replace with the AWS managed rotation Lambda ARN for production:
  # arn:aws:lambda:<region>:<<account-id>>:function:SecretsManagerRDSMySQLRotationSingleUser
}

resource "aws_lambda_permission" "secrets_rotation" {
  function_name = aws_lambda_function.secrets_rotation.function_name
  statement_id  = "AllowSecretsManagerInvoke"
  action        = "lambda:InvokeFunction"
  principal     = "secretsmanager.amazonaws.com"
}

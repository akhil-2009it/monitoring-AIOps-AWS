locals {
  prefix       = "${var.project}-${var.environment}"
  cluster_name = "${local.prefix}-msk"
}

# ─── KMS key for MSK encryption ──────────────────────────────────────────────
resource "aws_kms_key" "msk" {
  description             = "${local.cluster_name} encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = merge(var.tags, { Name = "${local.cluster_name}-kms" })
}

resource "aws_kms_alias" "msk" {
  name          = "alias/${local.cluster_name}"
  target_key_id = aws_kms_key.msk.key_id
}

# ─── Security group ──────────────────────────────────────────────────────────
resource "aws_security_group" "msk" {
  name        = "${local.cluster_name}-sg"
  description = "MSK SG: allow Kafka from VPC"
  vpc_id      = var.vpc_id

  ingress {
    description = "Kafka client (TLS)"
    from_port   = 9094
    to_port     = 9094
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
  ingress {
    description = "Kafka client (IAM)"
    from_port   = 9098
    to_port     = 9098
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
  ingress {
    description = "Zookeeper TLS (legacy clients)"
    from_port   = 2181
    to_port     = 2182
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.cluster_name}-sg" })
}

# ─── Logs ────────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "msk" {
  name              = "/aws/msk/${local.cluster_name}"
  retention_in_days = 14
  tags              = var.tags
}

# ─── Cluster configuration ──────────────────────────────────────────────────
resource "aws_msk_configuration" "main" {
  name              = "${local.cluster_name}-config"
  kafka_versions    = [var.kafka_version]
  server_properties = <<-PROPS
    auto.create.topics.enable=false
    default.replication.factor=3
    min.insync.replicas=2
    num.partitions=6
    log.retention.hours=72
    log.segment.bytes=1073741824
    unclean.leader.election.enable=false
    delete.topic.enable=true
  PROPS
}

# ─── MSK cluster ─────────────────────────────────────────────────────────────
resource "aws_msk_cluster" "main" {
  cluster_name           = local.cluster_name
  kafka_version          = var.kafka_version
  number_of_broker_nodes = var.broker_count

  broker_node_group_info {
    instance_type   = var.broker_instance_type
    client_subnets  = var.private_subnet_ids
    security_groups = [aws_security_group.msk.id]
    storage_info {
      ebs_storage_info {
        volume_size = var.ebs_volume_size_gb
      }
    }
  }

  encryption_info {
    encryption_at_rest_kms_key_arn = aws_kms_key.msk.arn
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  client_authentication {
    sasl {
      iam = var.client_authentication_iam
    }
    tls {}
  }

  configuration_info {
    arn      = aws_msk_configuration.main.arn
    revision = aws_msk_configuration.main.latest_revision
  }

  open_monitoring {
    prometheus {
      jmx_exporter {
        enabled_in_broker = true
      }
      node_exporter {
        enabled_in_broker = true
      }
    }
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk.name
      }
    }
  }

  tags = merge(var.tags, { Name = local.cluster_name })

  lifecycle {
    ignore_changes = [
      # Broker scale-up requires a separate API call sequence.
      number_of_broker_nodes,
    ]
  }
}

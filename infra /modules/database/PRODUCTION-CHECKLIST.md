# Database (RDS MySQL) — Production Checklist

## What this module creates
- RDS MySQL 8.0, KMS encrypted, in private subnets
- Multi-AZ enabled automatically when `environment == prod`
- Secrets Manager secret with auto-rotation Lambda (placeholder)
- Enhanced monitoring role
- Backup window 03:00-04:00 UTC; maintenance Mon 04:00-05:00 UTC

## Pre-apply gates
- [ ] **Storage**: `gp3` (already set), starts at 20 GB, autoscale to 100 GB. For prod, raise `max_allocated_storage` per usage forecast.
- [ ] **Multi-AZ**: auto-on in prod. Confirm in plan output. Adds 100% to compute cost.
- [ ] **`backup_retention_days = 7`** default — for compliance set to 30+ in prod. Each day costs ~storage cost × days.
- [ ] **`deletion_protection`**: auto-on in prod. Confirm in plan.
- [ ] **`skip_final_snapshot`**: auto-off in prod (a final snapshot will be created). Verify the `final_snapshot_identifier` is unique each apply.
- [ ] **`storage_encrypted = true`** with custom KMS — already set. Note: enabling encryption on an existing unencrypted DB requires a snapshot copy + restore.
- [ ] **Performance Insights**: not enabled. For prod debugging, add `performance_insights_enabled = true`, `performance_insights_kms_key_id`, `performance_insights_retention_period = 7` (free tier).
- [ ] **Slow query log** export enabled — already set. Ensure CloudWatch retention is set on `/aws/rds/instance/<id>/slowquery`.
- [ ] **Security group** allows MySQL from `10.0.0.0/16`. Tighten to specific EKS node SG ID in prod. The current rule grants any pod in the VPC access.
- [ ] **Public accessibility = false** — already set.
- [ ] **Master password rotation Lambda is a placeholder** (`def handler: pass`). Replace with the AWS-managed function `SecretsManagerRDSMySQLRotationSingleUser` ARN before relying on rotation.
- [ ] **Read replicas** — not created. For prod read scaling, add `aws_db_instance` with `replicate_source_db`.
- [ ] **PII column encryption** — application-level: use AES-GCM with a KMS DEK for `email`, `name`. Not handled by RDS-at-rest encryption alone (which protects volume, not column-level).

## Cost
- `db.t3.micro` Single-AZ: $0.017/hr ≈ **$12/month** + storage
- `db.t3.micro` Multi-AZ: ~$25/month
- Storage gp3: $0.115/GB-month
- Backups: same rate × retention days; first 100% free of allocated storage

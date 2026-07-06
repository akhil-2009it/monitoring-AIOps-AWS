output "resource_arn" { value = aws_db_instance.main.arn }
output "resource_name" { value = aws_db_instance.main.identifier }
output "resource_id" { value = aws_db_instance.main.id }

output "rds_endpoint" {
  description = "RDS MySQL endpoint (host:port)"
  value       = "${aws_db_instance.main.address}:${aws_db_instance.main.port}"
  sensitive   = true
}

output "rds_address" {
  value     = aws_db_instance.main.address
  sensitive = true
}

output "rds_port" {
  value = aws_db_instance.main.port
}

output "rds_secret_arn" {
  description = "Secrets Manager ARN for RDS master credentials"
  value       = aws_secretsmanager_secret.rds.arn
}

output "rds_security_group_id" {
  value = aws_security_group.rds.id
}

output "rds_kms_key_arn" {
  value = aws_kms_key.rds.arn
}

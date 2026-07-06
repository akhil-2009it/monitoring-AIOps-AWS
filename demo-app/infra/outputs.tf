output "ecr_repos" {
  value = { for k, v in aws_ecr_repository.demo : k => v.repository_url }
}

output "rds_endpoint" {
  value     = aws_db_instance.demo.address
  sensitive = true
}

output "rds_secret_arn" {
  value = aws_secretsmanager_secret.rds.arn
}

output "redis_endpoint" {
  value = aws_elasticache_replication_group.redis.primary_endpoint_address
}

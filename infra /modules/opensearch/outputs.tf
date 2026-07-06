output "domain_arn" {
  value = aws_opensearch_domain.main.arn
}

output "domain_endpoint" {
  value = aws_opensearch_domain.main.endpoint
}

output "domain_name" {
  value = aws_opensearch_domain.main.domain_name
}

output "kibana_endpoint" {
  value = aws_opensearch_domain.main.dashboard_endpoint
}

output "master_secret_arn" {
  value = aws_secretsmanager_secret.master.arn
}

output "security_group_id" {
  value = aws_security_group.aos.id
}

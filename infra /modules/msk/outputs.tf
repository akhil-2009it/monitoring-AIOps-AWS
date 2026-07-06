output "cluster_arn" {
  value = aws_msk_cluster.main.arn
}

output "bootstrap_brokers_tls" {
  value = aws_msk_cluster.main.bootstrap_brokers_tls
}

output "bootstrap_brokers_sasl_iam" {
  value = aws_msk_cluster.main.bootstrap_brokers_sasl_iam
}

output "zookeeper_connect_string_tls" {
  value = aws_msk_cluster.main.zookeeper_connect_string_tls
}

output "security_group_id" {
  value = aws_security_group.msk.id
}

output "kms_key_arn" {
  value = aws_kms_key.msk.arn
}

output "resource_arn" { value = aws_iam_role.sagemaker_exec.arn }
output "resource_name" { value = aws_iam_role.sagemaker_exec.name }
output "resource_id" { value = aws_iam_role.sagemaker_exec.id }

output "sagemaker_exec_role_arn" {
  description = "SageMaker execution role ARN — use in all pipelines and endpoints"
  value       = aws_iam_role.sagemaker_exec.arn
}

output "sagemaker_exec_role_name" {
  value = aws_iam_role.sagemaker_exec.name
}

output "log_feature_group_name" {
  value = aws_sagemaker_feature_group.log_features.feature_group_name
}

output "metric_feature_group_name" {
  value = aws_sagemaker_feature_group.metric_features.feature_group_name
}

output "log_feature_group_arn" {
  value = aws_sagemaker_feature_group.log_features.arn
}

output "metric_feature_group_arn" {
  value = aws_sagemaker_feature_group.metric_features.arn
}

output "model_registry_groups" {
  description = "Map of model key → model group name"
  value       = { for k, v in aws_sagemaker_model_package_group.groups : k => v.model_package_group_name }
}

output "sagemaker_config_secret_arn" {
  value = aws_secretsmanager_secret.sagemaker_config.arn
}

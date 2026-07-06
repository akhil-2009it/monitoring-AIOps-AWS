# ─── Account & Region ─────────────────────────────────────────────────────────
output "account_id" {
  description = "AWS account ID"
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "AWS region"
  value       = var.aws_region
}

# ─── VPC ──────────────────────────────────────────────────────────────────────
output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnets
}

# ─── Data Lake ────────────────────────────────────────────────────────────────
output "raw_bucket_name" {
  description = "S3 raw events bucket"
  value       = module.datalake.raw_bucket_name
}

output "processed_bucket_name" {
  description = "S3 processed data bucket"
  value       = module.datalake.processed_bucket_name
}

output "features_bucket_name" {
  description = "S3 Feature Store offline bucket"
  value       = module.datalake.features_bucket_name
}

output "models_bucket_name" {
  description = "S3 model artifacts bucket"
  value       = module.datalake.models_bucket_name
}

# ─── Streaming ────────────────────────────────────────────────────────────────
output "kinesis_stream_name" {
  description = "Kinesis stream for student events"
  value       = module.streaming.kinesis_stream_name
}

output "kinesis_stream_arn" {
  description = "Kinesis stream ARN"
  value       = module.streaming.kinesis_stream_arn
}

# ─── SageMaker ────────────────────────────────────────────────────────────────
output "sagemaker_exec_role_arn" {
  description = "SageMaker execution role ARN — use in all pipeline and endpoint configs"
  value       = module.sagemaker.sagemaker_exec_role_arn
}

output "log_feature_group_name" {
  value = module.sagemaker.log_feature_group_name
}

output "metric_feature_group_name" {
  value = module.sagemaker.metric_feature_group_name
}

# ─── AIOps platform outputs ──────────────────────────────────────────────────
output "opensearch_endpoint" {
  value     = module.opensearch.domain_endpoint
  sensitive = true
}

output "opensearch_master_secret_arn" {
  value = module.opensearch.master_secret_arn
}

output "msk_bootstrap_brokers_iam" {
  value     = module.msk.bootstrap_brokers_sasl_iam
  sensitive = true
}

output "amp_remote_write_url" {
  value = module.amp.remote_write_url
}

output "amg_workspace_url" {
  value = module.amg.workspace_url
}

output "guardduty_detector_id" {
  value = module.guardduty.detector_id
}

output "anomalies_bucket_name" {
  value = module.datalake.anomalies_bucket_name
}

output "firehose_streams" {
  value = module.firehose.stream_names
}

output "model_registry_groups" {
  description = "Model Registry model group names"
  value       = module.sagemaker.model_registry_groups
}

# ─── EKS ──────────────────────────────────────────────────────────────────────
output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS API server endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_arn" {
  description = "EKS cluster ARN"
  value       = module.eks.cluster_arn
}

output "eks_kubeconfig_command" {
  description = "Run this to update kubeconfig"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name} --profile mlops-learning"
}

# ─── Database ─────────────────────────────────────────────────────────────────
output "rds_endpoint" {
  description = "RDS MySQL endpoint"
  value       = module.database.rds_endpoint
  sensitive   = true
}

output "rds_secret_arn" {
  description = "Secrets Manager ARN for RDS credentials"
  value       = module.database.rds_secret_arn
}

# ─── CI/CD ────────────────────────────────────────────────────────────────────
output "codepipeline_name" {
  description = "Model promotion CodePipeline name"
  value       = module.cicd.codepipeline_name
}

# ─── Cognito ──────────────────────────────────────────────────────────────────
output "cognito_user_pool_id" {
  description = "Cognito User Pool ID — set as MLOPS_COGNITO_POOL_ID in API"
  value       = module.cognito.user_pool_id
}

output "cognito_user_pool_arn" {
  value = module.cognito.user_pool_arn
}

output "cognito_client_id" {
  value = module.cognito.client_id
}

output "cognito_hosted_ui_url" {
  value = module.cognito.hosted_ui_url
}

# ─── ALB ─────────────────────────────────────────────────────────────────────
output "api_alb_dns_name" {
  description = "ALB DNS name. Empty when ALB module is skipped (no api_hostname/acm_certificate_arn)."
  value       = length(module.alb) > 0 ? module.alb[0].alb_dns_name : ""
}

output "api_target_group_arn" {
  description = "Target group ARN to wire from EKS via TargetGroupBinding"
  value       = length(module.alb) > 0 ? module.alb[0].target_group_arn : ""
}

# ─── WAF / CloudTrail / Billing ──────────────────────────────────────────────
output "waf_web_acl_arn" { value = module.waf.web_acl_arn }
output "cloudtrail_arn" { value = module.cloudtrail.trail_arn }
output "billing_sns_arn" { value = module.billing.sns_topic_arn }

# ─── Quick reference ──────────────────────────────────────────────────────────
output "quick_reference" {
  description = "Copy-paste ARNs for ML pipeline configuration"
  value = {
    data_lake_bucket     = module.datalake.raw_bucket_name
    feature_store_bucket = module.datalake.features_bucket_name
    sagemaker_role       = module.sagemaker.sagemaker_exec_role_arn
    kinesis_stream       = module.streaming.kinesis_stream_arn
    eks_cluster          = module.eks.cluster_name
  }
}

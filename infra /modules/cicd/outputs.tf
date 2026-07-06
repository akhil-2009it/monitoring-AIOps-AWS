output "resource_arn" { value = values(aws_codepipeline.model_promotion)[0].arn }
output "resource_name" { value = values(aws_codepipeline.model_promotion)[0].name }
output "resource_id" { value = values(aws_codepipeline.model_promotion)[0].id }

output "codepipeline_name" {
  description = "Primary model promotion pipeline name (perf-predictor)"
  value       = aws_codepipeline.model_promotion["perf-predictor"].name
}

output "codepipeline_arns" {
  description = "All model promotion pipeline ARNs"
  value       = { for k, v in aws_codepipeline.model_promotion : k => v.arn }
}

output "pipeline_artifacts_bucket" {
  value = aws_s3_bucket.pipeline_artifacts.bucket
}

output "codebuild_role_arn" {
  value = aws_iam_role.codebuild.arn
}

output "trail_arn" { value = aws_cloudtrail.main.arn }
output "log_group_name" { value = aws_cloudwatch_log_group.trail.name }
output "log_group_arn" { value = aws_cloudwatch_log_group.trail.arn }
output "kms_key_arn" { value = aws_kms_key.trail.arn }
output "logs_bucket_name" { value = aws_s3_bucket.trail.id }

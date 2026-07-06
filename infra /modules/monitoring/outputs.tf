output "resource_arn" { value = aws_sns_topic.alerts.arn }
output "resource_name" { value = aws_sns_topic.alerts.name }
output "resource_id" { value = aws_sns_topic.alerts.id }

output "alerts_sns_topic_arn" { value = aws_sns_topic.alerts.arn }
output "retrain_lambda_arn" { value = aws_lambda_function.retrain_trigger.arn }
output "dashboard_name" { value = aws_cloudwatch_dashboard.mlops.dashboard_name }

output "alarm_arns" {
  description = "Map of all alarm names to ARNs"
  value = merge(
    { "kinesis-consumer-lag" = aws_cloudwatch_metric_alarm.kinesis_consumer_lag.arn },
    { "feature-drift-engagement" = aws_cloudwatch_metric_alarm.feature_drift_engagement.arn },
    { for k, v in aws_cloudwatch_metric_alarm.endpoint_latency_p99 : "latency-${k}" => v.arn },
    { for k, v in aws_cloudwatch_metric_alarm.endpoint_error_rate : "errors-${k}" => v.arn }
  )
}

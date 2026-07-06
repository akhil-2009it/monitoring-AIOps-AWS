output "stream_arns" {
  value = { for k, v in aws_kinesis_firehose_delivery_stream.stream : k => v.arn }
}

output "stream_names" {
  value = { for k, v in aws_kinesis_firehose_delivery_stream.stream : k => v.name }
}

output "role_arns" {
  value = { for k, v in aws_iam_role.firehose : k => v.arn }
}

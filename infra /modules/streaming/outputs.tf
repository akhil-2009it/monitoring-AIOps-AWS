output "resource_arn" { value = aws_kinesis_stream.events.arn }
output "resource_name" { value = aws_kinesis_stream.events.name }
output "resource_id" { value = aws_kinesis_stream.events.id }

output "kinesis_stream_name" { value = aws_kinesis_stream.events.name }
output "kinesis_stream_arn" { value = aws_kinesis_stream.events.arn }

output "dlq_url" { value = aws_sqs_queue.dlq.id }
output "dlq_arn" { value = aws_sqs_queue.dlq.arn }

output "lambda_consumer_name" { value = aws_lambda_function.kinesis_consumer.function_name }
output "lambda_consumer_arn" { value = aws_lambda_function.kinesis_consumer.arn }

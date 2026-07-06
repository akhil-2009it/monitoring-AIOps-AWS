locals {
  prefix      = "${var.project}-${var.environment}"
  stream_name = "${local.prefix}-events"
}

# ─── Kinesis Data Stream ──────────────────────────────────────────────────────
resource "aws_kinesis_stream" "events" {
  name             = local.stream_name
  shard_count      = var.kinesis_shard_count
  retention_period = var.kinesis_retention_hours

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  encryption_type = "KMS"
  kms_key_id      = "alias/aws/kinesis"

  tags = merge(var.tags, { Name = local.stream_name })
}

# ─── SQS Dead-Letter Queue ───────────────────────────────────────────────────
resource "aws_sqs_queue" "dlq" {
  name                      = "${local.prefix}-events-dlq"
  message_retention_seconds = 1209600 # 14 days

  kms_master_key_id                 = "alias/aws/sqs"
  kms_data_key_reuse_period_seconds = 300

  tags = merge(var.tags, { Name = "${local.prefix}-events-dlq" })
}

resource "aws_sqs_queue_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.dlq.arn
    }]
  })
}

# ─── Lambda IAM Role ─────────────────────────────────────────────────────────
resource "aws_iam_role" "lambda_consumer" {
  name = "${local.prefix}-kinesis-consumer-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_consumer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_kinesis_s3" {
  name = "${local.prefix}-lambda-kinesis-s3"
  role = aws_iam_role.lambda_consumer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:DescribeStreamSummary",
          "kinesis:ListShards",
          "kinesis:ListStreams"
        ]
        Resource = aws_kinesis_stream.events.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:PutObjectAcl"]
        Resource = "arn:aws:s3:::${var.raw_bucket_name}/student_events/*"
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.dlq.arn
      },
      {
        Effect = "Allow"
        Action = [
          "sagemaker:PutRecord",
          "featurestore-runtime:PutRecord"
        ]
        Resource = "*"
      }
    ]
  })
}

# ─── Lambda Function (Kinesis → S3 + Feature Store) ──────────────────────────
# The actual code is zipped and deployed via CI/CD.
# For bootstrap, we use an inline placeholder that logs events.
data "archive_file" "lambda_placeholder" {
  type        = "zip"
  output_path = "${path.module}/lambda_placeholder.zip"

  source {
    content  = <<-PYTHON
      import json, base64, boto3, os, datetime

      s3 = boto3.client('s3')
      BUCKET = os.environ['RAW_BUCKET']
      FEATURE_GROUP = os.environ['FEATURE_GROUP_NAME']

      def handler(event, context):
          records = []
          for r in event['Records']:
              payload = json.loads(base64.b64decode(r['kinesis']['data']))
              records.append(payload)

          # Write batch to S3 raw partition
          key = f"student_events/year={datetime.datetime.utcnow().year}/" \
                f"month={datetime.datetime.utcnow().month:02d}/" \
                f"day={datetime.datetime.utcnow().day:02d}/" \
                f"{context.aws_request_id}.json"
          s3.put_object(
              Bucket=BUCKET,
              Key=key,
              Body=json.dumps(records),
              ContentType='application/json'
          )
          print(f"Wrote {len(records)} records to s3://{BUCKET}/{key}")
          return {"statusCode": 200, "body": f"Processed {len(records)} records"}
      PYTHON
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "kinesis_consumer" {
  function_name = "${local.prefix}-kinesis-consumer"
  role          = aws_iam_role.lambda_consumer.arn
  handler       = "handler.handler"
  runtime       = "python3.11"
  timeout       = var.lambda_timeout_sec
  memory_size   = var.lambda_memory_mb

  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256

  environment {
    variables = {
      RAW_BUCKET         = var.raw_bucket_name
      FEATURE_GROUP_NAME = "${var.project}-student-features-v1"
      ENVIRONMENT        = var.environment
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  tracing_config {
    mode = "Active"
  }

  tags = merge(var.tags, { Name = "${local.prefix}-kinesis-consumer" })
}

# ─── Lambda Event Source Mapping ─────────────────────────────────────────────
resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn               = aws_kinesis_stream.events.arn
  function_name                  = aws_lambda_function.kinesis_consumer.arn
  starting_position              = "LATEST"
  batch_size                     = var.batch_size
  bisect_batch_on_function_error = true

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.dlq.arn
    }
  }
}

# ─── CloudWatch Log Group ─────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "lambda_consumer" {
  name              = "/aws/lambda/${aws_lambda_function.kinesis_consumer.function_name}"
  retention_in_days = 14
  tags              = var.tags
}

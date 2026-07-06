# Streaming (Kinesis + Lambda) — Production Checklist

## What this module creates
- Kinesis Data Stream (provisioned mode, KMS encrypted)
- Lambda consumer with placeholder code (writes batches to S3)
- SQS DLQ with 14-day retention
- Lambda IAM role with scoped Kinesis + S3 + Feature Store permissions
- Event source mapping with bisect-on-failure

## Pre-apply gates
- [ ] **`kinesis_shard_count`** sized for peak ingestion. Each shard handles 1 MB/sec write or 1000 records/sec. For 500K students × 30 events/day spread over peak hours, 2 shards is enough. Recompute for your actual load.
- [ ] **Stream mode = PROVISIONED**. Switch to ON_DEMAND if traffic is bursty/unpredictable; you trade fixed cost for per-request pricing.
- [ ] **`retention_period` (default 48h)** — extend up to 8760h ($/shard-hour). 168h (7d) is a common compromise for replay.
- [ ] **Lambda placeholder code** — `data.archive_file.lambda_placeholder` writes plain JSON to S3 only. Replace with real consumer that:
  - Validates schema (Avro/JSON Schema)
  - Strips PII before write
  - Calls `featurestore-runtime:PutRecord` for online store
  - Sends parse failures to DLQ explicitly (not just on Lambda crash)
- [ ] **`kms_key_id = "alias/aws/kinesis"`** uses the AWS-managed key. For prod, create a customer-managed KMS key (CMK) so you control rotation/access.
- [ ] **Bisect on function error = true** — already set; means a poison-pill record won't block the entire shard.
- [ ] **Reserved concurrency** on the Lambda (not currently set) — without it, a Kinesis backlog can saturate your account's Lambda concurrency.
- [ ] **CloudWatch alarms**: `IteratorAgeMilliseconds` > 5min, Lambda `Errors` > N, DLQ `ApproximateNumberOfMessagesVisible` > 0.
- [ ] **DLQ has subscriber** (Lambda or SNS). Currently only allows Lambda send; add a CloudWatch alarm + SNS so messages don't sit unnoticed.

## Cost
- Provisioned Kinesis: $0.015/shard-hour ≈ $11/shard/month + $0.014/million PUT records
- 2 shards = ~$22/month base
- Lambda: $0.20/million invocations + $0.0000167/GB-second

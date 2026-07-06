# Firehose — Production Checklist

## What this module creates
- Per-source Firehose delivery streams (cloudfront, alb, waf, app, eks, nginx, mysql)
- Each writes Parquet (uncompressed; Parquet is self-compressed) to `raw/source=<src>/year=…/month=…/day=…/hour=…/`
- Per-source IAM role + KMS-encrypted destination
- CloudWatch error logs per stream
- Dynamic partitioning by event timestamp

## Pre-apply gates
- [ ] **`buffer_size_mb` (default 64)** — smaller = lower latency to S3, more PUT requests / cost. 64 MB / 5 min is the sweet spot for most logs.
- [ ] **`enable_dynamic_partitioning = true`** — costs $0.020/GB but partition pruning saves ~10x in Athena.
- [ ] **CloudFront** logging is configured separately (CloudFront → S3 directly is cheaper); only use Firehose if you need cross-account routing.
- [ ] **WAF** logs need WAF→Firehose configured at the WAF ACL level (not in this module).
- [ ] **EKS** uses CloudWatch Logs subscription → this Firehose; configure the subscription filter outside this module.
- [ ] **MSK** sources (app, nginx, kafka, mongo, redis) bypass Firehose; they use Kafka Connect → S3 sink. This module only covers AWS-managed streams.
- [ ] Per-source role policies scope writes to the source's prefix only — verify in IAM Access Analyzer.
- [ ] Destination bucket KMS key is shared (single CMK from `datalake` module); rotate annually.

## Cost
- Firehose ingestion: $0.029 / GB
- Dynamic partitioning: + $0.020 / GB
- S3 storage: $0.023 / GB-month
- For 100 GB/day: ~$5/day

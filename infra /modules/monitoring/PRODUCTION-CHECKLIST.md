# Monitoring — Production Checklist

## What this module creates
- SNS topic `{prefix}-mlops-alerts` (with email subscription) — used by all ML alarms
- SNS topic `{prefix}-billing-alerts` (note: must be in us-east-1 for billing metrics — this module is in primary region; wire `billing` module instead)
- CloudWatch alarms:
  - Kinesis consumer iterator age > 5 min
  - Per-endpoint p99 latency > 300ms (×3 models)
  - Per-endpoint 5XX errors > 5/min (×3 models)
  - PSI drift > 0.20 on `engagement_score`
- CloudWatch dashboard
- EventBridge rules: drift alarm → Lambda → start retrain pipeline
- Retrain Lambda

## Pre-apply gates
- [ ] **`var.billing_alert_email`** in `variables.tf` is hardcoded as default. Replace with a team distribution list (e.g. `oncall@yourcompany.com`).
- [ ] **`SNS topic` is unencrypted by default** — add `kms_master_key_id = "alias/aws/sns"` for prod.
- [ ] **`endpoint_p99_ms = 300`** — matches API SLO. Note: `ModelLatency` is endpoint-only; the API SLO is end-to-end. Add an additional alarm on `aws_cloudwatch_metric_alarm` for the API.
- [ ] **`Invocation5XXErrors > 5/min`** — assumes ~500 rps. Lower in dev; raise in prod proportionally. Use `Invocation5XXErrors / Invocations` ratio with `Math expression` for true %.
- [ ] **PSI alarm depends on Model Monitor schedule actually running**. The `student_features` Feature Group has a placeholder schedule. Verify it emits metrics under `aws/sagemaker/Endpoints/data-metrics` namespace before relying on the alarm.
- [ ] **Retrain Lambda assumes SageMaker Pipelines exist with names `{model}-{env}-pipeline`** — they don't until `ml/pipelines/{model}/run_pipeline.py` is run once. First drift event will fail with "pipeline not found"; that's by design — retrain is idempotent and will succeed once pipelines exist.
- [ ] **EventBridge rule pattern matches `{prefix}/L7`** — only L7 (drift) alarms trigger retrain. Verify alarm name conventions match.
- [ ] **Dashboard widgets** include hardcoded model endpoint names. If you add a 4th model, add it to `local.model_endpoints`.
- [ ] **Alarm history** retention: CloudWatch keeps 14 days. For audit, send `EventBridge → Kinesis Firehose → S3` with all `CloudWatch Alarm State Change` events.
- [ ] **Composite alarms**: bundle related alarms into composites for cleaner paging (e.g. "endpoint health" = 5xx OR latency).

## Out of scope (add separately)
- API SLO burn rate alarms (multi-window multi-burn-rate, see Google SRE workbook)
- Synthetic monitoring (CloudWatch Synthetics canary hitting `/health` and `/recommendation/<test-id>`)
- Application-level metrics (this module covers only AWS-managed metrics)
- PagerDuty/Opsgenie integration — replace email subscription with HTTPS endpoint

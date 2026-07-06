# SageMaker — Production Checklist

## What this module creates
- SageMaker execution role + scoped S3/Secrets/CW policy
- 1 Feature Group (`student-features-v1`, online + offline, ~16 features)
- 3 Model Package Groups (perf-predictor, knowledge-tracing, dropout-risk)
- 1 placeholder Model Monitor schedule
- CloudWatch Log groups for all SageMaker components

## Sensitive: this module gates ALL ML inference
A mistake here can take down the Recommendation API. Read `CLAUDE.md` "Sensitive Areas" section first.

## Pre-apply gates
- [ ] **`AmazonSageMakerFullAccess`** is attached. In prod, replace with custom policy — Full Access grants `s3:*` on every bucket. Use `aws_iam_policy_document` to scope to project buckets only.
- [ ] **Feature Group online store** is enabled — confirm DynamoDB read capacity matches API QPS. SageMaker manages capacity automatically; check after first month for throttling.
- [ ] **Feature Group schema is immutable** — once created, you must create `student-features-v2` to change. Don't add a feature here without a feature_group versioning plan.
- [ ] **Model Package Groups exist for all 4 models**. The current module only creates 3 (`perf_predictor`, `knowledge_tracing`, `dropout_risk`). Add `DifficultyClassifierModelGroup` if you keep the difficulty model.
- [ ] **Model Monitor schedule has placeholder `monitoring_job_definition_name`** — `lifecycle.ignore_changes` masks the absence. The schedule won't actually run until you create the job definition (separate aws_cli step or Pipeline step).
- [ ] **Endpoint configs are intentionally NOT created here** — CodePipeline upserts them after first training. Don't add them here or the first apply will fail (no model yet).
- [ ] **VPC isolation** for endpoints (currently public). Add `vpc_config` block to `aws_sagemaker_endpoint_configuration` for prod so model traffic stays in the VPC.
- [ ] **KMS encryption on training/processing volumes**. SageMaker defaults to AWS-managed; add `volume_kms_key_id` on each TrainingJob.
- [ ] **Network isolation** mode for training (`enable_network_isolation = true`) for jobs that should not have internet access.
- [ ] **Studio domain** — not created here. Use console or a separate `aws_sagemaker_domain` module. Studio EFS persists; do not delete with the rest of the project.

## Cost (per running endpoint, 24x7)
- ml.t2.medium: $0.065/hr ≈ **$47/month per endpoint**
- ml.c5.large (knowledge tracing): $0.17/hr ≈ **$122/month**
- 3 endpoints running 24x7: ~$220-300/month minimum, before training costs
- Feature Store online: $0.013/100k writes + $0.001/100k reads + storage

## Cost-savings to consider for dev
- Use Async Inference endpoints (`ml.m5.large` only billed when invoked) — much cheaper for low-QPS dev
- Use Serverless Inference for irregular traffic
- Stop endpoints over weekends in dev (no native API; use EventBridge schedule + Lambda)

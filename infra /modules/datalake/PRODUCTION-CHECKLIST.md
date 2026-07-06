# Datalake — Production Pre-Apply Checklist

## What this module creates
- 5 KMS-encrypted, versioned, fully-blocked S3 buckets: `raw`, `processed`, `features`, `models`, `predictions`
- Glue catalog DB + crawler over `s3://<raw>/student_events/`
- Lake Formation registration for the 3 ML buckets

## Pre-apply gates
- [ ] **Bucket names are global**. The default `${project}-${environment}-{purpose}` pattern can collide with another tenant's bucket. If `terraform plan` shows naming conflicts, prefix with `${account_id}` or a random suffix.
- [ ] **`force_destroy = false`** in prod (currently set automatically when `environment = prod`). Verify in plan output.
- [ ] **`raw_retention_days` (default 90)** — confirms when raw data goes to Glacier. Glacier retrieval is $/GB and slow; if you need fast ad-hoc replay, raise to 180.
- [ ] **`processed_retention_days` (default 365)** — confirm legal retention requirements (FERPA: typically 5-7 years for student records).
- [ ] **KMS key policy** — currently uses default service principal access. For multi-account, add explicit principals to `aws_kms_key.datalake`'s `policy`.
- [ ] **Lake Formation admin** is currently `account-root`. For prod, set to specific IAM admin role(s).
- [ ] **No PII in raw events** — see `README.md` rule #4. Add CloudWatch Logs Insights query alerting on common PII patterns.
- [ ] **S3 access logging** to a separate `${prefix}-access-logs` bucket (NOT included; add as a separate small bucket).
- [ ] **Replication** to a DR region — out of scope per "no DR" answer. Add `aws_s3_bucket_replication_configuration` later for compliance.

## Cost
- 5 buckets × ~$0.023/GB-month standard. Negligible until you have hot data.
- KMS key: $1/month per key.
- Glue crawler: $0.44/DPU-hour, runs nightly → $0.44/run for ~1hr crawl.

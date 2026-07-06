# Master Production Pre-Launch Checklist — AIOps Platform

Gate to `terraform apply` against `prod`. **Every box ticked by a human reviewer.**

---

## 0. Authority & access
- [ ] Dedicated AWS account, root MFA on, no root keys
- [ ] Break-glass admin role; everything else via SSO/OIDC
- [ ] Billing alarms at $50, $100, $500, $1000 (us-east-1) — `infra /modules/billing`
- [ ] CloudTrail multi-region — `infra /modules/cloudtrail`
- [ ] GuardDuty enabled, all data sources — `infra /modules/guardduty`
- [ ] Security Hub with CIS + AWS Foundational standards — `infra /modules/securityhub`

## 1. Networking & isolation
- [ ] VPC has 3 AZs in `ap-south-1`
- [ ] OpenSearch is in-VPC only (`vpc_options` set)
- [ ] MSK is in-VPC only, brokers in private subnets
- [ ] Firehose role limited to its own S3 prefix
- [ ] EKS API endpoint `public_access_cidrs` restricted

## 2. Identity & secrets
- [ ] Cognito MFA `ON`, advanced security `ENFORCED`
- [ ] All secrets in Secrets Manager (OpenSearch master, RDS master)
- [ ] No long-lived AWS keys; GitHub Actions uses OIDC, EKS pods use IRSA
- [ ] No `*` in IAM unless documented
- [ ] WAF associated with the API ALB

## 3. Ingestion (L2)
- [ ] **Firehose** — `infra /modules/firehose/PRODUCTION-CHECKLIST.md`
- [ ] **MSK** — `infra /modules/msk/PRODUCTION-CHECKLIST.md`
- [ ] CloudFront / ALB / WAF logging configured at the *source* (not in this repo)
- [ ] Fluent Bit DaemonSet running, IRSA wired, MSK reachable
- [ ] ADOT collector running, AMP remote-write IRSA wired

## 4. Search / index (L3)
- [ ] **OpenSearch** — `infra /modules/opensearch/PRODUCTION-CHECKLIST.md`
- [ ] AD plugin detectors created via REST API after first apply (4 seed detectors)
- [ ] ISM policy attached: hot 7d → warm 30d → delete

## 5. ML detectors (L5)
- [ ] All 4 SageMaker Pipelines upserted in dev
- [ ] First training run succeeded for each detector, model registered Pending → manually approved
- [ ] Endpoints deployed; `/health` shows them in `sagemaker_endpoints`
- [ ] Baseline statistics uploaded for drift Lambda
- [ ] EventBridge `monitoring-mlops-{detector}-drift-retrain-rule` exists per detector

## 6. Application
- [ ] **API** — `api/scoring/`
- [ ] `MLOPS_AUTH_DISABLED` is unset
- [ ] Cognito IDs injected via External Secrets, not hardcoded
- [ ] Locust load test passes 500 users × 10m at p99 < 250 ms
- [ ] Helm: PDB minAvailable ≥ 2; HPA min 4 max sized to peak QPS / 100rps per pod
- [ ] NetworkPolicy default-deny verified

## 7. Edge
- [ ] **ALB** — `infra /modules/alb/PRODUCTION-CHECKLIST.md`
- [ ] **WAF** — `infra /modules/waf/PRODUCTION-CHECKLIST.md`
- [ ] HTTPS only; HTTP→HTTPS 301 verified
- [ ] WAF rate limit calibrated; anonymous IP rule in `block` mode
- [ ] DNS via Route53 alias, ACM cert auto-renewal verified

## 8. Observability
- [ ] AMP receiving metrics from ADOT
- [ ] AMG dashboards: AIOps overview, per-source ingest, per-detector precision
- [ ] OTEL traces flowing to X-Ray
- [ ] kube-prometheus-stack deployed; ServiceMonitor on the scoring API
- [ ] All 4 detector endpoints have p99 + 5xx alarms
- [ ] Drift PSI alarms exist for each detector's canary features
- [ ] Synthetic canary (`scripts/smoke_test.sh` on schedule) green for 24h

## 9. Cold-start understanding
- [ ] Stakeholders briefed: ML detectors don't fire until trained (≥ 7 days of representative data)
- [ ] Streaming statistical + GuardDuty + OpenSearch AD give Day-1 coverage
- [ ] Runbook `docs/runbooks/model-cold-start.md` rehearsed by on-call

## 10. CI/CD
- [ ] OIDC role created in AWS, no static GitHub secrets
- [ ] `terraform-apply.yml` gated by GitHub Environment with required reviewers for `prod`
- [ ] `api-ci.yml` `promote_to_prod` has 2 reviewers + 30-min wait
- [ ] Trivy scan reviewed; no unfixed CRITICAL CVEs

## 11. Operational readiness
- [ ] On-call rotation set up; primary + secondary
- [ ] Runbooks reviewed: ddos, brute-force, anomaly-storm, false-positive, cold-start
- [ ] Tabletop: simulate (a) DDoS, (b) credential stuffing, (c) detector storm, (d) model retrain triggered
- [ ] `scripts/teardown.sh` works in dev

## 12. Compliance
- [ ] All log sinks documented (PII handling, retention)
- [ ] Hashed user/IP fields where logs leave the parser
- [ ] Privacy + retention policy published
- [ ] DPIA completed for any feature that processes user-identifiable data

## 13. Cost ceiling
- [ ] Monthly budget set in `infra /modules/billing` (50/80/100/120%)
- [ ] Hard cap agreed with stakeholders
- [ ] Spot for all training; endpoints stopped over weekends in non-prod

If any box is unchecked → **do not apply to prod**. Build what's missing first.

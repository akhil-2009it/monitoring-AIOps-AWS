# End-to-End Deployment Workflow

Reference for how the `monitoring-mlops` repo goes from a laptop edit to a
running AIOps/MLOps stack in AWS. Nothing runs on the laptop except zip +
upload. Terraform, docker, ML pipelines all execute inside AWS.

---

## Why this shape

| Concern | Solution |
|---|---|
| No git remote yet | Source = S3 zip → CodeBuild reads it directly |
| Don't burn laptop battery / need admin to install terraform | CodeBuild container has terraform installed at runtime |
| Cost visibility | One CodeBuild project → one CloudWatch log stream per run |
| Reproducibility | Same buildspec.yml runs identically on every trigger |
| State safety | Remote state in S3 + DynamoDB lock (never on laptop) |
| Cross-account portability | Swap `AWS_ACCOUNT_ID` var; nothing else changes |

---

## Architecture Diagram

```
                         ┌──────────────────────────────────────┐
                         │           LAPTOP (thin)              │
                         │  - edit .tf / buildspec.yml          │
                         │  - zip repo                          │
                         │  - aws s3 cp source.zip …            │
                         │  - aws codebuild start-build         │
                         └──────────────┬───────────────────────┘
                                        │  (upload + trigger)
                                        ▼
       ═════════════════════════════════════════════════════════════════
       ║                          AWS ACCOUNT                          ║
       ║                                                               ║
       ║   ┌──────────────────────┐        ┌────────────────────────┐  ║
       ║   │  S3: source bucket   │◄───────│  IAM: CodeBuild role   │  ║
       ║   │  source.zip          │        │  (AdministratorAccess) │  ║
       ║   └──────────┬───────────┘        └────────────────────────┘  ║
       ║              │                                                ║
       ║              ▼                                                ║
       ║   ┌────────────────────────────────────────────────────┐      ║
       ║   │  CodeBuild project: monitoring-mlops-tf            │      ║
       ║   │  ─────────────────────────────────────────────     │      ║
       ║   │  1. install terraform 1.7.5                        │      ║
       ║   │  2. rename "infra "  →  tfroot                     │      ║
       ║   │  3. terraform init  (S3 backend + DDB lock)        │      ║
       ║   │  4. workspace select/new dev                       │      ║
       ║   │  5. STAGE-1  apply -target=vpc,datalake,eks        │      ║
       ║   │  6. STAGE-2  apply (full graph)                    │      ║
       ║   │  Logs → CloudWatch: /aws/codebuild/monitoring-…    │      ║
       ║   └───────────────┬────────────────────────────────────┘      ║
       ║                   │                                           ║
       ║   ┌───────────────┴─────────────────┐                         ║
       ║   ▼                                 ▼                         ║
       ║ ┌──────────────────────┐   ┌──────────────────────────┐       ║
       ║ │ S3 tfstate bucket    │   │ DynamoDB lock table      │       ║
       ║ │ mlops-learning-tfs…  │   │ mlops-learning-tfstate…  │       ║
       ║ │ versioned + SSE      │   │ (LockID hash key)        │       ║
       ║ └──────────────────────┘   └──────────────────────────┘       ║
       ║                                                               ║
       ║  ══════════ resources terraform provisions ══════════         ║
       ║                                                               ║
       ║  L1 network   VPC · subnets · NAT · IGW                       ║
       ║  L2 ingest    Kinesis Firehose · MSK Kafka                    ║
       ║  L3 lake      S3 raw partitioned · Glue                       ║
       ║  L4 features  SageMaker Processing jobs                       ║
       ║  L5 detect    OpenSearch · SageMaker · Lambda streaming       ║
       ║  L6 deploy    EKS · ALB · WAF · Cognito · CodePipeline        ║
       ║  L7 monitor   AMP · AMG · CloudWatch · GuardDuty · SecHub     ║
       ║                                                               ║
       ═════════════════════════════════════════════════════════════════
```

---

## Sequence — one deploy end-to-end

```
[dev]           [S3 src]      [CodeBuild]     [S3 state]     [AWS APIs]
  │                │                │              │              │
  │─zip + cp──────►│                │              │              │
  │─start-build ──────────────────► │              │              │
  │                │                │              │              │
  │                │◄──download─────│              │              │
  │                │                │─init ───────►│              │
  │                │                │◄─backend OK──│              │
  │                │                │─plan (stage1)───────────────►
  │                │                │◄──plan output───────────────│
  │                │                │─apply stage1 ───────────────►
  │                │                │  (creates VPC, S3 lake, EKS)│
  │                │                │◄──resources created────────│
  │                │                │─plan (full) ────────────────►
  │                │                │─apply (full) ───────────────►
  │                │                │  (MSK, OpenSearch, SM, …)   │
  │                │                │◄──stack up────────────────  │
  │◄─build SUCCESS ────────────────│              │              │
```

---

## Files that drive the workflow

| File | Role |
|---|---|
| `buildspec.yml` | CodeBuild runbook. install → init → workspace → staged apply |
| `infra /backend.tf` | S3 backend + DynamoDB lock config |
| `infra /main.tf` | Root module wiring — vpc, datalake, eks, msk, opensearch, sagemaker, monitoring, etc. |
| `infra /variables.tf` | Env knobs (region, EKS version, instance sizes) |
| `.github/workflows/terraform-apply.yml` | Alternate path — GitHub Actions + OIDC (unused today, no git remote) |
| `scripts/bootstrap_state.sh` | ONE-TIME: creates tfstate bucket + DDB lock (already done) |
| `scripts/teardown.sh` | Reverse order teardown |

---

## Two-stage apply — why it exists

Some modules use `count = something-only-known-after-apply`:

```hcl
# infra/modules/amp/main.tf
count = var.eks_oidc_provider_arn != "" && length(...) > 0 ? 1 : 0
```

`eks_oidc_provider_arn` is an **output** of the eks module. Terraform can't
evaluate `count` at plan time before the eks module has been applied at
least once. Result: `Error: Invalid count argument`.

**Fix**: `-target` the dependency roots first (vpc, datalake, eks) so their
outputs become known state; then a full unbounded apply plans cleanly against
that state.

```
STAGE-1  terraform apply -target=module.vpc -target=module.datalake -target=module.eks
STAGE-2  terraform apply
```

After the first successful stack, subsequent applies skip stage-1 (state
already has the outputs). Kept in buildspec because idempotent.

---

## What this deploy actually creates (dev workspace)

| Layer | Resources | Cost/day dev (approx) |
|---|---|---|
| Network | VPC, 3 public + 3 private subnets, NAT GW | $1.00 (NAT) |
| EKS | Control plane + 2 × m5.large nodes | $8-10 |
| MSK | 3 × kafka.t3.small brokers | $6-8 |
| OpenSearch | 1 × t3.small.search + 10 GB EBS | $2-3 |
| SageMaker | 4 endpoints on ml.t2.medium | $6-8 |
| RDS | db.t3.micro | $0.50 |
| Firehose / Kinesis | pay-per-request | $0-2 |
| ALB + WAF | $0.60 + rules | $1-2 |
| CloudTrail + GuardDuty + SecHub + AMP + AMG | data volume driven | $2-5 |
| Data-lake S3 + tfstate + source S3 | storage only | $0.10 |
| **Total idle** | | **~$30-45/day** |

Attack traffic + retraining on top of that.

---

## How to use — cheat sheet

### First-time bootstrap (already done)
```bash
aws s3api create-bucket --bucket mlops-learning-tfstate --region <AWS_REGION> …
aws dynamodb create-table --table-name mlops-learning-tfstate-lock …
aws iam create-role --role-name monitoring-mlops-codebuild-tf …
aws codebuild create-project --cli-input-json …
```

### Every subsequent change
```bash
# 1. edit .tf / .yml on laptop
# 2. package + push
zip -qr /tmp/src.zip . -x '.venv/*' '**/.terraform/*'
aws s3 cp /tmp/src.zip s3://monitoring-mlops-cb-source-<ACCOUNT_ID>/source.zip

# 3. trigger apply in AWS
aws codebuild start-build \
  --project-name monitoring-mlops-tf \
  --region <AWS_REGION> \
  --environment-variables-override name=TF_ACTION,value=apply,type=PLAINTEXT

# 4. watch
aws codebuild batch-get-builds --ids <build-id> --query 'builds[0].currentPhase'

# 5. logs
aws logs tail /aws/codebuild/monitoring-mlops-tf --follow
```

### Plan only (safe, no changes)
```bash
aws codebuild start-build --project-name monitoring-mlops-tf --region <AWS_REGION> \
  --environment-variables-override name=TF_ACTION,value=plan,type=PLAINTEXT
```

### Teardown
```bash
aws codebuild start-build --project-name monitoring-mlops-tf --region <AWS_REGION> \
  --environment-variables-override name=TF_ACTION,value=destroy,type=PLAINTEXT
# Follow order in scripts/teardown.sh: SM endpoints → EKS scale-0 → MSK → OS → firehose → destroy
```

---

## Why this is useful

- **Zero laptop dependency for the heavy lift.** Terraform + docker + kubectl live in the CodeBuild container. Laptop only needs `aws` + `zip`.
- **Reproducible.** Every trigger runs the same buildspec. No "works on my machine" drift.
- **Auditable.** Every action lands in CloudWatch Logs and in the CodeBuild build history. Log retention = 90 d default, can extend.
- **Team-friendly.** Anyone with `codebuild:StartBuild` can trigger an apply. Nobody needs terraform installed. No shared laptop state.
- **Cheaper CI.** No GitHub Actions minutes; CodeBuild's small tier is a few cents per build.
- **Portable.** Swap the account id + a few names, redeploy in another AWS account.
- **Failure isolation.** A bad plan aborts before touching resources. State stays consistent thanks to DDB lock.
- **Two-stage apply** documented above resolves count-of-unknown errors without hacky `depends_on` gymnastics.

---

## Failure modes seen so far

| Symptom | Root cause | Fix |
|---|---|---|
| `cd: infra: No such file or directory` | dir has trailing space (`infra `) | detect + rename to `tfroot` in install phase |
| `Invalid count argument` on amp/guardduty | `count` uses eks module output | staged apply — see above |
| `unsupported Kubernetes version 1.28` | 1.28 is EOL | bumped default to 1.30 in `variables.tf` |
| cwd lost between phases | CodeBuild resets shell each phase | consolidate all steps into one BUILD phase |

---

## Application screenshots

Real screenshots go in `docs/img/` after the deploy finishes and the ALB DNS
resolves. Until then, the mockups below describe what each surface should
look like. Replace with `![…](img/…png)` once captured.

### AIOps Dashboard (Grafana / OpenSearch Dashboards)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  AIOps · Anomaly Overview                                    ⏱ last 1h  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌── ANOMALY SCORE (all detectors) ────────────────────────────────┐    │
│   │  6 ┤                                          ▄                 │    │
│   │  4 ┤             ▄▄            ▄▄▄▄▄        ▄██                 │    │
│   │  2 ┤    ▄▄     ▄██▄▄▄     ▄▄▄▄██████▄▄▄▄▄██████                 │    │
│   │  0 └──────────────────────────────────────────────────────────  │    │
│   │        13:00      13:15      13:30      13:45      14:00        │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│   ┌── OPEN ALERTS (23) ──┐  ┌── DETECTOR HEALTH ────────────────────┐    │
│   │ ▲ CRIT   3           │  │ rcf-metrics-dev            ● HEALTHY  │    │
│   │ ▲ HIGH   7           │  │ iforest-logs-dev           ● HEALTHY  │    │
│   │ ▲ MED   11           │  │ lstm-ae-traces-dev         ● HEALTHY  │    │
│   │ ○ LOW    2           │  │ log-embed-anomaly-dev      ● WARNING  │    │
│   └──────────────────────┘  │ streaming-lambda-zscore    ● HEALTHY  │    │
│                              └───────────────────────────────────────┘    │
│                                                                          │
│   ┌── TOP SOURCES BY ANOMALY RATE ────────────────────────────────┐     │
│   │ nginx      ████████████████████████████████████████ 42.1%      │     │
│   │ waf        █████████████████████████ 24.6%                     │     │
│   │ alb        ███████████████ 15.3%                               │     │
│   │ app        ███████████ 10.9%                                   │     │
│   │ eks-audit  █████ 4.2%                                          │     │
│   │ others     ▂ 2.9%                                              │     │
│   └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│   ┌── LATEST ALERTS ──────────────────────────────────────────────┐     │
│   │ 14:02  CRIT   nginx   src_ip=10.0.44.1 · 4xx spike ×22         │     │
│   │ 13:58  HIGH   waf     BLOCK rate ↑ 6× baseline                 │     │
│   │ 13:47  HIGH   alb     latency p99 = 1.4s (baseline 180ms)      │     │
│   │ 13:32  MED    app     error_rate_5m = 7.1% (>5% threshold)     │     │
│   └────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────┘
```

Real image slot:
```
![AIOps dashboard](img/aiops-dashboard.png)
```

### Scoring API (`/score` request/response)

```
┌ POST https://<alb-dns>/api/v1/score ─────────────────────────────────────┐
│                                                                          │
│ Headers                                                                  │
│   Authorization: Bearer eyJraWQiOiJ…  (Cognito JWT)                     │
│   Content-Type:  application/json                                        │
│                                                                          │
│ Request body                                                             │
│ {                                                                        │
│   "ts": "2026-07-06T18:32:11Z",                                          │
│   "source": "nginx",                                                     │
│   "host": "ip-10-0-1-42",                                                │
│   "status": 401,                                                         │
│   "latency_ms": 89,                                                      │
│   "src_ip": "hmac_a1b2c3…",                                              │
│   "path": "/api/v1/login",                                               │
│   "message": "auth failed for user=admin"                                │
│ }                                                                        │
│                                                                          │
│ 200 OK                                                                   │
│ {                                                                        │
│   "score": 4.72,                                                         │
│   "is_anomaly": true,                                                    │
│   "detector": "iforest-logs-dev",                                        │
│   "explanation": {                                                       │
│     "top_features": [                                                    │
│       { "name": "auth_failure_rate_5m", "obs": 0.61, "baseline": 0.03 },│
│       { "name": "distinct_ips_5m",       "obs": 218,  "baseline": 12   },│
│       { "name": "4xx_rate_5m",           "obs": 0.42, "baseline": 0.05 }│
│     ],                                                                   │
│     "similar_past_alerts": ["a-2026-06-30-441", "a-2026-06-24-118"]      │
│   }                                                                      │
│ }                                                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

Real image slot:
```
![Scoring API /score](img/scoring-api-score.png)
![Scoring API /alerts](img/scoring-api-alerts.png)
```

### Capture commands (run after deploy)

```bash
# Get ALB DNS
ALB=$(aws elbv2 describe-load-balancers --region <AWS_REGION> \
  --query "LoadBalancers[?contains(LoadBalancerName,'aiops')].DNSName" -o text)

# API screenshot via Chrome headless
chrome --headless --screenshot=docs/img/scoring-api-score.png \
       --window-size=1400,900 "https://$ALB/docs"

# Grafana dashboard PNG export
curl -H "Authorization: Bearer $GRAFANA_TOKEN" \
     "https://$AMG_URL/render/d/aiops-overview?panelId=1&width=1400&height=800" \
     -o docs/img/aiops-dashboard.png
```

---

## Handy pointers

- CodeBuild console: `https://<region>.console.aws.amazon.com/codesuite/codebuild/projects/monitoring-mlops-tf`
- Log group: `/aws/codebuild/monitoring-mlops-tf`
- State bucket: `s3://mlops-learning-tfstate/monitoring-mlops/dev/terraform.tfstate`
- Lock table: `mlops-learning-tfstate-lock`
- Source zip: `s3://monitoring-mlops-cb-source-<ACCOUNT_ID>/source.zip`
- IAM role: `arn:aws:iam::<ACCOUNT_ID>:role/monitoring-mlops-codebuild-tf`

# AIOps + MLOps + Security Analytics Platform

End-to-end reference for the repo. Read before touching code or running commands.

---

## Project Overview

This is an end-to-end **AIOps / MLOps / Security Analytics platform on AWS** that
ingests logs, metrics, and traces from across the stack and runs **anomaly /
threat detection** on them — both with statistical streaming detectors (cold-start,
work from minute one) and trained ML detectors (work after a learning window).

It is a sibling project to `../mlops/` (student personalization platform). The
infrastructure shape is similar by design — VPC, EKS, SageMaker, observability,
CI/CD — but the **data, models, and APIs are different**.

**Goal**: Build, deploy, and validate a system that delivers:
- Real-time alerts on anomalous behaviour across ingested signals
- A tiered detection stack: AWS-managed (GuardDuty/Security Hub) + statistical
  streaming + ML batch + ML streaming inference
- Continuous retraining as the threat landscape and traffic baseline drift

**Owner**: <owner>
**Cloud**: AWS (ap-south-1 Mumbai, primary)
**ML Orchestration**: Amazon SageMaker
**Streaming**: Kinesis Firehose + MSK (Kafka)
**Search/AD**: Amazon OpenSearch (with Anomaly Detection plugin)
**Metrics**: Amazon Managed Prometheus (AMP) + Managed Grafana (AMG)
**IaC**: Terraform
**Container Runtime**: Amazon EKS (Kubernetes)

---

## Detection latency reality check

**This platform does not detect anomalies on day one of deployment.** Any
unsupervised detector (Random Cut Forest, Isolation Forest, autoencoder)
needs a baseline of "normal" before it can call something abnormal. This
is intrinsic to anomaly detection and cannot be removed.

The platform is therefore tiered:

| Tier | Latency | What it does | Cold-start |
|---|---|---|---|
| **AWS-managed**       | seconds       | GuardDuty (VPC/CT/DNS), Security Hub findings, Detective | works immediately |
| **Streaming statistical** (Lambda) | seconds | z-score, EWMA, rate-of-change, threshold rules | works after ~30 min of data |
| **OpenSearch AD plugin** | minutes    | RCF on indexed metrics/logs | works after detector init (≥ 32 intervals) |
| **SageMaker batch + endpoint** | hours train, ms inference | RCF, Isolation Forest, LSTM-AE, Log-BERT | needs ≥ 1–7 days of representative data |

**Real-time prediction is a property of the *inference* path, not training.**
Models train in batch, deploy to a SageMaker endpoint, and that endpoint
serves real-time predictions (~50–200 ms p99). The drift-retrain loop keeps
the model fresh.

---

## Repository Structure

```
monitoring-mlops/
├── README.md
├── infra /                        ← All AWS infrastructure
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── backend.tf
│   └── modules/
│       ├── datalake/              ← S3 (raw partitioned per-source), Glue
│       ├── firehose/              ← Kinesis Firehose: CloudFront/ALB/WAF/App/EKS → S3
│       ├── msk/                   ← Managed Kafka for high-throughput app/nginx logs
│       ├── opensearch/            ← OpenSearch domain + AD detectors
│       ├── sagemaker/              ← Feature Store, Endpoints, Model Registry
│       ├── eks/                   ← EKS + IRSA (Fluent Bit, ADOT, scoring API)
│       ├── database/              ← RDS for analyst metadata (acks, labels)
│       ├── cognito/               ← Analyst / responder / admin auth
│       ├── alb/ + waf/            ← Public ingress for the Scoring API
│       ├── monitoring/            ← CloudWatch alarms, dashboards, retrain Lambda
│       ├── cloudtrail/            ← Account audit
│       ├── billing/               ← Cost guardrails
│       ├── guardduty/             ← Threat intel
│       ├── securityhub/           ← Findings aggregation
│       ├── amp/                   ← Managed Prometheus
│       ├── amg/                   ← Managed Grafana
│       └── cicd/                  ← CodePipeline (model promotion)
├── ml/
│   ├── parsers/                   ← Per-source log parsers → common schema
│   ├── feature_engineering/       ← Sliding-window security features
│   ├── pipelines/                 ← SageMaker Pipelines (4 detectors)
│   │   ├── rcf_metrics/           ← Random Cut Forest on metrics
│   │   ├── iforest_logs/          ← Isolation Forest on tabular log features
│   │   ├── lstm_autoencoder_traces/ ← Sequence-level on OTEL spans
│   │   └── log_embedding_anomaly/ ← LogBERT-lite on raw log lines
│   ├── streaming/                 ← Lambda statistical detectors (cold-start)
│   ├── monitoring/                ← Drift detection on detector inputs
│   └── inference/                 ← Local model loaders
├── api/
│   └── scoring/                   ← FastAPI: /score, /alerts, /explain, /feedback
├── helm/
│   ├── charts/
│   │   ├── anomaly-scoring-api/   ← The API on EKS
│   │   ├── fluent-bit/            ← DaemonSet shipping container logs
│   │   └── adot-collector/        ← OTEL traces + Prom-remote-write
│   └── cluster-addons/
├── scripts/
│   ├── seed_logs.py               ← Generate synthetic logs across all 14 sources
│   ├── inject_attack.py           ← Simulated attacks (DDoS / brute force / slow loris)
│   ├── teardown.sh
│   └── smoke_test.sh
├── tests/
│   ├── unit/                      ← Parsers, features, detectors
│   ├── integration/               ← API end-to-end
│   └── load/                      ← Locust against scoring API
├── argocd/
└── docs/
    ├── architecture.md
    ├── slo-definitions.md
    ├── PRODUCTION-CHECKLIST.md
    └── runbooks/
```

---

## Layer Architecture

```
L1  Data Sources       CloudFront · ALB · WAF · App · EKS · NGINX · Kafka ·
                       MySQL · Mongo · Redis · node/container/Prom · OTEL traces
L2  Ingestion          Kinesis Firehose · MSK (Kafka) · Fluent Bit · ADOT collector
L3  Lake / Index       S3 (raw partitioned per-source) · Glue · OpenSearch indices
L4  Feature Engineering SageMaker Processing → security_features (sliding windows)
L5  Detection (tier'd) AWS-managed (GuardDuty/SecHub) + streaming-statistical
                       (Lambda) + OpenSearch AD + SageMaker ML detectors
L6  Registry + Deploy  Model Registry · CodePipeline · SageMaker Endpoints · EKS
L7  Monitoring         Drift on detector inputs · CloudWatch · EventBridge → retrain

APP Anomaly Scoring API   FastAPI on EKS · /score · /alerts · /explain
APP AIOps Dashboard        Grafana (AMG) + OpenSearch Dashboards
```

---

## Data Sources & Ingestion Path

| Source | Format | Path |
|---|---|---|
| CloudFront | W3C extended | CF logging → S3 → Firehose transform → S3 raw Parquet |
| ALB        | CLF-ish      | ALB access log → S3 → Firehose transform → S3 raw Parquet |
| WAF        | JSON         | WAF logging → Firehose → S3 raw |
| Application logs | JSON / structured | Fluent Bit DaemonSet → MSK → Glue ETL → S3 |
| EKS audit / control plane | JSON | CloudWatch Logs subscription → Firehose → S3 |
| NGINX     | combined log | Fluent Bit (`tail` on `/var/log/nginx/*.log`) → MSK → S3 |
| Kafka (broker) | JMX / log4j | Kafka Connect → MSK → S3 |
| MySQL     | slow-query / general | RDS log export → Firehose → S3 |
| MongoDB   | log lines    | Fluent Bit (sidecar / agent) → MSK → S3 |
| Redis     | log lines    | Fluent Bit sidecar → MSK → S3 |
| Node metrics | Prometheus | node_exporter → ADOT → AMP (remote write) |
| Container metrics | Prometheus | cAdvisor / kubelet → ADOT → AMP |
| Prometheus app metrics | Prometheus | scraped by ADOT → AMP |
| OpenTelemetry traces | OTLP | App SDK → ADOT → AWS X-Ray + S3 archive |

**Common schema** (`ml/parsers/__init__.py::CommonEvent`):

```python
{
    "ts":         iso8601,         # event time
    "ingest_ts":  iso8601,         # when we received it
    "source":     "cloudfront" | "alb" | "waf" | "app" | "eks" | "nginx" | ...,
    "host":       str,             # node, pod, edge location
    "severity":   "DEBUG" | "INFO" | "WARN" | "ERROR" | "CRITICAL" | None,
    "status":     int | None,
    "latency_ms": float | None,
    "bytes":      int | None,
    "src_ip":     str | None,
    "user":       str | None,
    "path":       str | None,
    "user_agent": str | None,
    "message":    str,
    "attrs":      dict,
}
```

---

## Anomaly Detector Specifications

### Detector 1 — RCF Metrics

| Attribute | Value |
|-----------|-------|
| Type | Unsupervised — streaming-friendly |
| Algorithm | SageMaker Random Cut Forest |
| Input | per-(source, host, metric) sliding-window vector — `request_rate_5m`, `error_rate_5m`, `p99_latency_5m`, `cpu_util_5m`, `mem_util_5m` |
| Output | `anomaly_score` (float ≥ 0; > 3.0 = strong anomaly) |
| Training instance | ml.m5.xlarge (Spot) |
| Inference instance | ml.t2.medium |
| Evaluation gate | F1 ≥ 0.70 on injected-attack labelled set |
| Retrain cadence | Daily |

### Detector 2 — Isolation Forest on Logs

| Attribute | Value |
|-----------|-------|
| Type | Unsupervised tabular |
| Algorithm | sklearn IsolationForest |
| Input | per-window tabular: `4xx_rate`, `5xx_rate`, `distinct_ips`, `distinct_paths`, `auth_failure_rate`, `bytes_p99`, `entropy_path` |
| Output | `anomaly_score` (negative = anomalous), `is_anomaly` (-1/1) |
| Evaluation gate | Precision @ top-1% ≥ 0.80 |
| Retrain cadence | Daily |

### Detector 3 — LSTM Autoencoder on Traces

| Attribute | Value |
|-----------|-------|
| Type | Sequence reconstruction |
| Algorithm | LSTM AE (PyTorch) |
| Input | OTEL span sequences per trace: (service_id, op_id, duration_ms, status_code) |
| Output | `recon_error` (mean-squared reconstruction error); threshold = 95th percentile of training set |
| Training instance | ml.g4dn.xlarge (GPU, Spot) |
| Inference instance | ml.c5.large |
| Evaluation gate | AUC > 0.80 on held-out anomaly set |
| Retrain cadence | Weekly |

### Detector 4 — Log Embedding Anomaly (LogBERT-lite)

| Attribute | Value |
|-----------|-------|
| Type | Unsupervised NLP |
| Algorithm | DistilBERT-mini or TF-IDF + IsolationForest fallback |
| Input | Raw log line + structured fields |
| Output | `anomaly_score` |
| Training instance | ml.m5.2xlarge (or ml.g4dn.xlarge for transformer) |
| Inference instance | ml.c5.xlarge |
| Evaluation gate | Precision @ top-1% ≥ 0.75 |
| Retrain cadence | Weekly |

### Streaming Statistical Detectors (Cold-Start)

Lambda triggered by Kinesis / Firehose. Fires from minute one (no training).
Rules:

```
z-score(metric, window=5m, threshold=4.0)
EWMA(metric, alpha=0.3, deviation=3σ)
rate-of-change(metric, threshold_pct=200%)
threshold-static (e.g. error_rate_5m > 5%)
distinct-counter (e.g. distinct_src_ips > 10000 in 1m → potential DDoS)
```

These detectors emit anomalies to the same SNS topic + S3 path as the ML
detectors so the API treats them uniformly.

---

## API Specifications

### Anomaly Scoring API

```
Base: https://aiops.mlops-learning.internal/api/v1
Auth: AWS Cognito JWT (groups: analyst | responder | admin)

POST /score
  Body: a CommonEvent
  Returns: { score: float, is_anomaly: bool, detector: str, explanation: dict }
  SLO: p99 < 250 ms

GET /alerts?since=...&source=...&severity=...
  Returns the active and recent anomalies (paginated).

GET /alerts/{id}/explain
  Returns top contributing features, baseline vs observed values, similar past
  alerts, and the detector that fired.

POST /feedback
  Body: { alert_id, label: "true_positive" | "false_positive" | "ignored" }

GET /sources
  Per-source health: ingest rate, last-seen timestamp.

GET /health
GET /metrics            (Prometheus)
```

---

## SLOs

See `docs/slo-definitions.md`. Headline numbers:

- **Mean Time to Detect (MTTD)**: streaming statistical < 90 s; ML detector < 5 min after training cycle
- **Alert latency (p99)**: < 250 ms (API)
- **False-positive rate** (after first month of feedback): < 5%
- **Ingest backlog**: Firehose / MSK consumer lag < 5 min p99
- **Detector availability**: ≥ 99.5% (mirrors API)

---

## Critical Rules

1. **No PII in security signals**. Hash usernames, IPs (HMAC) before they leave the parser. Raw IPs allowed only in WAF/CloudFront where they're already the data being analysed.
2. **Cost-aware**: ml.t2.medium endpoints in dev. No GPU above ml.g4dn.xlarge. Spot for all training.
3. **Teardown order is sacred**: SageMaker endpoints → EKS scale-to-0 → MSK delete → OpenSearch delete → Firehose → terraform destroy.
4. **All Terraform resources tagged** with `Project=monitoring-mlops`.
5. **Drift on detector inputs, not predictions**.
6. **Detector naming convention**: `{detector}-{environment}-pipeline`.
7. **Endpoint naming**: `{detector}-{environment}`.

---

## Sensitive Areas

1. `infra /modules/sagemaker/` — endpoint pool change can drop detection coverage.
2. `ml/feature_engineering/security_features.py` — feature change invalidates baselines; you must retrain ALL detectors.
3. `ml/streaming/rules.yaml` — false positives here drown the on-call; tune slowly.
4. `infra /modules/opensearch/` — schema is hard to evolve once indices exist; use index aliases + reindex.
5. `infra /modules/guardduty/` — disabling = blind to AWS-side threats. Don't.

# Signal flow — demo-app to monitoring-mlops

This is the end-to-end picture of how each of the 14 ingestion paths wires up
when the demo-app is deployed alongside the AIOps platform.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  demo-app (this directory)                                                   │
│                                                                              │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐                               │
│   │ web      │   │ api      │   │ worker   │                               │
│   │ (NGINX)  │   │ (FastAPI)│   │ (Python) │                               │
│   └────┬─────┘   └────┬─────┘   └────┬─────┘                               │
│        │              │              │                                      │
│        │              ▼              ▼                                      │
│        │         ┌─────────┐    ┌─────────┐                                │
│        │         │ MySQL   │    │ Redis   │                                │
│        │         │ (RDS)   │    │ (Cache) │                                │
│        │         └────┬────┘    └─────────┘                                │
│        │              │                                                     │
│        │              ▼                                                     │
│        │         /aws/rds/.../slowquery (CloudWatch Logs)                  │
│        │              │                                                     │
└────────┼──────────────┼─────────────────────────────────────────────────────┘
         │              │
         │              │  CloudWatch subscription filter (defined here)
         │              ▼
         │         monitoring-mlops Firehose: app stream
         │              │
         │              ▼
         │         s3://monitoring-mlops-{env}-raw/raw/source=app/year=…/
         │
         │ stdout/stderr → container log → Fluent Bit DaemonSet
         │
         ▼ (per-line)
   Fluent Bit (in cluster-addons helmfile)
         │
         ├──► MSK topic logs.app                       → S3 raw (via Kafka Connect / consumer)
         ├──► MSK topic logs.nginx                      → S3 raw
         └──► OpenSearch index logs-{source}-yyyy-mm-dd

   ADOT collector (in cluster-addons helmfile)
         │  via OTLP from api/worker
         │  via prometheus.io scrape annotations
         │
         ├──► AMP (Prometheus remote-write)
         └──► AWS X-Ray (traces)

   ALB (created by web Ingress)
         │  access logs → S3 (configure on the ALB after Ingress is created)
         │
         ▼
   monitoring-mlops Firehose: alb stream
         │
         ▼
   s3://monitoring-mlops-{env}-raw/raw/source=alb/...

   CloudFront (configured outside this repo)
         │  origin = ALB DNS
         │  logs   → S3 → Lambda → Firehose: cloudfront stream
         │
         ▼
   s3://monitoring-mlops-{env}-raw/raw/source=cloudfront/...

   WAFv2 (associated with ALB by Ingress annotation)
         │  logs → Firehose: waf stream
         │
         ▼
   s3://monitoring-mlops-{env}-raw/raw/source=waf/...
```

## Per-source mapping

| Source | Producer in demo | Path to platform |
|---|---|---|
| **app**           | api / worker container stdout (JSON) | Fluent Bit → MSK `logs.app` → S3 raw |
| **nginx**         | web container access log              | Fluent Bit → MSK `logs.nginx` → S3 raw |
| **mysql**         | RDS slow-query log                    | CloudWatch → Firehose mysql → S3 raw  |
| **alb**           | ALB access logs                       | ALB → S3 → Firehose alb → S3 raw      |
| **cloudfront**    | CloudFront standard logs              | CF → S3 → Firehose cloudfront → S3 raw |
| **waf**           | WAF v2 logs                           | WAF → Firehose waf → S3 raw           |
| **eks**           | K8s audit log                         | CW → Firehose eks → S3 raw            |
| **prometheus**    | api `/metrics`                        | ADOT → AMP                             |
| **node-metrics**  | node_exporter (cluster-addons)        | ADOT → AMP                             |
| **container-metrics** | cAdvisor / kubelet                | ADOT → AMP                             |
| **otel-traces**   | api OTEL SDK                          | ADOT → X-Ray + S3 archive             |
| **kafka**         | MSK broker logs (already wired in platform) | direct to S3 via MSK→Firehose pipeline |
| **mongodb**       | (not in demo — pattern same as mysql) | (not exercised)                        |
| **redis**         | (not exercised — ElastiCache logs are scraped via CW Logs subscription, not in this demo) | (not exercised) |

## What's NOT in this demo

- MongoDB and Redis logs aren't exercised. Both follow the same
  CloudWatch-Logs-subscription-to-Firehose pattern as MySQL slow-query;
  add a similar `aws_cloudwatch_log_subscription_filter` for them when you
  introduce those data tiers.
- Kafka broker logs are already wired in the AIOps platform (`infra /modules/msk`
  has `open_monitoring.prometheus.jmx_exporter.enabled_in_broker = true` and
  `logging_info.broker_logs.cloudwatch_logs.enabled = true`). You don't need
  to add anything in the demo.

## How to verify each path

After 10 minutes of traffic from `traffic-gen/`:

```bash
# 1. ALB access logs
aws s3 ls s3://monitoring-mlops-dev-raw/raw/source=alb/ --recursive | tail

# 2. App logs via MSK (look in OpenSearch since the MSK→S3 sink is async)
curl -k "https://${OPENSEARCH_ENDPOINT}/logs-app-*/_search?size=5&pretty" \
  -H "Authorization: Basic $(echo -n aiops_admin:$OS_PASSWORD | base64)"

# 3. NGINX access logs
curl -k "https://${OPENSEARCH_ENDPOINT}/logs-nginx-*/_search?size=5&pretty" ...

# 4. MySQL slow-query
aws s3 ls s3://monitoring-mlops-dev-raw/raw/source=mysql/ --recursive | tail

# 5. Prometheus metrics in AMP
aws amp query-metrics --workspace-id $AMP_ID \
  --query "demo_api_requests_total"

# 6. OTEL traces in X-Ray
aws xray get-trace-summaries --start-time $(date -d '5 min ago' +%s) \
  --end-time $(date +%s) --filter-expression 'service("demo-api")'

# 7. Anomalies arriving in the scoring API
curl -s "$SCORING_API/alerts?limit=20" | jq '.[] | {detector, source, score, ts_seen}'
```

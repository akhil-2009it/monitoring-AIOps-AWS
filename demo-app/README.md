# demo-app/ — A small e-commerce stack that emits everything `monitoring-mlops` ingests

This is the **producer side** for the AIOps platform. It exists so you can
run an end-to-end demo without pointing the platform at a real production
system.

It is a deliberately small stack:

```
Internet ──► CloudFront ──► ALB (WAFv2) ──► EKS
                                              ├── web         (NGINX)
                                              ├── api         (FastAPI)
                                              └── worker      (background jobs)
                                                  │
                                                  ├──► RDS MySQL  (slow-query log enabled)
                                                  └──► (future)   Redis / Mongo

Logs/metrics/traces flow:
  CloudFront → S3 logging                         → Firehose ─► S3 raw
  ALB        → S3 access logs                     → Firehose ─► S3 raw
  WAF        → Firehose direct                    → S3 raw
  EKS audit  → CW Logs → subscription             → Firehose ─► S3 raw
  RDS slow   → CW Logs → subscription             → Firehose ─► S3 raw
  App stdout → Fluent Bit DaemonSet               → MSK     ─► S3 processed
  NGINX log  → Fluent Bit (tail)                  → MSK     ─► S3 processed
  Metrics    → Prometheus (in-cluster) → ADOT     → AMP
  Traces     → OTLP via ADOT collector            → X-Ray + S3 archive
  Node/cont  → cAdvisor + node_exporter → ADOT    → AMP
```

That covers all 14 sources documented in `../CLAUDE.md`.

## What's in this directory

```
demo-app/
├── README.md                ← this file
├── api/                     ← Python FastAPI service (the backend API)
│   ├── app/main.py
│   ├── app/...
│   ├── Dockerfile
│   └── requirements.txt
├── worker/                  ← Python background worker (job processor)
│   ├── app/worker.py
│   ├── Dockerfile
│   └── requirements.txt
├── web/                     ← NGINX-served static site (the frontend)
│   ├── site/index.html
│   └── nginx.conf
├── traffic-gen/             ← Locust-based traffic generator
│   ├── locustfile.py
│   └── README.md
├── infra/                   ← Terraform for CloudFront/ALB/WAF/RDS/CW
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── helm/                    ← Helm charts for the 3 services
│   ├── api/
│   ├── worker/
│   └── web/
└── docs/                    ← Demo-specific runbooks
    └── walkthrough.md
```

## Why each service exists

| Service | Drives | What anomalies it can simulate |
|---|---|---|
| `web` (NGINX) | CloudFront, ALB access logs, NGINX combined log, WAF | DDoS, scanner, slow-loris |
| `api` (FastAPI) | App JSON logs, OTEL traces, Prom metrics, MySQL slow-query | High latency, error storms, memory leaks (simulated), brute-force on /login |
| `worker` (Python) | App JSON logs, OTEL traces, Prom metrics | Queue depth anomalies, processing-time outliers |

## Deploying

This deploys *on top of* a running `monitoring-mlops` environment (the
AIOps platform must already be applied). The demo app expects:

- An EKS cluster (`monitoring-mlops-{env}`)
- The Firehose streams from `infra /modules/firehose`
- The MSK cluster from `infra /modules/msk`
- The OpenSearch domain from `infra /modules/opensearch`
- Fluent Bit + ADOT collector deployed (cluster-addons helmfile)

```bash
cd demo-app/infra
terraform init -backend-config="key=monitoring-mlops/demo-app/${ENV}/terraform.tfstate"
terraform workspace select dev
terraform apply

# After terraform completes, deploy services
cd ../helm
for svc in api worker web; do
  helm upgrade --install demo-$svc ./$svc \
    --namespace demo --create-namespace \
    --set image.tag=$(git rev-parse --short HEAD) \
    -f ./$svc/values.yaml
done

# Drive traffic
cd ../traffic-gen
HOST=$(terraform -chdir=../infra output -raw cloudfront_url) \
  locust -f locustfile.py --headless --users 50 --spawn-rate 5 --run-time 30m
```

## What you'll see

After ~10 minutes of traffic:

1. `s3://monitoring-mlops-{env}-raw/raw/source=alb/...parquet` filling up.
2. OpenSearch index `logs-app-*` getting documents.
3. AMG (Grafana) showing per-service Prometheus metrics.
4. The streaming detector (Lambda) firing on synthetic traffic spikes.
5. After ~7 days: ML detectors trained, scoring real events.

## Cost

This stack adds:
- ALB: ~$0.60/day base + LCU
- CloudFront: ~$0.085/GB + $0.0075/10k requests (low for demo)
- RDS db.t3.micro: ~$0.40/day
- 3 small EKS deployments: minimal incremental EKS cost (using existing nodes)
- WAFv2 ACL: ~$0.20/day base
- S3 + Firehose: per-GB

**Demo daily floor: ~$2–4/day on top of the AIOps platform.**

## Tearing down

```bash
helm -n demo uninstall demo-api demo-worker demo-web
cd demo-app/infra && terraform destroy
```

The AIOps platform stays intact.

# traffic-gen — Locust-based traffic generator

Two ways to run:

## Local (against a public-facing demo deployment)

```bash
pip install locust==2.30.0
HOST=$(kubectl -n demo get ingress demo-web -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Normal traffic
locust -f locustfile.py --headless \
  --host "https://$HOST" --users 50 --spawn-rate 5 --run-time 30m

# Attack — DDoS
DEMO_MODE=attack DEMO_ATTACK=ddos \
  locust -f locustfile.py --headless \
  --host "https://$HOST" --users 200 --spawn-rate 50 --run-time 5m

# Attack — brute-force
DEMO_MODE=attack DEMO_ATTACK=brute-force \
  locust -f locustfile.py --headless \
  --host "https://$HOST" --users 30 --spawn-rate 5 --run-time 10m
```

## In-cluster CronJob (continuous traffic)

```bash
kubectl apply -f k8s-cronjob.yaml
# CronJob `demo-traffic-normal` runs every 30 min keeping signal flowing.
# CronJob `demo-traffic-attack` is suspended by default.

# Trigger an attack run on demand:
kubectl -n demo patch cronjob demo-traffic-attack --patch '{"spec":{"suspend":false}}'
kubectl -n demo create job --from=cronjob/demo-traffic-attack attack-now
# After 5 min (the configured runtime), the Job finishes; suspend it again:
kubectl -n demo patch cronjob demo-traffic-attack --patch '{"spec":{"suspend":true}}'
```

## What you should see in the AIOps platform

After ~10 min of normal traffic:
- `demo-api` Prometheus metrics in AMP (`demo_api_requests_total`, `demo_api_request_latency_seconds`)
- App logs in OpenSearch index `logs-app-*`
- ALB access logs in `s3://monitoring-mlops-{env}-raw/raw/source=alb/`
- Streaming statistical detector firing on synthetic chaos (DEMO_ERROR_RATE injects 2% 500s)

After 5 min of attack traffic:
- Brute-force: streaming `auth_failure_rate` z-score alarm fires
- DDoS: WAF rate-limit rule blocks; `distinct_src_ips` counter alarm fires
- SQLi: WAF blocks the request; you see `BLOCK` in WAF findings

## Tuning the chaos knobs

The api Deployment's ConfigMap has three knobs that let you turn the
"realism" up or down:

```yaml
DEMO_ERROR_RATE:    "0.02"   # 2% of requests get a synthetic 500
DEMO_SLOW_RATE:     "0.05"   # 5% of requests get a slow path injected
DEMO_SLOW_LATENCY:  "1.5"    # the slow-path adds 1.5s
```

Bump these up if you want detectors to fire more obviously during demos:

```bash
kubectl -n demo set env deployment/demo-api \
  DEMO_ERROR_RATE=0.10 DEMO_SLOW_RATE=0.20
```

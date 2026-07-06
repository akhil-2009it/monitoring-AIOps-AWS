# Runbook — Demo-app end-to-end walkthrough

This is the "it actually works" demo. Deploy the AIOps platform + the demo
e-commerce app + traffic generator and watch alerts roll in.

**Prereqs**: `monitoring-mlops` is fully applied to a `dev` workspace, EKS
is running, Fluent Bit and ADOT collector are deployed via the cluster-addons
helmfile, and Cognito is configured.

## Step 1 — Build + push the demo images

```bash
cd monitoring-mlops/demo-app

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=ap-south-1
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $REGISTRY

for svc in api worker web; do
  docker build -t monitoring-mlops/demo-$svc:dev ./$svc
  docker tag  monitoring-mlops/demo-$svc:dev $REGISTRY/monitoring-mlops/demo-$svc:dev
  docker push $REGISTRY/monitoring-mlops/demo-$svc:dev
done

docker build -t monitoring-mlops/demo-traffic-gen:latest ./traffic-gen
docker tag    monitoring-mlops/demo-traffic-gen:latest $REGISTRY/monitoring-mlops/demo-traffic-gen:latest
docker push   $REGISTRY/monitoring-mlops/demo-traffic-gen:latest
```

(If the ECR repos don't exist yet, run `terraform apply` in step 2 first —
it creates them.)

## Step 2 — Apply the demo Terraform

```bash
cd monitoring-mlops/demo-app/infra
terraform init -backend-config="key=monitoring-mlops/demo-app/dev/terraform.tfstate"
terraform workspace select dev || terraform workspace new dev
terraform apply \
  -var="vpc_id=$(terraform -chdir=../../infra\  output -raw vpc_id)" \
  -var="private_subnet_ids=$(terraform -chdir=../../infra\  output -json private_subnet_ids)" \
  -var="eks_node_security_group_id=...your node SG..." \
  -var="raw_bucket_arn=$(terraform -chdir=../../infra\  output -raw raw_bucket_arn)" \
  -var="firehose_app_stream_name=monitoring-mlops-dev-app"
```

This creates: ECR repos, RDS MySQL (with slow-query log → CloudWatch →
Firehose), ElastiCache Redis, KMS keys, security groups, secrets.

## Step 3 — Deploy the 3 services

```bash
cd monitoring-mlops/demo-app

# Namespace
kubectl create namespace demo --dry-run=client -o yaml | kubectl apply -f -

# Inject DB password as a K8s secret (External Secrets in prod)
SECRET_ARN=$(terraform -chdir=infra output -raw rds_secret_arn)
DB_PW=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" \
  --query SecretString --output text | jq -r .password)
kubectl -n demo create secret generic demo-db --from-literal=DB_PASSWORD="$DB_PW" \
  --dry-run=client -o yaml | kubectl apply -f -

# Deploy services
for svc in api worker web; do
  helm upgrade --install demo-$svc helm/demo-service \
    --namespace demo \
    --set image.tag=dev \
    -f helm/demo-service/values-${svc}.yaml
done

# Wait for ready
kubectl -n demo rollout status deployment/demo-api
kubectl -n demo rollout status deployment/demo-worker
kubectl -n demo rollout status deployment/demo-web
```

The `web` Ingress will provision an ALB. Get its hostname:

```bash
kubectl -n demo get ingress demo-web -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

## Step 4 — Drive traffic

In-cluster CronJob (continuous):

```bash
kubectl apply -f traffic-gen/k8s-cronjob.yaml
# Job re-runs every 30 min for ~25 min each time.
```

Or manually from your laptop:

```bash
HOST=$(kubectl -n demo get ingress demo-web -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

pip install locust==2.30.0
locust -f traffic-gen/locustfile.py --headless \
  --host "https://$HOST" --users 30 --spawn-rate 3 --run-time 15m
```

## Step 5 — Verify each ingestion path

After 10 minutes of traffic:

```bash
ENV=dev
RAW_BUCKET=monitoring-mlops-${ENV}-raw

# 1. ALB access logs (configure ALB to log first; if not, skip)
aws s3 ls s3://${RAW_BUCKET}/raw/source=alb/ --recursive | tail -5

# 2. MySQL slow-query → Firehose (only fires on slow queries; bump DEMO_SLOW_RATE if empty)
aws s3 ls s3://${RAW_BUCKET}/raw/source=app/ --recursive | tail -5

# 3. App stdout → MSK → S3 (if a Kafka Connect S3 sink is wired) OR OpenSearch
curl -k "https://${OPENSEARCH_ENDPOINT}/logs-app-*/_search?size=3&pretty" \
  -u "aiops_admin:${OS_PASSWORD}"

# 4. Prometheus metrics in AMP via AMG dashboard
echo "Open AMG: $(terraform -chdir=../../infra\  output -raw amg_workspace_url)"
# Look for demo_api_requests_total, demo_worker_jobs_total

# 5. OTEL traces in X-Ray
aws xray get-trace-summaries \
  --start-time $(date -u -v-10M +%s) \
  --end-time   $(date -u +%s) \
  --filter-expression 'service("demo-api")' \
  --query 'TraceSummaries[0:3]'

# 6. Anomalies in the scoring API
SCORING_API=https://aiops-${ENV}.monitoring-mlops.example.com
curl -s "$SCORING_API/alerts?limit=10" | jq '.[] | {detector, source, score, ts_seen}'

# 7. AlertManager / SNS notification
aws sns list-subscriptions-by-topic \
  --topic-arn $(terraform -chdir=../../infra\  output -raw billing_sns_arn)
```

## Step 6 — Inject an attack and watch the platform respond

```bash
# Brute force (5 min, ~30 users, all hitting /login with bad credentials)
HOST=$(kubectl -n demo get ingress demo-web -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
DEMO_MODE=attack DEMO_ATTACK=brute-force \
  locust -f traffic-gen/locustfile.py --headless \
  --host "https://$HOST" --users 30 --spawn-rate 5 --run-time 5m
```

Within 90 seconds you should see:
- `demo_api_login_attempts_total{status="wrong_password"}` spiking in AMP
- A z-score alert on `auth_failure_rate` from the streaming statistical detector
- An entry in `/alerts` with `detector=zscore`, `source=app`, `metric_key=app:demo-api-*:auth_failure_rate`

Open the runbook for that alert: `docs/runbooks/brute-force-detected.md`.

## Step 7 — Tear down

```bash
helm -n demo uninstall demo-api demo-worker demo-web
kubectl -n demo delete -f traffic-gen/k8s-cronjob.yaml
cd monitoring-mlops/demo-app/infra && terraform destroy
```

The AIOps platform itself stays intact. Use `monitoring-mlops/scripts/teardown.sh`
to also tear that down.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `demo-api` pods CrashLoopBackOff | Wrong DB endpoint or password in env. Check `kubectl -n demo describe pod demo-api-xxx`. |
| No ALB created | AWS Load Balancer Controller not installed (cluster-addons helmfile not applied). |
| No logs in OpenSearch | Fluent Bit not running, or its IRSA can't write to MSK. `kubectl -n logging logs ds/fluent-bit`. |
| No metrics in AMP | ADOT collector not running, or its IRSA can't sigv4-sign to AMP. |
| No alerts in `/alerts` | Scoring API doesn't have any of the SageMaker endpoints wired (it's still in cold-start). Streaming detector should still fire on z-score; check API logs. |
| MySQL slow-query empty | Bump `DEMO_SLOW_RATE` and `DEMO_SLOW_LATENCY` env vars on `demo-api`. |

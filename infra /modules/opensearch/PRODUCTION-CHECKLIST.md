# OpenSearch — Production Checklist

## What this module creates
- OpenSearch domain, in-VPC, KMS-encrypted
- Fine-grained access (master user in Secrets Manager)
- Slow-query, slow-search, and audit logs to CloudWatch
- IAM role list for IRSA-based access from the EKS scoring API + Lambda detectors

## Pre-apply gates
- [ ] **`instance_type`** — `t3.small.search` in dev (~$26/instance/month, 2 instances = ~$52). Prod minimum: `r6g.large.search` (~$130/instance/month, 3 nodes = ~$390/month + storage).
- [ ] **`instance_count`** — must be ≥ 2 in dev for AZ-awareness. Use 3 in prod.
- [ ] **Dedicated master nodes** — not enabled here. For prod over 6 data nodes, set `dedicated_master_enabled = true` (extra ~$100/month for 3 small masters).
- [ ] **`ebs_volume_size_gb`** — 50 GB is enough for ~7 days at moderate log volume. Bump per `ClusterUsedSpace` × growth rate.
- [ ] **AD plugin detectors** — created via the OpenSearch REST API after domain is up; provision via a Lambda + CloudFormation custom resource OR a CI step. Detectors to seed:
  - `request_rate_anomaly` over `logs-alb-*`
  - `error_rate_anomaly` over `logs-app-*`
  - `latency_anomaly` over `metrics-otel-*`
  - `auth_failure_anomaly` over `logs-app-*` filtered by `event=login`
- [ ] **Index lifecycle**: hot (7d) → warm (30d) → delete. ISM policy attached via REST API.
- [ ] **Snapshot to S3** — daily snapshot to a dedicated `aiops-aos-snapshots` bucket. Not in this module; configure via the OpenSearch API after first apply.
- [ ] **Access policy** is permissive `es:*` on `*` principal — narrow this after IAM role list is finalised.
- [ ] **TLS 1.2 minimum** — already set.

## Cost
- Domain compute: ~$52/month (dev) / ~$400/month (prod)
- Storage: $0.135/GB-month (gp3)
- A 3-node prod with 200 GB: ~$430-500/month all-in
- Data transfer: free in-region

## Limits
- Schema changes on existing indices: not possible. Use index aliases + reindex.
- AD plugin: max 60 detectors per domain.
- API throttling at high QPS: use `_msearch` for batch reads.

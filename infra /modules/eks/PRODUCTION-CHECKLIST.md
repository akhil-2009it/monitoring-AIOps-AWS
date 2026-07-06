# EKS — Production Checklist

## What this module creates
- EKS cluster (control plane) with all log types enabled
- 1 managed node group (general workloads)
- IRSA OIDC provider
- IRSA role for `recommendation-api` service account
- ECR repos for `recommendation-api`, `rl-agent`
- Lifecycle policy: keep last 20 ECR images

## Pre-apply gates
- [ ] **`endpoint_public_access = true`** — restrict to known CIDRs in prod via `public_access_cidrs`. Currently the K8s API is reachable from any IP.
- [ ] **Add `aws_eks_cluster.access_config = { authentication_mode = "API_AND_CONFIG_MAP" }`** to enable EKS access entries (newer, replaces aws-auth ConfigMap)
- [ ] **`enabled_cluster_log_types`** — all 5 enabled. CloudWatch ingest cost: ~$0.50/GB. Cluster audit logs are hot-loud; either a 14-day retention or a Firehose→S3 archival path saves money.
- [ ] **Node group instance types**: `m5.large` is fine for dev. For prod, use `m6i.large` (~10% cheaper) or Graviton (`m7g.large`, ~20% cheaper).
- [ ] **Spot instances** for non-critical workloads (RL agent training, batch jobs). Add a second node group with `capacity_type = "SPOT"`.
- [ ] **PodSecurityStandard**: enforce `restricted` profile per namespace (`api`, `monitoring`, etc.) — not in TF; configure via `kustomize/` or a Helm post-install.
- [ ] **NetworkPolicy default-deny per namespace** — set in cluster-addons (Calico/Cilium).
- [ ] **EBS CSI driver** — install via cluster-addons; without it, PVCs fail. The IAM role for the CSI service account is a separate IRSA.
- [ ] **CloudWatch Container Insights** — adds ~$0.30/GB ingest. Worth it for prod observability.
- [ ] **Cluster Autoscaler** — add IRSA + helm chart. Without it, node group scaling is manual.
- [ ] **Karpenter** alternative to ASG-based autoscaling — much faster scale-up. Worth evaluating for prod.
- [ ] **SG hardening**: cluster SG allows `0.0.0.0/0` egress. Add explicit egress to RDS, SageMaker endpoints, Kinesis only.

## ECR
- [ ] **Image scanning on push** — already enabled.
- [ ] **`image_tag_mutability = MUTABLE`** — switch to IMMUTABLE for prod (forces every deploy to use a new tag, prevents `latest` rollback foot-gun).
- [ ] **Lifecycle policy** keeps 20 images. Sized for ~1 deploy/day for 3 weeks.

## IRSA
- [ ] **`recommendation-api` IRSA** scopes are reasonable (Feature Store read, endpoint invoke for `*-${env}`, secrets project-prefix). Verify the SA name matches your helm chart's `serviceAccount.name`.
- [ ] Add IRSA roles for: cluster-autoscaler, external-secrets, aws-load-balancer-controller, external-dns. None are created here.

## Cost
- EKS control plane: $0.10/hour ≈ **$73/month** per cluster
- 2× m5.large nodes 24x7: ~$140/month
- NAT Gateway (in VPC module): ~$32/month + data charges. Single NAT in dev saves $96/month vs multi-AZ.

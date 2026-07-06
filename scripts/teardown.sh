#!/usr/bin/env bash
# AIOps platform teardown — order matters.
#
#   1. SageMaker real-time + async endpoints     (highest ongoing cost)
#   2. EKS node groups → 0
#   3. MSK cluster                                (~$100/mo if left running)
#   4. OpenSearch domain                          (~$50-400/mo)
#   5. Firehose delivery streams
#   6. RDS stop                                    (preserve data)
#   7. terraform destroy                          (--full-destroy only)
#   8. Manual checks (S3, CW Logs, ECR, GuardDuty findings export)
#
# Usage:
#   bash scripts/teardown.sh --env dev --confirm
#   bash scripts/teardown.sh --env dev --full-destroy --confirm

set -euo pipefail

ENV=""; FULL=0; CONFIRM=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV="$2"; shift 2;;
    --full-destroy) FULL=1; shift;;
    --confirm) CONFIRM=1; shift;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done
[[ -n "$ENV" ]] || { echo "Required: --env <dev|qa|prod>" >&2; exit 2; }
[[ "$CONFIRM" == 1 ]] || { echo "Refusing without --confirm" >&2; exit 2; }

PREFIX="monitoring-mlops-${ENV}"
REGION="${AWS_REGION:-ap-south-1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Teardown: env=$ENV region=$REGION full_destroy=$FULL ==="

# ── 1. SageMaker endpoints ────────────────────────────────────────────────
echo "[1/8] Deleting SageMaker endpoints..."
for ep in $(aws sagemaker list-endpoints --region "$REGION" \
            --name-contains "$ENV" \
            --query "Endpoints[].EndpointName" --output text 2>/dev/null || echo ""); do
  echo "    -> deleting endpoint $ep"
  aws sagemaker delete-endpoint --endpoint-name "$ep" --region "$REGION" || true
done

# ── 2. Scale EKS node groups to 0 ─────────────────────────────────────────
echo "[2/8] Scaling EKS node groups to 0..."
for ng in $(aws eks list-nodegroups --cluster-name "$PREFIX" --region "$REGION" \
            --query "nodegroups[]" --output text 2>/dev/null || echo ""); do
  echo "    -> scaling $ng to 0"
  aws eks update-nodegroup-config --cluster-name "$PREFIX" --nodegroup-name "$ng" \
    --scaling-config minSize=0,maxSize=1,desiredSize=0 --region "$REGION" || true
done

# ── 3. MSK ────────────────────────────────────────────────────────────────
if [[ "$FULL" == 1 ]]; then
  echo "[3/8] Deleting MSK..."
  for arn in $(aws kafka list-clusters --region "$REGION" \
              --query "ClusterInfoList[?starts_with(ClusterName, \`$PREFIX\`)].ClusterArn" --output text); do
    aws kafka delete-cluster --cluster-arn "$arn" --region "$REGION" || true
  done
else
  echo "[3/8] MSK skipped (use --full-destroy)."
fi

# ── 4. OpenSearch ─────────────────────────────────────────────────────────
if [[ "$FULL" == 1 ]]; then
  echo "[4/8] Deleting OpenSearch domains..."
  for domain in $(aws opensearch list-domain-names --region "$REGION" \
                 --query "DomainNames[?starts_with(DomainName, \`$PREFIX\`)].DomainName" --output text); do
    aws opensearch delete-domain --domain-name "$domain" --region "$REGION" || true
  done
else
  echo "[4/8] OpenSearch skipped (use --full-destroy)."
fi

# ── 5. Firehose ──────────────────────────────────────────────────────────
if [[ "$FULL" == 1 ]]; then
  echo "[5/8] Deleting Firehose delivery streams..."
  for s in $(aws firehose list-delivery-streams --region "$REGION" \
            --query "DeliveryStreamNames" --output text); do
    if [[ "$s" == "$PREFIX"* ]]; then
      aws firehose delete-delivery-stream --delivery-stream-name "$s" --region "$REGION" || true
    fi
  done
fi

# ── 6. RDS ────────────────────────────────────────────────────────────────
echo "[6/8] Stopping RDS..."
aws rds stop-db-instance --db-instance-identifier "${PREFIX}-mysql" --region "$REGION" 2>/dev/null \
  || echo "    RDS already stopped or not found."

# ── 7. terraform destroy ──────────────────────────────────────────────────
if [[ "$FULL" == 1 ]]; then
  echo "[7/8] terraform destroy..."
  cd "$ROOT/infra "
  terraform workspace select "$ENV" >/dev/null
  terraform destroy -auto-approve
  cd "$ROOT"
fi

# ── 8. Manual-check reminders ─────────────────────────────────────────────
echo
echo "[8/8] Manual checks (terraform may leave these):"
echo "    - S3 versioned buckets:  aws s3 ls | grep ${PREFIX}-"
echo "    - GuardDuty: still enabled? aws guardduty list-detectors --region $REGION"
echo "    - Security Hub: aws securityhub describe-hub --region $REGION"
echo "    - CW Logs:    aws logs describe-log-groups --log-group-name-prefix /aws/${PREFIX}"
echo "    - ECR:        aws ecr describe-repositories --query 'repositories[?starts_with(repositoryName, \\\`monitoring-mlops\\\`)]'"
echo
echo "Done. Verify AWS Billing dashboard 24 hours from now."

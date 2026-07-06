#!/usr/bin/env bash
# bootstrap_state.sh — Run ONCE before `terraform init`
# Creates the S3 state bucket + DynamoDB lock table.
# Requires: AWS CLI configured with mlops-learning profile, region ap-south-1.
set -euo pipefail

PROFILE="${AWS_PROFILE:-mlops-learning}"
REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
STATE_BUCKET="mlops-learning-tfstate"
LOCK_TABLE="mlops-learning-tfstate-lock"

echo "Bootstrap: account=$ACCOUNT_ID region=$REGION"

# ── S3 state bucket ───────────────────────────────────────────────────────────
if aws s3api head-bucket --bucket "$STATE_BUCKET" --profile "$PROFILE" 2>/dev/null; then
  echo "State bucket $STATE_BUCKET already exists — skipping creation."
else
  aws s3api create-bucket \
    --bucket "$STATE_BUCKET" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" \
    --profile "$PROFILE"

  aws s3api put-bucket-versioning \
    --bucket "$STATE_BUCKET" \
    --versioning-configuration Status=Enabled \
    --profile "$PROFILE"

  aws s3api put-bucket-encryption \
    --bucket "$STATE_BUCKET" \
    --server-side-encryption-configuration '{
      "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]
    }' \
    --profile "$PROFILE"

  aws s3api put-public-access-block \
    --bucket "$STATE_BUCKET" \
    --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
    --profile "$PROFILE"

  echo "Created state bucket: $STATE_BUCKET"
fi

# ── DynamoDB lock table ───────────────────────────────────────────────────────
if aws dynamodb describe-table --table-name "$LOCK_TABLE" --region "$REGION" --profile "$PROFILE" 2>/dev/null; then
  echo "Lock table $LOCK_TABLE already exists — skipping creation."
else
  aws dynamodb create-table \
    --table-name "$LOCK_TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" \
    --profile "$PROFILE"
  echo "Created DynamoDB lock table: $LOCK_TABLE"
fi

echo ""
echo "✅ Bootstrap complete. Now run:"
echo ""
echo "  cd terraform/"
echo "  terraform init"
echo "  terraform workspace new dev   # or: terraform workspace select dev"
echo "  terraform plan -out=tfplan"
echo "  terraform apply tfplan"

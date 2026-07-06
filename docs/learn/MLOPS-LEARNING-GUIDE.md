---
title: "MLOps Learning Guide — From First Principles to Two Production Pipelines"
author: "Owner"
date: "2026-06-19"
---

# MLOps Learning Guide

A complete walk-through of two production-grade MLOps pipelines on AWS, written
for someone who wants to *understand* MLOps, not just deploy it.

This document walks every layer, every Terraform module, every Python file, and
every operational decision in two sibling projects:

1. **`mlops/`** — a personalized learning platform (student MCQ recommendation)
2. **`monitoring-mlops/`** — an AIOps + Security Analytics platform (anomaly + threat detection)

Both projects use the same MLOps "shell" (the infra + ops pattern). What
differs is the *ML payload* — the data, models, features, and APIs. Once you
understand the shell, you can apply it to a third domain (fraud, recommendation,
forecasting, content moderation, etc.).

---

## Table of contents

- [Part 1 — Fundamentals: what MLOps is and why each layer exists](#part-1--fundamentals)
- [Part 2 — Walking the `mlops/` project layer by layer](#part-2--walking-the-mlops-project)
- [Part 3 — Walking the `monitoring-mlops/` project (AIOps)](#part-3--walking-the-monitoring-mlops-project)
- [Part 4 — Day-2 operations](#part-4--day-2-operations)
- [Part 5 — Compare, contrast, and what to learn next](#part-5--compare-contrast-and-what-to-learn-next)

---

# Part 1 — Fundamentals

## 1.1 What is MLOps?

MLOps is **DevOps for machine learning systems**. The promise: take a model
from a Jupyter notebook to production, retrain it on new data automatically,
detect when it stops working, and roll forward without 3 a.m. heroics.

That promise has three hard problems that classical DevOps doesn't solve:

1. **Code is one input. Data is another.** A bug-free pipeline trained on
   stale or biased data produces a broken model. So MLOps versions data,
   features, *and* code.
2. **Models silently rot.** A model that predicted well last quarter may
   degrade because the world changed (concept drift) or the input
   distribution shifted (data drift). MLOps measures this continuously and
   triggers retraining when it crosses a threshold.
3. **Inference latency is part of the SLA.** A 95% accurate model that
   takes 5 seconds is unusable for a real-time recommendation. MLOps treats
   serving as a first-class engineering problem (autoscaling, circuit
   breakers, async fan-out).

If you're new to the term, the quick mental model is:

> MLOps = data engineering + classical DevOps + monitoring on the *quality*
> of predictions, not just the health of the servers serving them.

## 1.2 The 7-layer architecture

Both projects in this repo are organised into 7 layers. Knowing them by
heart makes every other decision easier to reason about:

```
L1  Data Sources         Where signal originates (databases, logs, mobile SDK)
L2  Ingestion            Get data off those sources reliably (Kinesis, MSK, Firehose)
L3  Lake / Index         Store it for batch + interactive analytics (S3, OpenSearch)
L4  Feature Engineering  Turn raw events into ML-ready features (Processing Jobs, Feature Store)
L5  Model Training        Train, evaluate, and gate registration (SageMaker Pipelines)
L6  Registry + Deploy     Version, approve, deploy, route traffic (Model Registry, CodePipeline, Endpoints)
L7  Monitoring             Watch the models in production (drift, latency, error budget, retrain triggers)
```

These are not arbitrary. They follow the natural data flow from raw signal
to operational alerting, and each layer is a tested abstraction boundary —
you can swap out any one layer (e.g., replace Kinesis with Kafka) without
rewriting the others.

The two projects use the *same 7 layers*, but the *content* of L4 and L5
diverges:

|   | `mlops/` (Student MCQ)                   | `monitoring-mlops/` (AIOps)             |
|---|------------------------------------------|------------------------------------------|
| L4 | per-student aggregates, 12 features      | per-(source, host, window) sliding-window features |
| L5 | 4 supervised models (XGBoost, RF, LSTM, RF) | 4 unsupervised detectors (RCF, IForest, LSTM-AE, LogBERT-lite) + streaming statistical |

## 1.3 Why each layer exists

### L1 — Data Sources

The whole pipeline is downstream of data. If you can't reliably get data off
your databases, no amount of model brilliance will help. Layer 1's job is to
*not lose data* during normal operation, planned maintenance, or partial outages.

In `mlops/`: student events come from a mobile SDK + LMS. We assume push
delivery to Kinesis.

In `monitoring-mlops/`: 14 different log/metric/trace sources feeding multiple
ingestion paths. The hard part is heterogeneous formats; we solve that by
normalising every source to a `CommonEvent` schema in L2.

### L2 — Ingestion

Data has to flow somewhere durable, fast, and replayable. The two choices
in this repo:

- **Kinesis Firehose** — simple, managed, "set buffer + S3 path and forget".
  Best for AWS-native log sources (CloudFront, ALB, WAF, EKS). Pricing per GB.
- **MSK (Managed Kafka)** — high-throughput, replayable for days, supports
  complex consumer patterns (multiple downstream apps reading the same
  stream). Best for app-level logs that many consumers want.

`mlops/` uses just Kinesis Data Streams (the cousin of Firehose) because the
data volume is moderate. `monitoring-mlops/` uses both.

### L3 — Lake / Index

Two storage shapes for two access patterns:

- **S3 + Glue** — cheap, durable, queryable via Athena. Good for batch ML
  training (read 30 days of features once) and analyst ad-hoc queries.
- **OpenSearch** — fast text search + per-field aggregations. Good for
  interactive log dashboards and the OpenSearch Anomaly Detection plugin
  (which gives you a quick AD baseline before SageMaker is ready).

`mlops/` uses just S3. `monitoring-mlops/` uses both because security
analysts need full-text search.

### L4 — Feature Engineering

Raw data isn't ML-ready. You have to:

- Aggregate (compute averages, percentiles, counts over windows).
- Join (look up a student's history when scoring).
- Encode (one-hot categoricals, hash high-cardinality strings).
- Materialise (write the aggregated row to a Feature Store so training and
  inference see the *same* feature definitions).

The Feature Store is critical. Without it, your training pipeline computes a
feature one way, your API computes it another way, and the model is silently
wrong in production. SageMaker Feature Store gives you an *online* store
(fast lookups for inference) and an *offline* store (S3 Parquet for training).

### L5 — Model Training

A SageMaker Pipeline is a directed acyclic graph (DAG) of steps. Both
projects use the same 5-step shape:

```
data_validation → feature_extraction → train → evaluate → conditional_register
```

The `conditional_register` step is the **metric gate**: if the model's
evaluation metric is worse than the threshold, the pipeline stops without
registering. This is the difference between an MLOps pipeline and "just a
script that trains" — bad models can't accidentally promote to production.

### L6 — Registry + Deploy

Models go through three states:

1. **Pending** (just registered, not approved)
2. **Approved** (a human looked at the metrics + bias report and clicked OK)
3. **Rejected** (a human said no)

Approval triggers CodePipeline, which deploys the new model to a SageMaker
endpoint with rolling traffic shift (blue/green). The API code doesn't
change — it just calls the same endpoint name.

### L7 — Monitoring

Three things to monitor, each with its own alarm:

- **Endpoint health** (latency, error rate). Same as any service.
- **Data drift** on detector inputs. PSI > 0.20 = retrain.
- **Model performance** in prod (when ground truth is available). Auto-FP-rate.

Drift triggers an EventBridge rule → Lambda → starts the SageMaker Pipeline
again, closing the loop. This is the auto-retrain pattern.

## 1.4 Pre-requisites you should know before reading further

If you're shaky on any of these, skim a primer first:

- **Terraform basics**: providers, modules, variables, outputs, state.
- **AWS basics**: IAM roles vs policies, S3 buckets + KMS, VPC + subnets.
- **Kubernetes basics**: Deployment, Service, ConfigMap, IRSA, namespaces.
- **Python basics**: type hints, async/await, FastAPI request handlers.
- **ML basics**: train/test split, classification vs regression, what overfitting is.

You don't need to be an expert — the projects use these tools in fairly idiomatic
ways. But "what is a Terraform provider" should not be a surprise.

---

# Part 2 — Walking the `mlops/` project

This is the simpler of the two projects: a personalized learning platform that
recommends MCQs to students based on their performance history. We're going to
walk it bottom-up, in the order Terraform applies modules.

## 2.1 Repository layout

```
mlops/
├── README.md                      ← project bible (read this first in real life)
├── adaptive-mcq-platform.jsx      ← client-side React app (kept for reference)
├── infra /                        ← Terraform (note trailing space in dir name)
│   ├── main.tf, variables.tf, outputs.tf, backend.tf
│   ├── bootstrap_state.sh         ← one-time S3 + DynamoDB lock setup
│   └── modules/{datalake, streaming, sagemaker, eks, database, monitoring,
│                cicd, cognito, alb, waf, cloudtrail, billing}/
├── data/                          ← question bank + dev event log
├── ml/
│   ├── feature_engineering/       ← per-student feature builders
│   ├── training/                   ← local trainer (legacy, dev convenience)
│   ├── pipelines/{performance_predictor, dropout_risk, knowledge_tracing,
│                  difficulty_classifier, _shared}/   ← SageMaker Pipelines
│   ├── monitoring/                 ← drift detection (PSI/KL on features)
│   └── inference/                  ← local recommender (dev fallback)
├── api/recommendation/            ← FastAPI service on EKS
├── helm/charts/recommendation-api/ ← K8s manifests
├── helm/cluster-addons/           ← Helmfile for ALB controller, ArgoCD, etc.
├── scripts/{seed_synthetic_data, retrain, smoke_test, teardown, inject_drift}.py
├── tests/{unit, integration, load}/
├── docs/{architecture, slo-definitions, PRODUCTION-CHECKLIST}.md + runbooks/
├── argocd/                         ← app-of-apps + per-service Application
├── .github/workflows/             ← terraform plan/apply, api CI, ml-pipeline-trigger
├── pyproject.toml                  ← single source of truth for Python deps
└── Makefile                        ← convenience targets
```

## 2.2 The bootstrap (one-time-only setup)

Before you run any Terraform, you need somewhere for Terraform to *store its
state file*. State is the source of truth Terraform consults to know "what
exists right now"; if two engineers run terraform apply at the same time and
share local state, they'll corrupt it.

`infra /backend.tf` declares the backend:

```hcl
terraform {
  backend "s3" {
    bucket         = "mlops-learning-tfstate"
    key            = "mlops-learning/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "mlops-learning-tfstate-lock"
    encrypt        = true
  }
}
```

That bucket and DynamoDB lock table can't be created *by* Terraform (chicken-and-egg).
`infra /bootstrap_state.sh` is the one-time setup:

```bash
PROFILE="${AWS_PROFILE:-mlops-learning}"
ACCOUNT_ID=$(aws sts get-caller-identity --profile $PROFILE --query Account --output text)

aws s3api create-bucket --bucket mlops-learning-tfstate --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1 --profile $PROFILE
aws s3api put-bucket-versioning --bucket mlops-learning-tfstate \
  --versioning-configuration Status=Enabled --profile $PROFILE
aws s3api put-bucket-encryption --bucket mlops-learning-tfstate \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"}}]}' \
  --profile $PROFILE
aws s3api put-public-access-block --bucket mlops-learning-tfstate \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
  --profile $PROFILE

aws dynamodb create-table --table-name mlops-learning-tfstate-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --region ap-south-1 --profile $PROFILE
```

Why each line:
- **versioning enabled**: state files get corrupted by partial writes. Versioning
  lets you roll back to last good state.
- **KMS encryption**: state contains secrets (passwords, API keys). Encrypt at rest.
- **public access block**: belt-and-braces. Prevents accidental public exposure.
- **DynamoDB lock**: Terraform acquires a row in this table before modifying state.
  Concurrent applies wait or fail — never corrupt.

Run it once, never again.

## 2.3 The root Terraform module

`infra /main.tf` is the orchestrator. It composes 14 sub-modules in a specific
order driven by data dependencies:

```hcl
provider "aws"          { region = var.aws_region; default_tags { tags = local.common_tags } }
provider "aws"          { alias = "useast1"; region = "us-east-1"; default_tags { tags = local.common_tags } }

module "vpc"            { source = "terraform-aws-modules/vpc/aws"; ... }
module "datalake"       { source = "./modules/datalake";       depends_on = [module.vpc] }
module "streaming"      { source = "./modules/streaming";      depends_on = [module.datalake] }
module "sagemaker"      { source = "./modules/sagemaker";      depends_on = [module.datalake] }
module "eks"            { source = "./modules/eks";            depends_on = [module.vpc] }
module "database"       { source = "./modules/database";       depends_on = [module.vpc] }
module "monitoring"     { source = "./modules/monitoring";     depends_on = [module.streaming, module.sagemaker] }
module "cloudtrail"     { source = "./modules/cloudtrail" }
module "billing"        { source = "./modules/billing"; providers = { aws.useast1 = aws.useast1 } }
module "cognito"        { source = "./modules/cognito" }
module "waf"            { source = "./modules/waf" }
module "alb"            { source = "./modules/alb"; count = var.api_hostname != "" ? 1 : 0 }
resource "aws_route53_record" "api" { count = ... }
module "cicd"           { source = "./modules/cicd"; depends_on = [module.sagemaker, module.eks] }
```

Two important patterns here:

1. **Two providers** — most resources go to `ap-south-1` (Mumbai). But AWS
   *Billing* metrics only emit from `us-east-1`. So we declare a second
   provider with alias `useast1` and pass it to the `billing` module.
2. **Conditional creation with `count = ... ? 1 : 0`** — the ALB module only
   creates resources if the user provides a hostname + ACM cert. This is the
   Terraform way of saying "optional dependency".

## 2.4 Layer 3 — the data lake (`modules/datalake/`)

This module creates 5 KMS-encrypted, versioned, fully-blocked S3 buckets, plus
Glue catalog and Lake Formation registration.

`modules/datalake/main.tf`:

```hcl
locals {
  prefix = "${var.project}-${var.environment}"
  buckets = {
    raw         = "${local.prefix}-raw"           # raw events from Kinesis
    processed   = "${local.prefix}-processed"     # post-ETL Parquet
    features    = "${local.prefix}-features"      # Feature Store offline
    models      = "${local.prefix}-models"        # trained model artifacts
    predictions = "${local.prefix}-predictions"   # batch inference output
  }
}

resource "aws_kms_key" "datalake" {
  description             = "${local.prefix} data lake encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_s3_bucket" "buckets" {
  for_each      = local.buckets
  bucket        = each.value
  force_destroy = var.environment != "prod"   # in prod, never delete buckets with data
}

resource "aws_s3_bucket_versioning" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.datalake.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "buckets" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.buckets[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

The teaching points:

- **`for_each` over a map** instead of repeating 5 resource blocks. Terraform's
  way of "DRY".
- **Naming convention** `${project}-${environment}-{purpose}`. Globally
  unique buckets need careful naming; if two AWS accounts try to claim
  `mlops-raw`, the second loses.
- **`force_destroy`** depends on environment. In dev we let `terraform destroy`
  wipe the bucket even if it has objects (otherwise you'd have to `aws s3 rm`
  first). In prod, this is a foot-gun — set to false so a misclick can't
  delete a year of data.
- **Bucket key enabled (`bucket_key_enabled = true`)** drops your KMS bill
  by ~99% on high-IO buckets. Without it, every S3 GET makes a KMS call.
- **Default-deny public access** — the four `block_*` flags are belt-and-braces.
  Even if a future IAM mistake grants public bucket policy, S3 itself refuses.

The lifecycle rules transition raw data to Glacier after 90 days and expire
processed data after 365 days. Why these defaults? Because:
- Raw events you'll almost never re-read after a week, so Glacier (cheap, slow)
  is fine.
- Processed data feeds analytics dashboards; 365 days of history is enough
  for year-over-year compare; older data goes to a separate "archive" path
  if needed (FERPA/GDPR retention rules vary).

## 2.5 Layer 2 — streaming (`modules/streaming/`)

Three resources stitched together: Kinesis Data Stream, a Lambda consumer,
and an SQS dead-letter queue.

```
producer ──► Kinesis stream ──► Lambda (event source mapping) ──► S3 raw bucket
                                       │
                                       └──(on failure)──► SQS DLQ
```

`modules/streaming/main.tf`:

```hcl
resource "aws_kinesis_stream" "events" {
  name             = "${local.prefix}-events"
  shard_count      = var.kinesis_shard_count    # default 2
  retention_period = var.kinesis_retention_hours # default 48h
  encryption_type  = "KMS"
  kms_key_id       = "alias/aws/kinesis"
  stream_mode_details { stream_mode = "PROVISIONED" }
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${local.prefix}-events-dlq"
  message_retention_seconds = 1209600   # 14 days
  kms_master_key_id         = "alias/aws/sqs"
}

resource "aws_iam_role" "lambda_consumer" { ... }   # trusted by lambda.amazonaws.com
resource "aws_iam_role_policy" "lambda_kinesis_s3" { ... }   # least-privilege

data "archive_file" "lambda_placeholder" {
  type        = "zip"
  output_path = "${path.module}/lambda_placeholder.zip"
  source {
    content  = <<-PYTHON
      import json, base64, boto3, os, datetime
      s3 = boto3.client('s3')
      def handler(event, context):
          records = [json.loads(base64.b64decode(r['kinesis']['data'])) for r in event['Records']]
          key = f"student_events/year={...}/month={...}/{context.aws_request_id}.json"
          s3.put_object(Bucket=os.environ['RAW_BUCKET'], Key=key, Body=json.dumps(records))
          return {"statusCode": 200}
    PYTHON
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "kinesis_consumer" {
  function_name    = "${local.prefix}-kinesis-consumer"
  role             = aws_iam_role.lambda_consumer.arn
  handler          = "handler.handler"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout_sec
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  dead_letter_config { target_arn = aws_sqs_queue.dlq.arn }
  tracing_config    { mode = "Active" }   # X-Ray
}

resource "aws_lambda_event_source_mapping" "kinesis_trigger" {
  event_source_arn               = aws_kinesis_stream.events.arn
  function_name                  = aws_lambda_function.kinesis_consumer.arn
  starting_position              = "LATEST"
  batch_size                     = var.batch_size
  bisect_batch_on_function_error = true   # ← important
  destination_config {
    on_failure { destination_arn = aws_sqs_queue.dlq.arn }
  }
}
```

What's happening:

- The Kinesis stream is the durable buffer. Even if the Lambda is down for
  47 hours, no data is lost (retention = 48h).
- The Lambda subscribes via an *event source mapping* — AWS pulls records
  from Kinesis and invokes the Lambda with batches of records.
- `bisect_batch_on_function_error = true` means: if a batch of 100 fails
  because of one bad record, AWS automatically splits it in half, retries,
  splits the failing half again, and so on. The good 99 records still get
  processed. Without this, one poison-pill record can stall the entire shard
  for hours.
- `destination_config.on_failure` sends records the Lambda *gave up on* to
  SQS DLQ. Now you have a forensic record of every event that couldn't be
  processed.
- The Lambda code itself is a placeholder — real code goes in via CI/CD
  (`aws lambda update-function-code`). Terraform creates the function shell;
  CI keeps the code fresh. This separation matters because Terraform applies
  are slow (minutes) and rare; code updates should be fast (seconds) and
  frequent.

## 2.6 Layer 4–6 — SageMaker (`modules/sagemaker/`)

This module is the heart of the ML platform. It creates:

1. The SageMaker execution role (the IAM role training jobs and endpoints
   assume).
2. The Feature Group with its 16-feature schema.
3. The 4 Model Package Groups (one per model: perf-predictor,
   knowledge-tracing, dropout-risk, difficulty-classifier).
4. A placeholder Model Monitor schedule.
5. CloudWatch log groups.

The most important thing to internalize: **the Feature Group's schema is
immutable once created**. If you change a feature definition, SageMaker
won't update the existing group; you have to create `student-features-v2`
and migrate. So the Feature Group resource is the single most-consequential
declaration in the entire repo.

```hcl
resource "aws_sagemaker_feature_group" "student_features" {
  feature_group_name             = "${var.project}-student-features-v1"
  record_identifier_feature_name = "student_id"
  event_time_feature_name        = "feature_timestamp"
  role_arn                       = aws_iam_role.sagemaker_exec.arn

  online_store_config { enable_online_store = true }   # DynamoDB-backed, <10ms reads
  offline_store_config {
    s3_storage_config { s3_uri = "s3://${var.feature_store_bucket}/feature-store/" }
    disable_glue_table_creation = false
  }

  feature_definition { feature_name = "student_id";        feature_type = "String" }
  feature_definition { feature_name = "feature_timestamp"; feature_type = "String" }
  feature_definition { feature_name = "avg_score_7d";      feature_type = "Fractional" }
  feature_definition { feature_name = "avg_score_30d";     feature_type = "Fractional" }
  # ...12 more feature definitions...
}
```

The dual store design (online + offline):
- **Online store** is DynamoDB under the hood. The API does sub-10ms reads
  for inference. You write the latest feature value with `PutRecord`; the
  store keeps only the most recent.
- **Offline store** is S3 Parquet partitioned by event time. Used by training
  pipelines that need "what was this feature at time T?" — point-in-time
  correct lookups for honest train/val splits.

The IAM role policy is interesting too:

```hcl
resource "aws_iam_role_policy" "sagemaker_s3_access" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
        Resource = [
          "arn:aws:s3:::${var.project}-${var.environment}-*",
          "arn:aws:s3:::${var.project}-${var.environment}-*/*"
        ]
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:${var.project}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = { StringEquals = { "cloudwatch:namespace" = "mlops-learning/models" } }
      }
    ]
  })
}
```

The key technique is **Resource ARN scoping**:
- S3: only buckets named with the project+env prefix. A SageMaker job can't
  read other people's buckets in the same account.
- Secrets Manager: only secrets in the `${project}/*` path.
- CloudWatch: any resource (`*`), but constrained by `Condition` to a single
  namespace. So the role can put metrics, but only under one namespace.

This is least-privilege done with grace. Compare it to the SageMaker
`AmazonSageMakerFullAccess` managed policy (also attached) which grants `s3:*`
on every bucket — that's why prod hardening (per the checklist) replaces it
with this scoped-down version.

## 2.7 Layer 6 — EKS (`modules/eks/`)

EKS is where the FastAPI service lives. The module creates:

- The EKS cluster + node group
- The OIDC provider (so K8s service accounts can assume IAM roles — IRSA)
- A scoped IAM role for the recommendation API service account
- ECR repositories for the API image
- CloudWatch log groups

The IRSA pattern is worth a separate paragraph. Without it, your pod has
two bad options:

1. Mount AWS credentials as a K8s Secret. Now your IAM keys are sitting in
   etcd and a kubectl get secret gives them up.
2. Give the EC2 node IAM permissions. Now every pod on that node has them,
   not just yours.

IRSA solves this by making the K8s service account assume an AWS IAM role
via OIDC federation. The pod gets temporary AWS credentials with only the
permissions you scoped, no static keys anywhere.

```hcl
data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# IRSA role for the recommendation-api service account
data "aws_iam_policy_document" "recommendation_api_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub"
      values   = ["system:serviceaccount:api:recommendation-api"]
    }
  }
}
```

Two lines do the heavy lifting:
- The `principals` block says: only requests federated through *this specific
  EKS cluster's OIDC provider* may assume the role.
- The `condition` block says: only requests where the JWT's `sub` claim is
  `system:serviceaccount:api:recommendation-api` may assume. That's the
  fully-qualified K8s service account name (`<namespace>:<name>`).

So the only thing in the world that can assume this role is a pod running
under that exact service account on that exact cluster. Nobody else.

The node group itself uses managed node groups (AWS handles the EC2
provisioning and lifecycle):

```hcl
resource "aws_eks_node_group" "general" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${local.prefix}-general"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = var.node_instance_types     # default ["m5.large"]

  scaling_config {
    min_size     = var.node_min_size              # default 2
    max_size     = var.node_max_size              # default 6
    desired_size = var.node_desired_size          # default 2
  }

  update_config { max_unavailable = 1 }
}
```

The `update_config.max_unavailable = 1` is the controlled-rollout knob. When
you upgrade the node group's AMI, AWS drains nodes one at a time, never
breaking the workload's availability.

## 2.8 Layer 1 (PII) — RDS (`modules/database/`)

The RDS MySQL instance holds **only the PII** — name, email, phone,
encrypted with column-level encryption. It is *never* part of the ML
training data. The ML pipeline sees only `student_id` (UUID).

This separation is one of the project's load-bearing rules (see README.md
rule #4). The reasons are compliance (FERPA, GDPR), security blast radius,
and operational simplicity (you can wipe the entire ML side without
touching student records).

```hcl
resource "random_password" "rds_master" { length = 32; special = true }

resource "aws_secretsmanager_secret" "rds" {
  name                    = "${var.project}/${var.environment}/rds-master-credentials"
  kms_key_id              = aws_kms_key.rds.arn
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "rds" {
  secret_id = aws_secretsmanager_secret.rds.id
  secret_string = jsonencode({
    username = "mlops_admin"
    password = random_password.rds_master.result
    engine   = "mysql"
    host     = aws_db_instance.main.address
    port     = 3306
    dbname   = var.db_name
  })
  depends_on = [aws_db_instance.main]
}

resource "aws_db_instance" "main" {
  identifier        = "${local.prefix}-mysql"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = var.rds_instance_class
  allocated_storage = var.allocated_storage

  db_name  = var.db_name
  username = "mlops_admin"
  password = random_password.rds_master.result

  storage_encrypted       = true
  kms_key_id              = aws_kms_key.rds.arn
  multi_az                = var.environment == "prod" ? true : var.multi_az
  backup_retention_period = var.backup_retention_days
  publicly_accessible     = false
  deletion_protection     = var.environment == "prod"
  skip_final_snapshot     = var.environment != "prod"
  monitoring_interval     = 60
  enabled_cloudwatch_logs_exports = ["error", "slowquery"]

  lifecycle {
    ignore_changes = [password]   # rotation happens via secrets manager, not Terraform
  }
}
```

Things to notice:

- **Random password** generated by Terraform on first apply, stored in
  Secrets Manager. The application reads it from there, never from a
  ConfigMap or env var.
- **`ignore_changes = [password]`** — once Secrets Manager rotates the
  password (via the rotation Lambda), Terraform mustn't try to "fix" it
  back to the original. This is a common source of pain for new
  Terraform users.
- **Multi-AZ in prod** — synchronous replica in another availability zone.
  Doubles cost but survives single-AZ outages with seconds of failover.
- **Deletion protection in prod** — `aws rds delete-db-instance` will refuse
  unless you explicitly disable it first. Prevents the worst kind of typo.

## 2.9 Layer 7 — monitoring (`modules/monitoring/`)

Three categories of monitoring:

1. **Alarms on AWS-managed metrics** (Kinesis lag, endpoint latency, error rate)
2. **Alarms on custom metrics** (PSI from drift detector)
3. **EventBridge → Lambda → SageMaker Pipeline** for auto-retrain

The drift retrain Lambda is the most interesting piece. When a PSI alarm
fires, EventBridge routes the event to a small Lambda that:

```python
def handler(event, context):
    """Triggered by EventBridge when a drift alarm fires."""
    alarm_name = event.get('detail', {}).get('alarmName', '')
    model = next((k for k in PIPELINE_MAP if k in alarm_name), None)
    if not model:
        return {"statusCode": 400}

    pipeline_name = PIPELINE_MAP[model]
    execution_name = f"auto-retrain-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    resp = sm.start_pipeline_execution(
        PipelineName=pipeline_name,
        PipelineExecutionDisplayName=execution_name,
        PipelineParameters=[
            {"Name": "trigger", "Value": "drift-alarm"},
            {"Name": "alarm_name", "Value": alarm_name},
        ]
    )
    return {"statusCode": 200, "pipelineExecutionArn": resp['PipelineExecutionArn']}
```

This is a 30-line function, but it closes a critical loop: when the model
starts misbehaving, the system retrains itself without a human in the loop.
The human appears later — at the model approval gate in the registry.

## 2.10 Layer 5 — SageMaker Pipelines (`ml/pipelines/`)

Each model has its own directory under `ml/pipelines/`. The structure is
the same:

```
ml/pipelines/
├── _shared/
│   ├── pipeline_helpers.py     ← session setup, common parameters, gated register
│   └── data_validation.py       ← reusable first step (PII scan, row count)
├── performance_predictor/
│   ├── pipeline.py              ← the Pipeline definition (DAG)
│   ├── feature_extract.py        ← Processing entrypoint
│   ├── evaluate.py               ← Processing entrypoint
│   └── run_pipeline.py            ← CLI: upsert + start
├── dropout_risk/                 ← same shape, different model
├── knowledge_tracing/             ← same shape, different model
└── difficulty_classifier/         ← same shape, different model
```

`_shared/pipeline_helpers.py` is the centerpiece. It exposes 4 functions
that every model pipeline calls:

- `pipeline_session(region)` — wraps boto3 + SageMaker SDK in a thread-safe
  pipeline session (different from a normal SageMaker session because the
  pipeline definition isn't executed at author time).
- `common_parameters()` — returns the parameters every pipeline shares
  (`trigger`, `alarm_name`, `training_instance_count`).
- `build_processing_step(...)` — constructs an `SKLearnProcessor` step with
  default IAM, instance type, base job name. Used for data validation,
  feature extraction, evaluation steps.
- `build_register_step_with_gate(config, training_step, eval_step,
  primary_metric_name, gate_op, gate_threshold)` — this is the metric gate.
  It builds a `ConditionStep` that uses `JsonGet` to read the evaluation
  JSON's primary metric, compares it against the threshold, and only runs
  the inner `RegisterModel` step if the comparison passes.

Here's the gate logic, simplified:

```python
def build_register_step_with_gate(config, training_step, eval_step,
                                   eval_property_file, primary_metric_name,
                                   gate_op, gate_threshold,
                                   inference_instances=None,
                                   transform_instances=None):
    metrics_uri = eval_step.properties.ProcessingOutputConfig.Outputs["evaluation"].S3Output.S3Uri

    register = RegisterModel(
        name="RegisterModel",
        estimator=training_step.estimator,
        model_data=training_step.properties.ModelArtifacts.S3ModelArtifacts,
        ...,
        approval_status="PendingManualApproval",
        model_metrics=ModelMetrics(model_statistics=MetricsSource(s3_uri=metrics_uri,
                                                                   content_type="application/json")),
    )

    metric_value = JsonGet(step_name=eval_step.name,
                           property_file=eval_property_file,
                           json_path=primary_metric_name)
    cond = ConditionLessThanOrEqualTo(left=metric_value, right=gate_threshold) \
           if gate_op == "<=" else \
           ConditionGreaterThanOrEqualTo(left=metric_value, right=gate_threshold)

    return ConditionStep(name="GateOnMetric",
                          conditions=[cond],
                          if_steps=[register],
                          else_steps=[])
```

Every model has its own (`primary_metric_name`, `gate_op`, `gate_threshold`):

- `perf-predictor`: `metrics.rmse` `<= 8.0` (regression — lower is better)
- `dropout-risk`: `metrics.auc` `>= 0.85` (classification — higher is better)
- `knowledge-tracing`: `metrics.next_q_auc` `>= 0.82`
- `difficulty-classifier`: `metrics.accuracy` `>= 0.70`

A failed gate doesn't crash the pipeline — it just skips registration. The
training and evaluation steps still ran (and their artifacts are in S3 for
you to inspect). You see "Pipeline Succeeded, model NOT registered" in the
SageMaker console.

The actual model definitions are short. `pipeline.py` for the performance
predictor:

```python
def build_pipeline(config):
    sm_session = pipeline_session(config.region)
    params = common_parameters()
    input_data_uri = ParameterString(name="input_data_uri",
                                       default_value=f"s3://{config.bucket}/processed/student_events/")

    validation_step = build_processing_step(
        config=config,
        step_name="DataValidation",
        code_path=str(SHARED / "data_validation.py"),
        ...
    )

    extract_step = build_processing_step(
        config=config,
        step_name="FeatureExtract",
        code_path=str(CODE_DIR / "feature_extract.py"),
        ...
    )
    extract_step.add_depends_on([validation_step])

    image_uri = retrieve(framework="xgboost", region=config.region, version="1.7-1")
    estimator = Estimator(
        image_uri=image_uri,
        role=config.role_arn,
        instance_count=1,
        instance_type=config.instance_type_train,
        output_path=f"s3://{config.bucket}/models/{config.model_name}/{config.environment}/",
        sagemaker_session=sm_session,
        use_spot_instances=config.use_spot,
        max_run=config.max_runtime_sec,
        max_wait=config.max_wait_sec if config.use_spot else None,
    )
    estimator.set_hyperparameters(
        objective="reg:squarederror",
        num_round=200, max_depth=6, eta=0.05,
        subsample=0.85, colsample_bytree=0.8,
        min_child_weight=2, eval_metric="rmse",
    )

    train_step = TrainingStep(
        name="Train", estimator=estimator,
        inputs={
            "train":      TrainingInput(s3_data=extract_step.properties...["train"].S3Output.S3Uri,
                                          content_type="text/csv"),
            "validation": TrainingInput(s3_data=...["validation"].S3Output.S3Uri,
                                          content_type="text/csv"),
        },
    )

    eval_step, eval_pf = build_evaluation_step(config, code_path=str(CODE_DIR / "evaluate.py"),
                                                 training_step=train_step,
                                                 eval_data_input=...["test"].S3Output.S3Uri)

    register_step = build_register_step_with_gate(
        config, training_step=train_step, eval_step=eval_step,
        eval_property_file=eval_pf,
        primary_metric_name="metrics.rmse",
        gate_op="<=",
        gate_threshold=config.metric_gate.get("rmse", 8.0),
    )

    return Pipeline(
        name=config.pipeline_name,
        parameters=list(params.values()) + [input_data_uri],
        steps=[validation_step, extract_step, train_step, eval_step, register_step],
        sagemaker_session=sm_session,
    )
```

Notes:
- **`use_spot_instances=True`** can save 70–90% on training cost. Spot
  instances can be interrupted, so you set `max_wait` (longer than `max_run`)
  to give time for retries.
- **Built-in framework images** (`retrieve(framework="xgboost", ...)`) — AWS
  ships pre-built containers for common frameworks. You don't build a
  Dockerfile for a vanilla XGBoost training run.
- **Pipeline parameters** — these are knobs the runtime can tweak per execution
  (e.g., the auto-retrain Lambda passes `trigger=drift-alarm`). Pipeline
  *definition* is static; pipeline *execution* takes parameters.

## 2.11 The application — `api/recommendation/`

The FastAPI service is the customer-facing surface. It does roughly:

```
GET  /health                      ← liveness/readiness probe
GET  /metrics                     ← Prometheus
GET  /questions/{id}              ← serve a question (public)
GET  /questions                   ← list questions (public, filterable)
POST /assessment/submit           ← grade 10 answers, return next batch (auth)
GET  /recommendation/{student_id} ← fetch latest recommendation (auth)
```

The hot path is `POST /assessment/submit`:

```python
@app.post("/assessment/submit", response_model=AssessmentResult)
async def submit_assessment(submission: AssessmentSubmission,
                             claims: dict = Depends(auth_dependency)) -> AssessmentResult:
    _enforce_student_match(claims, submission.student_id)
    rec = get_recommender()
    store = get_event_store()
    submitted_at = submission.submitted_at or datetime.now(timezone.utc)

    per_question = []
    score = 0
    for ans in submission.answers:
        question = rec.get_question(ans.question_id)
        if question is None:
            raise HTTPException(400, f"unknown question_id: {ans.question_id}")
        is_correct = ans.selected_option == question["correct"]
        if is_correct:
            score += 1
        store.append({...event details...})
        per_question.append({...})

    history = store.get_history(submission.student_id)
    result = rec.recommend(submission.student_id, history, subject=submission.subject)
    LEVEL_PREDICTIONS.labels(level=result.level).inc()

    external = await _fan_out_endpoints(history)

    return _build_response(submission, score, per_question, result, external)
```

Key teaching points:

- **`Depends(auth_dependency)`** — FastAPI's DI. The dependency function
  reads the `Authorization` header, validates the JWT against the cached
  Cognito JWKS, returns the claims dict. If anything's wrong, it raises
  `HTTPException(401)` and the route handler never runs.
- **`_enforce_student_match`** — students may only access their own data.
  Instructors and admins (claims contain `cognito:groups: ["instructor"]`)
  can access anyone's. This is a one-line authz check that prevents the
  worst-class IDOR bug.
- **`asyncio.gather` for endpoint fan-out** — 3 SageMaker endpoints called
  concurrently, total latency = max of the 3, not sum. Without async, this
  would be 200ms (sequential). With async, ~80ms.
- **Circuit breakers** in `services/sagemaker_invoker.py` — after 5 consecutive
  failures, the breaker opens and skips the invoker for 30 seconds. So a
  slow downstream model can't drag the API past its SLO.

The auth code (`services/auth.py`) is worth showing because it's a common
production gotcha:

```python
def verify_token(token: str) -> dict[str, Any]:
    if _is_auth_disabled():
        return {"sub": "local-dev", "cognito:groups": ["beginner"]}

    region = os.environ["MLOPS_COGNITO_REGION"]
    user_pool_id = os.environ["MLOPS_COGNITO_USER_POOL_ID"]
    client_id = os.environ.get("MLOPS_COGNITO_CLIENT_ID")

    from jose import jwt

    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(401, "missing kid")

    key = _JWKS.get(region, user_pool_id, kid)   # cached for 24h
    if key is None:
        _JWKS._refresh(region, user_pool_id)
        key = _JWKS.get(region, user_pool_id, kid)
    if key is None:
        raise HTTPException(401, "unknown signing key")

    try:
        return jwt.decode(token, key, algorithms=["RS256"],
                           audience=client_id,
                           issuer=f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}",
                           options={"verify_aud": client_id is not None})
    except Exception as exc:
        raise HTTPException(401, f"invalid token: {exc}")
```

The JWKS cache is critical: without it, every request would hit Cognito's
`.well-known/jwks.json` endpoint (~200ms). With it, the first request fetches
and caches for 24 hours; the rest are local hash table lookups.

## 2.12 Helm chart — `helm/charts/recommendation-api/`

The Helm chart is what turns the Docker image into running pods. Highlights
from `templates/deployment.yaml`:

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0       # never drop below desired replica count during rollout
  template:
    spec:
      serviceAccountName: {{ include "recommendation-api.serviceAccountName" . }}
      automountServiceAccountToken: true   # IRSA needs this
      terminationGracePeriodSeconds: 45
      containers:
        - name: api
          ports: [{ name: http, containerPort: 8086 }]
          envFrom:
            - configMapRef: { name: ...-config }
            - secretRef:    { name: ...-external }   # External Secrets injects this
          startupProbe:    { httpGet: { path: /health, port: http }, ... }
          livenessProbe:   { httpGet: { path: /health, port: http }, ... }
          readinessProbe:  { httpGet: { path: /health, port: http }, ... }
          resources:       { requests: ..., limits: ... }
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 1000
            capabilities: { drop: [ALL] }
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 10"]   # let in-flight reqs drain
```

The five things that distinguish a "production" chart from a "minimal" one:

1. **Three probes** (startup, liveness, readiness). Startup probe gives the
   container long enough to load the model (~30–60s). Liveness restarts a
   wedged pod. Readiness keeps a slow-starting pod out of the load balancer
   target group until it can serve.
2. **Pod security context locked down** — non-root user, no privilege
   escalation, read-only root filesystem, all Linux capabilities dropped.
   A compromised pod has no kernel surface to attack.
3. **`maxUnavailable: 0`** — during rolling updates, never drop below
   desired replicas. Pair with `maxSurge: 25%` to add new pods first, then
   remove old ones.
4. **`preStop` sleep** — when K8s sends SIGTERM, give the load balancer
   10 seconds to notice the pod is `Terminating` and stop sending new
   requests, *then* shut down gracefully.
5. **`automountServiceAccountToken: true`** — explicit, not implicit.
   Required for IRSA; the AWS SDK reads the projected token from
   `/var/run/secrets/eks.amazonaws.com/serviceaccount/token`.

The `templates/networkpolicy.yaml` is default-deny:

```yaml
policyTypes: [Ingress, Egress]
ingress:
  - from:
      - namespaceSelector:
          matchLabels: { kubernetes.io/metadata.name: ingress-controller }
      - namespaceSelector:
          matchLabels: { kubernetes.io/metadata.name: monitoring }
    ports: [{ protocol: TCP, port: 8086 }]
egress:
  - to: [{ namespaceSelector: {}, podSelector: { matchLabels: { k8s-app: kube-dns } } }]
    ports: [{ protocol: UDP, port: 53 }, { protocol: TCP, port: 53 }]
  - to: [{ ipBlock: { cidr: 0.0.0.0/0, except: [169.254.169.254/32] } }]
    ports: [{ protocol: TCP, port: 443 }]
```

What this does:
- **Ingress**: only pods in `ingress-controller` (the ALB controller) and
  `monitoring` (Prometheus scraper) may reach the API on port 8086.
- **Egress**: DNS (so the AWS SDK can resolve hostnames) and HTTPS (for
  AWS APIs), but NOT to the IMDS endpoint `169.254.169.254`. IMDS is the
  in-instance credential service; blocking it forces the SDK to use IRSA.

## 2.13 CI/CD — `.github/workflows/`

Five workflow files, in two categories:

**Infrastructure**:
- `terraform-plan.yml` — runs on every PR. Matrix over dev/qa/prod. Comments
  the dev plan back to the PR.
- `terraform-apply.yml` — manual dispatch only. Gated by GitHub Environment
  protection rules (required reviewers).

**Application**:
- `api-ci.yml` — test → build → ECR push → Trivy scan → deploy dev (auto,
  on push to dev branch) → promote prod (manual approval, on push to main).
- `ml-pipeline-trigger.yml` — manual dispatch to upsert/start a SageMaker
  Pipeline.
- `drift-lambda-build.yml` — packages and uploads the drift detector Lambda
  zip on every push.

The OIDC pattern in `terraform-plan.yml`:

```yaml
permissions:
  contents: read
  id-token: write       # required for AWS OIDC

steps:
  - uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/mlops-learning-gha-${{ matrix.env }}-tf
      role-session-name: gha-tf-plan-${{ matrix.env }}
      aws-region: ap-south-1
```

There are no static AWS credentials in GitHub Secrets. Instead, GitHub
issues an OIDC token to the runner, AWS validates that token against a
trust policy on the IAM role, and only requests from the *correct repo* on
the *correct branch* may assume the role. Set up once in IAM, never rotate
credentials again.

## 2.14 Local development loop

You should be able to:

1. `python scripts/seed_synthetic_data.py --num-students 200`
2. `python ml/training/train_difficulty_classifier.py`
3. `MLOPS_AUTH_DISABLED=1 uvicorn api.recommendation.main:app --reload`
4. `pytest tests/`

The local trainer (`ml/training/train_difficulty_classifier.py`) is a
single-file convenience that bypasses SageMaker. It reads the JSONL events,
builds features, fits a sklearn `RandomForestClassifier`, evaluates, and
saves `artifacts/model.joblib`. The same code runs inside the SageMaker
Pipeline (we factored out the inner functions). This is how you get a
fast inner loop on a laptop and a controlled outer loop on AWS.

The 15 tests in `tests/` cover:
- Unit tests for feature engineering (no AWS, no model — pure math)
- Unit tests for the recommender (loads a mock model, tests selection logic)
- Integration tests against the FastAPI app via `TestClient` (in-memory)

`make test` runs them all. They should be green before any commit.

---

# Part 3 — Walking the `monitoring-mlops/` project

This project is a sibling of `mlops/` with the same skeleton. I'll focus on
**what's different** — the AIOps-specific layers.

## 3.1 Big-picture differences

| Aspect | `mlops/` | `monitoring-mlops/` |
|---|---|---|
| Data sources (L1) | 1 stream (student events) | 14 sources (logs, metrics, traces) |
| Ingestion (L2) | Kinesis Data Stream | Kinesis Firehose + MSK + Fluent Bit + ADOT |
| Lake (L3) | S3 + Glue | S3 + Glue + OpenSearch (with AD plugin) |
| Features (L4) | per-student aggregates | per-(source, host, window) sliding windows |
| Models (L5) | 4 supervised | 4 unsupervised + streaming statistical |
| API | grades MCQs, returns recs | scores events, returns alerts |
| Auth roles | student / instructor / admin | analyst / responder / admin |
| Threat intel layer | none | GuardDuty + Security Hub + Detective |
| Cold start | none (synthetic data trains immediately) | 7 days for ML to be useful |

## 3.2 Layer 2 — Firehose (`infra /modules/firehose/`)

The Firehose module replaces the single Kinesis stream with **7 per-source
delivery streams**. Each stream:
- Writes Parquet files to a per-source S3 prefix (`raw/source=<src>/year=…/`)
- Has its own scoped IAM role (least privilege per source)
- Uses dynamic partitioning by event timestamp (cheap Athena queries)

```hcl
locals {
  sources = toset(["cloudfront", "alb", "waf", "app", "eks", "nginx", "mysql"])
}

resource "aws_kinesis_firehose_delivery_stream" "stream" {
  for_each    = local.sources
  name        = "${local.prefix}-${each.key}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose[each.key].arn
    bucket_arn = var.raw_bucket_arn
    prefix              = "raw/source=${each.key}/year=!{partitionKeyFromQuery:year}/month=!{partitionKeyFromQuery:month}/day=!{partitionKeyFromQuery:day}/hour=!{partitionKeyFromQuery:hour}/"
    error_output_prefix = "errors/source=${each.key}/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"

    buffering_size     = 64    # MB
    buffering_interval = 300   # seconds (5 min)

    dynamic_partitioning_configuration { enabled = true }

    processing_configuration {
      enabled = true
      processors {
        type = "MetadataExtraction"
        parameters {
          parameter_name  = "MetadataExtractionQuery"
          parameter_value = "{year:.ts|fromdate|strftime(\"%Y\"),month:.ts|fromdate|strftime(\"%m\"),day:.ts|fromdate|strftime(\"%d\"),hour:.ts|fromdate|strftime(\"%H\")}"
        }
        parameters {
          parameter_name  = "JsonParsingEngine"
          parameter_value = "JQ-1.6"
        }
      }
    }
  }
}
```

What this does at runtime:

1. Producer puts a JSON record into the Firehose: `{"ts":"2026-06-19T10:11:12Z","source":"alb",...}`
2. Firehose reads the record, runs the JQ expression to extract `year/month/day/hour`
   from the `ts` field.
3. Buffers up to 64 MB or 5 minutes.
4. Writes a Parquet file to `s3://<bucket>/raw/source=alb/year=2026/month=06/day=19/hour=10/<file>.parquet`.

Athena can now query just `WHERE source='alb' AND year='2026' AND month='06'`
and S3 reads only those partitions — 100x speedup on big tables.

## 3.3 Layer 2 — MSK (`infra /modules/msk/`)

For high-throughput app logs (NGINX, MongoDB, Redis), Firehose is overkill
and Kafka is the right tool. MSK = Managed Kafka.

```hcl
resource "aws_msk_configuration" "main" {
  name              = "${local.cluster_name}-config"
  kafka_versions    = [var.kafka_version]
  server_properties = <<-PROPS
    auto.create.topics.enable=false
    default.replication.factor=3
    min.insync.replicas=2
    num.partitions=6
    log.retention.hours=72
    log.segment.bytes=1073741824
    unclean.leader.election.enable=false
    delete.topic.enable=true
  PROPS
}

resource "aws_msk_cluster" "main" {
  cluster_name           = local.cluster_name
  kafka_version          = var.kafka_version
  number_of_broker_nodes = var.broker_count

  broker_node_group_info {
    instance_type   = var.broker_instance_type
    client_subnets  = var.private_subnet_ids
    security_groups = [aws_security_group.msk.id]
    storage_info {
      ebs_storage_info { volume_size = var.ebs_volume_size_gb }
    }
  }

  encryption_info {
    encryption_at_rest_kms_key_arn = aws_kms_key.msk.arn
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  client_authentication {
    sasl { iam = var.client_authentication_iam }
    tls {}
  }
}
```

The 7 most consequential Kafka settings:

- `auto.create.topics.enable=false` — strict. Every topic must exist
  explicitly. Misconfigured producers can't accidentally create
  `logs.app.typo`.
- `default.replication.factor=3` — every partition has 3 copies across
  brokers. Survives any single broker failure.
- `min.insync.replicas=2` — a producer's `acks=all` waits for at least 2
  replicas to acknowledge. Survives any 1 broker without data loss.
- `unclean.leader.election.enable=false` — when a leader fails, only a
  fully-caught-up follower may take over. Trades availability for durability.
- `client_broker=TLS`, `in_cluster=true` — encryption everywhere.
- `sasl.iam` — clients (the API, Fluent Bit) authenticate using AWS IAM,
  not username/password. IRSA roles map to MSK ACLs.

## 3.4 Layer 3 — OpenSearch (`infra /modules/opensearch/`)

OpenSearch serves three needs in this project:
1. **Log search** for analysts (Kibana-style dashboards)
2. **Anomaly Detection plugin** (RCF on indexed time-series, faster than
   SageMaker for "OpenSearch-shaped" use cases)
3. **A read API for the scoring service** to fetch recent log context

```hcl
resource "aws_opensearch_domain" "main" {
  domain_name    = local.domain_name
  engine_version = var.engine_version

  cluster_config {
    instance_type          = var.instance_type
    instance_count         = var.instance_count
    zone_awareness_enabled = var.instance_count >= 2
    zone_awareness_config {
      availability_zone_count = min(var.instance_count, length(var.private_subnet_ids))
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.ebs_volume_size_gb
    iops        = 3000
    throughput  = 125
  }

  vpc_options {
    subnet_ids         = slice(var.private_subnet_ids, 0, min(var.instance_count, length(var.private_subnet_ids)))
    security_group_ids = [aws_security_group.aos.id]
  }

  encrypt_at_rest      { enabled = true; kms_key_id = aws_kms_key.aos.arn }
  node_to_node_encryption { enabled = true }
  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = true
    master_user_options {
      master_user_name     = var.master_user_name
      master_user_password = random_password.master.result
    }
  }
}
```

Things to know:
- **VPC-only by default.** No public endpoint. Access is via the API pods or
  a bastion.
- **Fine-grained access control** via `internal_user_database`. The master
  user is in Secrets Manager; everyone else uses IAM roles mapped to
  OpenSearch roles (a 2-step authn chain).
- **Anomaly Detection plugin** is enabled by default in OpenSearch ≥ 1.0.
  You create AD detectors via the REST API after the domain is up — Terraform
  doesn't have a resource for it. The PRODUCTION-CHECKLIST documents this.

## 3.5 Layer 5 — managed threat intel (`infra /modules/guardduty/`)

GuardDuty is AWS's managed threat detection service. It analyzes:
- VPC Flow Logs (network anomalies, port scans, exfil patterns)
- CloudTrail management events (compromised IAM, unauthorized API calls)
- DNS query logs (DGA-style domains, known C2)
- S3 data events (mass downloads from unusual sources)
- EKS audit logs (kubectl exec, pod-level escapes)
- Malware scans on EBS volumes

This module enables it with all data sources except EBS malware scans
(expensive):

```hcl
resource "aws_guardduty_detector" "main" {
  enable                       = true
  finding_publishing_frequency = "FIFTEEN_MINUTES"

  datasources {
    s3_logs    { enable = var.enable_s3_protection }
    kubernetes { audit_logs { enable = var.enable_eks_protection } }
    malware_protection {
      scan_ec2_instance_with_findings { ebs_volumes { enable = var.enable_malware_protection } }
    }
  }
}

resource "aws_guardduty_detector_feature" "rds_login" {
  count       = var.enable_rds_protection ? 1 : 0
  detector_id = aws_guardduty_detector.main.id
  name        = "RDS_LOGIN_EVENTS"
  status      = "ENABLED"
}

resource "aws_guardduty_detector_feature" "lambda_network" {
  count       = var.enable_lambda_protection ? 1 : 0
  detector_id = aws_guardduty_detector.main.id
  name        = "LAMBDA_NETWORK_LOGS"
  status      = "ENABLED"
}

resource "aws_guardduty_detector_feature" "eks_runtime" {
  count       = var.enable_eks_protection ? 1 : 0
  detector_id = aws_guardduty_detector.main.id
  name        = "EKS_RUNTIME_MONITORING"
  status      = "ENABLED"
  additional_configuration { name = "EKS_ADDON_MANAGEMENT"; status = "ENABLED" }
}
```

The point: GuardDuty *works from minute one*. You don't have to train it,
or feed it baselines, or build features. It's pre-trained at AWS scale on
threat intel feeds. The AIOps platform layers its custom ML *on top* of
GuardDuty, not instead of it.

## 3.6 Layer 4 — log parsers (`ml/parsers/`)

14 source-specific parsers, all returning the same `CommonEvent` dict:

```python
# ml/parsers/__init__.py
def make_event(*, source, ts, host=None, severity=None, status=None,
                latency_ms=None, bytes_=None, src_ip=None, user=None,
                path=None, user_agent=None, message="", attrs=None):
    return {
        "ts": ts_iso, "ingest_ts": now_iso,
        "source": source, "host": host or "",
        "severity": severity, "status": status,
        "latency_ms": latency_ms, "bytes": bytes_,
        "src_ip": src_ip, "user": user, "path": path,
        "user_agent": user_agent,
        "message": message[:4000],
        "attrs": attrs or {},
    }
```

The schema is the *contract*. Every downstream consumer (feature engineering,
streaming detector, OpenSearch indexer, scoring API) reads only these fields.
If you add a new source, you write `ml/parsers/<source>.py` that emits this
dict and you're done.

Example: ALB parser.

```python
# ml/parsers/alb.py
def parse_alb(line: str) -> dict | None:
    parts = shlex.split(line)
    if len(parts) < 14:
        return None

    type_, ts, elb, client_port, target_port, *_rest = parts
    request_processing_time = float(parts[5]) if parts[5] not in ("-1", "-") else None
    target_processing_time  = float(parts[6]) if parts[6] not in ("-1", "-") else None
    response_processing_time = float(parts[7]) if parts[7] not in ("-1", "-") else None
    elb_status = int(parts[8]) if parts[8] != "-" else None
    sent_bytes = int(parts[11]) if parts[11] != "-" else None
    request_line = parts[12] if len(parts) > 12 else ""
    user_agent = parts[13] if len(parts) > 13 else ""

    method = path = ""
    if request_line:
        try: method, path, _proto = request_line.split(" ", 2)
        except ValueError: method = request_line.split(" ", 1)[0]

    src_ip = client_port.split(":")[0] if client_port else None
    latency_ms = None
    if target_processing_time is not None:
        latency_ms = ((request_processing_time or 0) +
                       target_processing_time +
                       (response_processing_time or 0)) * 1000

    return make_event(source="alb", ts=ts, host=elb,
                       severity="ERROR" if (elb_status or 0) >= 500 else None,
                       status=elb_status,
                       latency_ms=latency_ms,
                       bytes_=sent_bytes,
                       src_ip=src_ip, path=path, user_agent=user_agent,
                       message=f"{method} {path} -> {elb_status}",
                       attrs={"type": type_, "target": target_port})
```

What's happening:
- ALB writes log lines in a documented format (space-separated, quoted strings).
- We parse the fields, defending against `"-"` placeholders and missing fields.
- We compute `latency_ms` from three component times (request + target + response).
- We map ALB-specific fields (status code, src_ip) to the `CommonEvent` shape.
- ALB-specific bits we want to keep (target IP, type) go into `attrs`.

The OTEL trace parser is the most interesting because OTLP is verbose:

```python
# ml/parsers/otel.py
def parse_otel_span(span: dict) -> dict | None:
    if not span:
        return None
    attrs = {a["key"]: a["value"].get("stringValue") or a["value"].get("intValue") or a["value"].get("doubleValue")
             for a in span.get("attributes", [])}
    start_ns = int(span.get("startTimeUnixNano", 0))
    end_ns   = int(span.get("endTimeUnixNano", 0))
    dur_ms   = (end_ns - start_ns) / 1_000_000.0
    status_code = (span.get("status") or {}).get("code")  # 0=Unset, 1=OK, 2=Error
    severity = "ERROR" if status_code == 2 else "INFO"
    ts_iso = datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    return make_event(source="otel-traces", ts=ts_iso,
                       host=attrs.get("host.name") or attrs.get("k8s.pod.name"),
                       severity=severity, latency_ms=dur_ms,
                       message=f"{span.get('name', '?')} ({dur_ms:.1f}ms)",
                       attrs={"trace_id": span.get("traceId"), "span_id": span.get("spanId"),
                              "parent_span_id": span.get("parentSpanId"),
                              "name": span.get("name"),
                              "service.name": attrs.get("service.name"),
                              "http.status_code": attrs.get("http.status_code"),
                              "status_code": status_code})
```

OTLP attributes are typed: `stringValue`, `intValue`, `doubleValue`. We
flatten them by reading whichever key is present.

## 3.7 Layer 4 — security feature engineering (`ml/feature_engineering/security_features.py`)

The features differ from `mlops/`. Where the student MCQ project computes
*per-student aggregates*, the AIOps project computes *per-(source, host,
window) sliding-window statistics*:

```python
LOG_FEATURE_COLUMNS = (
    "request_count", "rate_4xx", "rate_5xx",
    "distinct_ips", "distinct_paths", "auth_failure_rate",
    "p99_latency_ms", "p50_latency_ms", "avg_bytes",
    "entropy_path", "entropy_src_ip", "user_agent_distinct",
)

METRIC_FEATURE_COLUMNS = (
    "value_p50", "value_p95", "value_p99", "value_max", "delta_p50", "slope",
)
```

The `entropy_path` and `entropy_src_ip` features are the cleverest. Shannon
entropy over the path distribution catches scanners (a normal user hits 5–10
paths; a scanner hits 1000+ random paths → high entropy on the
path-distribution). Same for src_ip — a normal API mostly serves a stable
set of clients; a sudden surge of distinct IPs spikes the entropy.

```python
def _entropy(values: Iterable) -> float:
    counts = Counter(values)
    total = sum(counts.values())
    if total <= 1: return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c)
```

The bucketing function turns a stream of events into per-window groups:

```python
def bucket_events_by_window(events, window_seconds=300):
    buckets = defaultdict(list)
    for ev in events:
        ts = _parse_ts(ev["ts"])
        epoch = int(ts.timestamp())
        floor = epoch - (epoch % window_seconds)
        bucket_start = datetime.fromtimestamp(floor, tz=timezone.utc)
        buckets[(ev["source"], ev["host"] or "", bucket_start.isoformat())].append(ev)
    return buckets
```

A 5-minute window → all events at 10:02:34 and 10:04:59 land in the same
`10:00:00` bucket. The detector trains on these buckets, so the temporal
granularity of the model is exactly 5 minutes.

## 3.8 Layer 5 — the streaming statistical detector (`ml/streaming/detector.py`)

This is the **cold-start** detector — works from minute one, no training
required. It implements 5 rules, each as a Python class:

```python
@dataclass
class ZScoreRule(Rule):
    window_size: int = 60
    threshold:   float = 4.0
    _buffers: dict[str, deque] = field(default_factory=dict)

    def update(self, key: str, value: float, ts: float) -> Anomaly | None:
        buf = self._buffers.setdefault(key, deque(maxlen=self.window_size))
        buf.append(value)
        if len(buf) < max(10, self.window_size // 6):
            return None
        mean = sum(buf) / len(buf)
        variance = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        std = math.sqrt(variance)
        if std == 0: return None
        z = (value - mean) / std
        if abs(z) >= self.threshold:
            return Anomaly(detector=self.name, metric_key=key, ts_seen=ts,
                            value=value, baseline=mean, score=abs(z) / self.threshold,
                            explanation=f"z={z:.2f} (mean={mean:.3f}, std={std:.3f})")
        return None
```

Five rules:
- `ZScoreRule` — fixed sliding window. Catches sudden spikes against recent normal.
- `EWMARule` — exponentially weighted moving average. Reacts to gradual shifts.
  We score against the *pre-update* mean so a sudden jump fires immediately
  instead of being absorbed.
- `RateOfChangeRule` — bin-to-bin percentage change. Catches step-function
  changes (a deploy that broke things at 10:00:00 sharp).
- `StaticThresholdRule` — error rate > 5% etc. Hardcoded business rules.
- `DistinctCounterRule` — distinct IPs > 10K = DDoS.

Each rule is independent and stateful per `metric_key`. A `StreamingDetector`
holds them all and routes each sample to all rules:

```python
class StreamingDetector:
    def __init__(self, rules):
        self._rules = list(rules)

    def update(self, key, value, ts=None) -> list[Anomaly]:
        ts = ts if ts is not None else time.time()
        out = []
        for rule in self._rules:
            try:
                a = rule.update(key, value, ts)
            except Exception:
                a = None
            if a is not None:
                out.append(a)
        return out
```

The detector runs in two places:
1. Inside the FastAPI scoring service (per-request scoring).
2. Inside a Lambda triggered by Firehose/Kinesis for asynchronous bulk
   anomaly detection (`ml/streaming/lambda_handler.py`).

## 3.9 Layer 5 — the 4 ML detectors

Each detector follows the same shape as the `mlops/` SageMaker Pipelines.
Differences worth knowing:

**`rcf_metrics`** — Random Cut Forest (built-in SageMaker algorithm). RCF
is interesting because it's *streaming-friendly*: you can update the trees
online with new data without retraining from scratch. Use it for numeric
metric streams (CPU, latency, request rate).

**`iforest_logs`** — Isolation Forest on tabular log features. The shorter
the path to isolate a sample in a random tree, the more anomalous. Cheap,
explainable, no GPU. Use it for the 12-feature LOG vector.

**`lstm_autoencoder_traces`** — train an LSTM to reconstruct OTEL trace span
sequences. Anomaly = high reconstruction error. The model never sees a label;
it just learns the structure of "normal" traces. GPU required because of
sequence length × feature dim × hidden dim.

**`log_embedding_anomaly`** — TF-IDF char-ngrams + Isolation Forest on the
embedded space. A modern alternative is LogBERT (DistilBERT-mini fine-tuned
on log lines), but the TF-IDF version runs without a GPU. Use it for raw
log lines where the LOG feature vector is too coarse.

The data validation step (`ml/pipelines/_shared/data_validation.py`) has a
PII scanner — refuses to run if log lines contain phone numbers or email
addresses (README.md rule #1):

```python
PII_FIELDS = {"name", "first_name", "last_name", "email", "phone", "address", "ssn", "dob"}
PII_VALUE_PATTERNS = [
    re.compile(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b"),  # phone
    re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I),  # email
]

def find_pii(records):
    hits = []
    for i, rec in enumerate(records[:1000]):
        for k, v in rec.items():
            if k.lower() in PII_FIELDS:
                hits.append({"row": i, "field": k, "reason": "field name in PII allowlist"})
            if isinstance(v, str):
                for pat in PII_VALUE_PATTERNS:
                    if pat.search(v):
                        hits.append({"row": i, "field": k, "reason": "value matches PII pattern"})
                        break
    return hits
```

If the validation fails, `sys.exit(1)` — pipeline stops, model never trains
on PII.

## 3.10 The scoring API (`api/scoring/`)

Different shape from the recommendation API:

```
POST /score                      ← score one event with streaming + ML detectors
GET  /alerts                     ← list active + recent alerts
GET  /alerts/{id}                ← fetch one alert
GET  /alerts/{id}/explain        ← contributing features, similar past alerts
POST /feedback                   ← responder labels TP/FP/ignored
GET  /sources                    ← per-source ingest health
GET  /health                     ← liveness/readiness
GET  /metrics                    ← Prometheus
```

The hot path is `POST /score`:

```python
@app.post("/score", response_model=ScoreResponse)
async def score(event: CommonEvent, claims: dict = Depends(auth_dependency)) -> ScoreResponse:
    require_role(claims, "analyst")

    s = _state()
    detector = s["detector"]
    alerts_store = s["alerts"]

    kv = _key_and_value(event)   # ← extracts (metric_key, value) from the event
    if kv is None:
        raise HTTPException(400, "event has no scorable signal")
    key, value = kv

    ts_epoch = parse_event_ts(event.ts)
    streaming_anomalies = detector.update(key, value, ts_epoch)

    # Optional ML fan-out
    external = await _fan_out(event)

    is_anomaly = bool(streaming_anomalies) or any(
        (r or {}).get("is_anomaly") for r in external.values()
    )
    detector_label = (streaming_anomalies[0].detector if streaming_anomalies
                       else next((k for k, r in external.items() if (r or {}).get("is_anomaly")), "none"))
    score_val = max(
        [a.score for a in streaming_anomalies] +
        [float((r or {}).get("score", 0)) for r in external.values()] + [0.0]
    )

    if is_anomaly:
        ALERTS_ANOMALY.labels(detector=detector_label).inc()
        alerts_store.append({
            "detector":   detector_label,
            "metric_key": key,
            "source":     event.source,
            "score":      score_val,
            "value":      value,
            "baseline":   streaming_anomalies[0].baseline if streaming_anomalies else value,
            "explanation": streaming_anomalies[0].explanation if streaming_anomalies else "external detector",
            "ts_seen":    ts_epoch,
            "raw_event":  event.model_dump(),
        })

    return ScoreResponse(score=score_val, is_anomaly=is_anomaly,
                          detector=detector_label, explanation={...},
                          metric_key=key)
```

The control flow:
1. Verify auth + role.
2. Extract `(metric_key, value)` from the event (different per source).
3. Update streaming statistical detector (always works).
4. If ML endpoints are configured, fan out via `asyncio.gather`.
5. If any detector flagged it, persist the alert and increment metrics.
6. Return the score.

The `require_role` helper enforces the role hierarchy:

```python
def require_role(claims: dict, required: str) -> None:
    groups = claims.get("cognito:groups", []) or []
    rank = {"analyst": 1, "responder": 2, "admin": 3}
    have = max((rank.get(g, 0) for g in groups), default=0)
    need = rank.get(required, 0)
    if have < need:
        raise HTTPException(403, f"requires role {required}")
```

`responder` includes `analyst` privileges; `admin` includes both. Cleaner
than rewriting the check at every endpoint.

## 3.11 Pre-trained model import (`scripts/import_pretrained_model.py`)

The bring-your-own-model script handles all 4 detector formats, validates
the artifact loads, packages it correctly, and registers it. Key idea:
**the rest of the platform doesn't care where the model came from** — once
it's in the Model Registry with status `Approved`, CodePipeline deploys it
the same way as a freshly-trained one.

The script supports two paths:
- **Manual approval (default)** — register as `PendingManualApproval`.
  You review in the SageMaker console (or via CLI) before CodePipeline
  picks it up.
- **`--auto-approve`** — register as `Approved` and deploy automatically.
  Convenient for dev. The runbook calls out "don't use this in prod".

The script generates an inference handler script per detector type:

```python
INFERENCE_SCRIPT_SKLEARN = """
def model_fn(model_dir):
    return joblib.load(os.path.join(model_dir, "model.joblib"))

def input_fn(body, content_type):
    rec = json.loads(body)
    if "features" in rec:
        return ("features", np.asarray(rec["features"], dtype=float))
    if "text" in rec:
        return ("text", list(rec["text"]))
    raise ValueError("Expected JSON with 'features' or 'text'")

def predict_fn(input_data, model):
    kind, X = input_data
    anomaly_score = -model.score_samples(X) if hasattr(model, "score_samples") else ...
    is_anomaly = (anomaly_score >= np.percentile(anomaly_score, 99)).tolist()
    return {"score": anomaly_score.tolist(), "is_anomaly": is_anomaly}

def output_fn(prediction, accept):
    return json.dumps(prediction), "application/json"
"""
```

These four handlers (`model_fn`, `input_fn`, `predict_fn`, `output_fn`)
are SageMaker's contract for script-mode inference containers. The script
gets uploaded inside `model.tar.gz` and the container runs it on every
request.

---

# Part 4 — Day-2 operations

## 4.1 The PRODUCTION-CHECKLIST is a hard gate

The master `docs/PRODUCTION-CHECKLIST.md` is not optional. Before any
`terraform apply` to a `prod` workspace, every box must be ticked by a
human reviewer.

The checklist is grouped into 13 sections. The most critical:

- **Authority & access**: account isolation, root MFA, billing alerts in
  us-east-1.
- **Networking & isolation**: 3 AZs, NAT Gateways per AZ in prod, EKS
  endpoint restricted by CIDR.
- **Identity & secrets**: MFA on Cognito, all secrets in Secrets Manager,
  no long-lived AWS keys.
- **Cold-start understanding** (AIOps only): stakeholders briefed that ML
  detectors don't fire until trained.

Sub-checklists per module live under `infra /modules/<name>/PRODUCTION-CHECKLIST.md`.

## 4.2 The runbooks

Each project has 4–5 runbooks under `docs/runbooks/`. Common runbook shape:

1. **Trigger**: which alarm or symptom led you here.
2. **First N minutes**: cheap diagnostic queries.
3. **Mitigations**: ranked from "cheapest, safest" to "blast radius".
4. **Communication**: status page, on-call, postmortem template.

Reading order for `monitoring-mlops/`:
- `model-cold-start.md` — what's running on day 1 vs day 7.
- `bring-your-own-model.md` — fast-track ML detection with a borrowed model.
- `ddos-detected.md`, `brute-force-detected.md` — concrete attack scenarios.
- `anomaly-storm.md` — what to do when 100s of alerts fire at once.
- `false-positive-review.md` — weekly precision tuning loop.

The drift-fired runbook in `mlops/` is the single most-instructive document
in the repo. Read it carefully — it explains why you don't always retrain
on a drift signal (data quality issue → fix the source, don't retrain).

## 4.3 Deploying a pre-trained model

The shortest path is documented in `docs/runbooks/bring-your-own-model.md`,
but the gist:

```bash
# 1. Train your model locally or wherever
joblib.dump(my_iforest, "iforest.joblib")

# 2. Import + register
python scripts/import_pretrained_model.py \
    --detector iforest-logs \
    --artifact ./iforest.joblib \
    --env dev \
    --models-bucket monitoring-mlops-dev-models \
    --role-arn arn:aws:iam::ACCOUNT:role/monitoring-mlops-dev-sagemaker-exec-role

# 3. Approve in SageMaker console (1 click)

# 4. Wait for endpoint InService (~25 min)

# 5. Wire the endpoint name into the API
kubectl -n api set env deployment/anomaly-scoring-api \
    MLOPS_ENDPOINT_IFOREST_LOGS=iforest-logs-dev
kubectl -n api rollout status deployment/anomaly-scoring-api
```

The runbook also describes "advisory mode" — run a borrowed model for 48
hours without paging on its alerts, collect feedback labels, then promote
to paging once precision is acceptable.

## 4.4 The drift retrain loop in detail

Here's exactly what happens when drift fires:

1. **Hourly schedule** — EventBridge rule triggers the drift Lambda every hour.
2. **Drift Lambda** reads:
   - The current feature window from `s3://<features>/perf-predictor/current.parquet`
   - The training-time baseline from `s3://<features>/baselines/perf-predictor/{statistics, constraints}.json`
3. **Compute PSI** per feature using the histograms in the baseline.
4. **Push metrics** to CloudWatch under `mlops-learning/drift/PSI` with
   dimensions (Model, Environment, Feature).
5. **Write report** to `s3://<features>/drift-reports/perf-predictor/<timestamp>.json`.

If PSI > 0.20 for any feature:

6. **CloudWatch alarm** transitions to ALARM state.
7. **EventBridge rule** matches on `CloudWatch Alarm State Change` events
   with `alarmName` matching `mlops-learning-prod/L7/feature-drift-*`.
8. **Retrain Lambda** starts the corresponding SageMaker Pipeline:

```python
def trigger_retrain(event, context):
    alarm_name = event["detail"]["alarmName"]
    model = next((k for k in PIPELINE_MAP if k in alarm_name), None)
    pipeline_name = f"{model}-prod-pipeline"
    sm_client.start_pipeline_execution(
        PipelineName=pipeline_name,
        PipelineExecutionDisplayName=f"auto-retrain-{datetime.utcnow().isoformat()}",
        PipelineParameters=[{"Name": "trigger", "Value": "drift-alarm"}]
    )
```

9. **Pipeline runs** 5 steps: data validation → feature extraction →
   training → evaluation → conditional register.
10. **If the new model passes the metric gate**, it lands in the Model
    Registry as `PendingManualApproval`.
11. **An on-call engineer reviews** the metrics in the registry. If they
    approve:
12. **CodePipeline deploys** the new endpoint config (~25 min).
13. **The API picks up the new endpoint** automatically (it reads the
    endpoint name from an env var that's already set; the new model is
    behind the same name).

End-to-end: drift → retrain → deploy → live takes 4–6 hours, mostly
SageMaker Pipeline run time.

## 4.5 Teardown — the order matters

`scripts/teardown.sh` is your sole correct path for deleting infra. It runs
in this exact order because each step depends on the previous:

```bash
1. SageMaker endpoints     ← highest hourly cost
2. SageMaker async endpoints (handled with real-time)
3. Scale EKS nodes to 0    ← stops new pod scheduling
4. EKS cluster (deferred to terraform destroy)
5. Stop RDS                ← preserves snapshot for restore
6. Kinesis (--full-destroy only)
7. terraform destroy       ← removes everything else
8. Manual checks            ← S3 versioned buckets, CW logs, ECR
```

If you skip step 1 (delete endpoints), `terraform destroy` will fail
because the SageMaker module can't delete a Feature Group while endpoints
reference its features. So you'd have to delete endpoints by hand anyway.
The script saves you from learning that the hard way.

---

# Part 5 — Compare, contrast, and what to learn next

## 5.1 What's identical between the two projects

The 7-layer skeleton is verbatim shared:

- VPC + 3 AZs in `ap-south-1`
- EKS + IRSA pattern
- Cognito + ALB + WAFv2 + CloudTrail + CloudWatch billing alerts
- KMS-encrypted S3 buckets with versioning + bucket key
- Secrets Manager for all secrets
- Helm chart shape (PDB, HPA, NetworkPolicy, ServiceMonitor, IRSA)
- Cluster addons (ALB controller, External Secrets, cert-manager,
  kube-prometheus-stack, ArgoCD)
- GitHub Actions OIDC pattern
- The 5-step SageMaker Pipeline shape (data-val → process → train → eval → gated register)
- Drift Lambda → EventBridge → Retrain pattern
- Master PRODUCTION-CHECKLIST + per-module checklists
- Runbook structure
- `scripts/teardown.sh` order

About 70% of `monitoring-mlops/` was a copy-paste from `mlops/` followed by
content swap.

## 5.2 What's different

The 30% that's different is *the ML payload*:

- Different data sources, different parsers
- Different feature engineering
- Different model classes (supervised vs unsupervised)
- Different APIs (recommend vs score+alert)
- Different runbooks (drift vs ddos/brute-force)

Plus the AIOps-specific layers `monitoring-mlops/` adds:

- Firehose for AWS-managed log sources
- MSK for high-throughput app logs
- OpenSearch for log search + AD plugin
- GuardDuty + Security Hub for managed threat intel
- AMP + AMG for Prometheus + Grafana
- Streaming statistical detector (cold-start)
- Bring-your-own-model script

## 5.3 Why this pattern is reusable

Imagine a third project: **fraud detection on transaction streams**. Most
of the work is already done:

- L1 — transaction stream from your card processor (Kinesis, you already know how)
- L2 — Firehose → S3 raw (same module as monitoring-mlops)
- L3 — same S3+Glue+OpenSearch
- L4 — write a parser for transaction format → CommonEvent (or a custom
  per-transaction feature builder)
- L5 — add an `xgboost_fraud` pipeline (looks like `iforest_logs` shape)
- L6 — same Model Registry + CodePipeline
- L7 — same drift Lambda, same alarms

You'd write maybe 1500 new lines: parser + features + 1 detector pipeline +
schema + a few Cognito groups for fraud analysts. Everything else is reused.

This is the dividend of getting the MLOps shell right once.

## 5.4 What to learn next

Concrete suggestions, in order:

### Read deeper

- **Kleppmann, *Designing Data-Intensive Applications*** — chapter 11
  (Stream Processing) is the canon for L2.
- **Google's *Site Reliability Engineering*** — the "Monitoring Distributed
  Systems" chapter and the multi-window multi-burn-rate alerting paper for L7.
- **AWS Well-Architected ML Lens** — the official framework that this repo
  loosely follows.
- **Huyen, *Designing Machine Learning Systems*** — best single-book overview
  of the MLOps lifecycle.

### Extend the projects

These are exercises that deepen understanding:

1. **Add SHAP/LIME explanations** to the dropout-risk endpoint. Modify
   `predict_fn` to return per-feature contributions; surface them in the
   API and dashboard.
2. **Add a multi-armed bandit** for question selection in `mlops/`. Replace
   the static recommender with Thompson sampling; track regret over time.
3. **Add a Ray RLlib agent** for adaptive question selection. Skipped in the
   first build; README.md documents the design.
4. **Wire an LLM tutor** (the LLMOps layer). Use Bedrock + a RAG pipeline
   over a question-bank vector DB.
5. **Add an "Explainable AIOps"** stage to the scoring API. Take the
   Isolation Forest's path-length per feature, return top-3 contributors.

### Operate the system

The deepest learning comes from running the system:

1. Deploy `mlops/dev` end-to-end. Watch the cost dashboard daily.
2. Run a drift injection (`scripts/inject_drift.py`) and watch the retrain
   pipeline fire.
3. Inject an attack into `monitoring-mlops/` (`scripts/inject_attack.py`)
   and confirm the streaming detector + GuardDuty both alert.
4. Bring your own pre-trained model (`scripts/import_pretrained_model.py`)
   and walk it through "advisory mode" → "paging mode".

### What's missing from these scaffolds

Don't read this guide as "everything you need to operate at scale". Things
the projects deliberately leave out (because they're large undertakings):

- **Multi-region DR** — these are single-region. Multi-region adds ~30%
  cost and significant complexity.
- **LLMOps** — Bedrock, RAG, hallucination detection. Out of scope here.
- **Federated learning** — for cross-customer training without raw data sharing.
- **A/B testing infrastructure** — the chart has rollout knobs but no
  weighted traffic routing for shadow/canary.
- **Cost attribution per team** — tags are in place; the actual reports are not.
- **Data lineage** — what feature came from what training job from what data
  partition? Use OpenLineage or Marquez to layer this on top.
- **Model interpretability + bias auditing** — beyond SHAP; serious bias
  audits (e.g. with `aif360`) take real domain knowledge.

## 5.5 Closing thought

Read the source. The walkthroughs in this guide are sketches; the source
files have the full story, including the comments that explain *why each
default*. When something doesn't make sense, open the file, read the
comment block at the top, then read the function. Most decisions are
documented within ~50 lines of where they're enforced.

Good luck. Build something with this.

---

*Last updated: 2026-06-19. If you're reading this much later, AWS APIs may
have moved on; check `terraform plan` output before assuming any specific
hcl block still validates.*

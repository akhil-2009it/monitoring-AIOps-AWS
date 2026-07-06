# CI/CD (CodePipeline + CodeBuild) — Production Checklist

## What this module creates
- Per-model CodePipeline (`{model}-promotion` × 3): Source → Train → Approve → Deploy
- CodeBuild projects: `{model}-train` (kicks off SageMaker Pipeline), `{model}-deploy` (deploys approved model package)
- Source: S3-trigger files at `s3://<artifacts>/triggers/{model}-trigger.json`
- Manual approval gate notifies SNS topic `{prefix}-mlops-alerts`

## Pre-apply gates
- [ ] **CodePipeline IAM** has `sagemaker:*` blanket permission. Scope to: `StartPipelineExecution`, `DescribePipelineExecution`, `Update/CreateEndpointConfig`, `UpdateEndpoint`, `Describe/CreateModel`, `ListModelPackages`, `UpdateModelPackage`. Drop the rest.
- [ ] **CodeBuild image**: `aws/codebuild/standard:7.0`. Newer (`8.0`, `9.0`) available — verify Python 3.11 still supported.
- [ ] **Manual Approve** uses SNS topic from `monitoring` module. Confirm `arn:aws:sns:<region>:<account-id>:<prefix>-mlops-alerts` exists before first run, or pipeline halts at this stage.
- [ ] **Source = S3 trigger** is fine for the "drift fired" auto-retrain path. For a Git-driven pipeline, replace Source with CodeStar Connection / GitHub Actions integration.
- [ ] **Privileged mode = true** on `model_train` — required for Docker-in-Docker. Disable on the `deploy` project (it doesn't need it).
- [ ] **No git source** — model code lives somewhere; document where (likely the `ml/pipelines/` directory pushed to S3 by GitHub Actions).
- [ ] **Approval notification customisation**: the Approve stage sends only the model name. Add metric URLs (CloudWatch dashboard) to `CustomData` for richer reviewer context.
- [ ] **Build_timeout = 120 min on train** — fine for XGBoost, too short for DKT (LSTM) on big data. Per-model override needed.
- [ ] **Pipeline state notifications**: add `aws_codestarnotifications_notification_rule` to fan failures into the SNS topic.

## Cost
- CodePipeline: $1/pipeline/month (active) + $0/run
- CodeBuild: $0.005/min for `BUILD_GENERAL1_SMALL`. Avg train trigger: ~5 min wall = $0.025
- Storage: pipeline artifacts bucket — versioned. Add lifecycle to expire old artifacts after 30d.

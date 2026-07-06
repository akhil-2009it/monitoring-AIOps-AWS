locals {
  prefix = "${var.project}-${var.environment}"

  # One CodePipeline per model
  models = ["perf-predictor", "knowledge-tracing", "dropout-risk"]
}

# ─── S3 Bucket for CodePipeline artifacts ────────────────────────────────────
resource "aws_s3_bucket" "pipeline_artifacts" {
  bucket        = "${local.prefix}-cicd-artifacts"
  force_destroy = true
  tags          = merge(var.tags, { Name = "${local.prefix}-cicd-artifacts" })
}

resource "aws_s3_bucket_versioning" "pipeline_artifacts" {
  bucket = aws_s3_bucket.pipeline_artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "pipeline_artifacts" {
  bucket                  = aws_s3_bucket.pipeline_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─── CodeBuild IAM Role ───────────────────────────────────────────────────────
resource "aws_iam_role" "codebuild" {
  name = "${local.prefix}-codebuild-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "codebuild" {
  name = "${local.prefix}-codebuild-policy"
  role = aws_iam_role.codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/codebuild/*"
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.pipeline_artifacts.arn,
          "${aws_s3_bucket.pipeline_artifacts.arn}/*",
          "arn:aws:s3:::${var.models_bucket}",
          "arn:aws:s3:::${var.models_bucket}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sagemaker:CreateTrainingJob",
          "sagemaker:DescribeTrainingJob",
          "sagemaker:StartPipelineExecution",
          "sagemaker:DescribePipelineExecution",
          "sagemaker:ListPipelineExecutionSteps",
          "sagemaker:UpdateEndpoint",
          "sagemaker:CreateEndpointConfig",
          "sagemaker:DescribeEndpoint",
          "sagemaker:CreateModel",
          "sagemaker:UpdateModelPackage",
          "sagemaker:DescribeModelPackage",
          "sagemaker:ListModelPackages"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = var.sagemaker_exec_role_arn
      },
      {
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:${var.project}/*"
      }
    ]
  })
}

# ─── CodePipeline IAM Role ────────────────────────────────────────────────────
resource "aws_iam_role" "codepipeline" {
  name = "${local.prefix}-codepipeline-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codepipeline.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "codepipeline" {
  name = "${local.prefix}-codepipeline-policy"
  role = aws_iam_role.codepipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.pipeline_artifacts.arn,
          "${aws_s3_bucket.pipeline_artifacts.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:*"]
        Resource = "*"
      }
    ]
  })
}

# ─── CodeBuild Projects ───────────────────────────────────────────────────────
# 1. Model Training (runs SageMaker Pipeline)
resource "aws_codebuild_project" "model_train" {
  for_each = toset(local.models)

  name          = "${local.prefix}-${each.key}-train"
  description   = "Runs SageMaker training pipeline for ${each.key}"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 120 # 2 hours max

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/standard:7.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true

    environment_variable {
      name  = "MODEL_NAME"
      value = each.key
    }
    environment_variable {
      name  = "ENVIRONMENT"
      value = var.environment
    }
    environment_variable {
      name  = "SAGEMAKER_ROLE_ARN"
      value = var.sagemaker_exec_role_arn
    }
    environment_variable {
      name  = "MODELS_BUCKET"
      value = var.models_bucket
    }
    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = <<-BUILDSPEC
      version: 0.2
      phases:
        install:
          runtime-versions:
            python: 3.11
          commands:
            - pip install boto3 sagemaker --break-system-packages
        build:
          commands:
            - echo "Starting SageMaker Pipeline for $MODEL_NAME in $ENVIRONMENT"
            - |
              python - <<'EOF'
              import boto3, time, sys, os
              sm = boto3.client('sagemaker')
              model = os.environ['MODEL_NAME'].replace('-', '_')
              pipeline = f"{os.environ['MODEL_NAME']}-{os.environ['ENVIRONMENT']}-pipeline"
              resp = sm.start_pipeline_execution(
                  PipelineName=pipeline,
                  PipelineExecutionDisplayName=f"codepipeline-{int(time.time())}",
                  PipelineParameters=[{"Name": "trigger", "Value": "codepipeline"}]
              )
              arn = resp['PipelineExecutionArn']
              print(f"Pipeline execution started: {arn}")
              # Poll until done
              for _ in range(120):
                  status = sm.describe_pipeline_execution(PipelineExecutionArn=arn)['PipelineExecutionStatus']
                  print(f"Status: {status}")
                  if status in ['Succeeded', 'Failed', 'Stopped']:
                      break
                  time.sleep(60)
              if status != 'Succeeded':
                  sys.exit(1)
              EOF
      artifacts:
        files:
          - "**/*"
      BUILDSPEC
  }

  logs_config {
    cloudwatch_logs {
      group_name = "/aws/codebuild/${local.prefix}-${each.key}-train"
      status     = "ENABLED"
    }
  }

  tags = var.tags
}

# 2. Model Approval & Deployment
resource "aws_codebuild_project" "model_deploy" {
  for_each = toset(local.models)

  name          = "${local.prefix}-${each.key}-deploy"
  description   = "Approves and deploys latest ${each.key} model to SageMaker endpoint"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 30

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "MODEL_NAME"
      value = each.key
    }
    environment_variable {
      name  = "ENVIRONMENT"
      value = var.environment
    }
    environment_variable {
      name  = "SAGEMAKER_ROLE_ARN"
      value = var.sagemaker_exec_role_arn
    }
    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = <<-BUILDSPEC
      version: 0.2
      phases:
        install:
          runtime-versions:
            python: 3.11
          commands:
            - pip install boto3 sagemaker --break-system-packages
        build:
          commands:
            - echo "Deploying $MODEL_NAME to $ENVIRONMENT"
            - |
              python - <<'EOF'
              import boto3, os, time

              sm = boto3.client('sagemaker')
              model_name = os.environ['MODEL_NAME']
              env = os.environ['ENVIRONMENT']
              endpoint_name = f"{model_name}-{env}"

              # Find latest Approved model package
              group_map = {
                  'perf-predictor':    'PerformancePredictorModelGroup',
                  'knowledge-tracing': 'KnowledgeTracingModelGroup',
                  'dropout-risk':      'DropoutRiskModelGroup',
              }
              group = group_map[model_name]

              pkgs = sm.list_model_packages(
                  ModelPackageGroupName=group,
                  ModelApprovalStatus='Approved',
                  SortBy='CreationTime',
                  SortOrder='Descending',
                  MaxResults=1
              )['ModelPackageSummaryList']

              if not pkgs:
                  raise Exception(f"No approved model in {group}")

              model_package_arn = pkgs[0]['ModelPackageArn']
              print(f"Deploying {model_package_arn}")

              # Instance types per model spec in CLAUDE.md
              instance_map = {
                  'perf-predictor':    'ml.t2.medium',    # $0.065/hr
                  'knowledge-tracing': 'ml.c5.large',     # $0.17/hr
                  'dropout-risk':      'ml.t2.medium',    # $0.065/hr
              }

              config_name = f"{endpoint_name}-{int(time.time())}"
              sm.create_endpoint_config(
                  EndpointConfigName=config_name,
                  ProductionVariants=[{
                      'VariantName': 'AllTraffic',
                      'ModelName': config_name,
                      'InitialInstanceCount': 1,
                      'InstanceType': instance_map[model_name],
                      'InitialVariantWeight': 1.0,
                  }],
              )

              try:
                  sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)
              except sm.exceptions.ValidationException:
                  sm.update_endpoint(EndpointName=endpoint_name, EndpointConfigName=config_name)

              # Wait for InService
              for _ in range(30):
                  status = sm.describe_endpoint(EndpointName=endpoint_name)['EndpointStatus']
                  print(f"Endpoint status: {status}")
                  if status == 'InService':
                      break
                  if status in ['Failed', 'RollingBack']:
                      raise Exception(f"Endpoint deployment failed: {status}")
                  time.sleep(60)
              print(f"Endpoint {endpoint_name} is InService")
              EOF
      BUILDSPEC
  }

  logs_config {
    cloudwatch_logs {
      group_name = "/aws/codebuild/${local.prefix}-${each.key}-deploy"
      status     = "ENABLED"
    }
  }

  tags = var.tags
}

# ─── CodePipeline — Model Promotion Pipeline ──────────────────────────────────
resource "aws_codepipeline" "model_promotion" {
  for_each = toset(local.models)

  name     = "${local.prefix}-${each.key}-promotion"
  role_arn = aws_iam_role.codepipeline.arn

  artifact_store {
    location = aws_s3_bucket.pipeline_artifacts.bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "ModelRegistryApproval"
      category         = "Source"
      owner            = "AWS"
      provider         = "S3"
      version          = "1"
      output_artifacts = ["SourceOutput"]

      configuration = {
        S3Bucket             = aws_s3_bucket.pipeline_artifacts.bucket
        S3ObjectKey          = "triggers/${each.key}-trigger.json"
        PollForSourceChanges = "true"
      }
    }
  }

  stage {
    name = "Train"
    action {
      name             = "RunSageMakerPipeline"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["SourceOutput"]
      output_artifacts = ["TrainOutput"]

      configuration = {
        ProjectName = aws_codebuild_project.model_train[each.key].name
      }
    }
  }

  stage {
    name = "Approve"
    action {
      name     = "ManualApproval"
      category = "Approval"
      owner    = "AWS"
      provider = "Manual"
      version  = "1"

      configuration = {
        NotificationArn = "arn:aws:sns:${var.aws_region}:${var.account_id}:${local.prefix}-mlops-alerts"
        CustomData      = "Review model metrics in SageMaker Model Registry before approving ${each.key} deployment to ${var.environment}."
      }
    }
  }

  stage {
    name = "Deploy"
    action {
      name            = "DeployEndpoint"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["TrainOutput"]

      configuration = {
        ProjectName = aws_codebuild_project.model_deploy[each.key].name
      }
    }
  }

  tags = var.tags
}

# ─── CloudWatch Log Groups for CodeBuild ─────────────────────────────────────
resource "aws_cloudwatch_log_group" "codebuild_train" {
  for_each          = toset(local.models)
  name              = "/aws/codebuild/${local.prefix}-${each.key}-train"
  retention_in_days = 30
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "codebuild_deploy" {
  for_each          = toset(local.models)
  name              = "/aws/codebuild/${local.prefix}-${each.key}-deploy"
  retention_in_days = 30
  tags              = var.tags
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

# Billing metrics + AWS Budgets only emit/are queryable from us-east-1.
provider "aws" {
  alias  = "useast1"
  region = "us-east-1"

  default_tags {
    tags = local.common_tags
  }
}

# ─── Data ─────────────────────────────────────────────────────────────────────
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }

# ─── Locals ───────────────────────────────────────────────────────────────────
locals {
  account_id = data.aws_caller_identity.current.account_id
  azs        = slice(data.aws_availability_zones.available.names, 0, 3)

  common_tags = {
    Project     = var.project
    Owner       = var.owner
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "learning"
  }

  name_prefix = "${var.project}-${var.environment}"
}

# ─── VPC ──────────────────────────────────────────────────────────────────────
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.4"

  name = "${local.name_prefix}-vpc"
  cidr = var.vpc_cidr

  azs             = local.azs
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway   = true
  single_nat_gateway   = var.environment == "prod" ? false : true
  enable_dns_hostnames = true
  enable_dns_support   = true

  # EKS requires these subnet tags for load balancer auto-discovery
  private_subnet_tags = {
    "kubernetes.io/cluster/${local.name_prefix}" = "shared"
    "kubernetes.io/role/internal-elb"            = "1"
  }
  public_subnet_tags = {
    "kubernetes.io/cluster/${local.name_prefix}" = "shared"
    "kubernetes.io/role/elb"                     = "1"
  }

  tags = merge(local.common_tags, { Layer = "L1-network" })
}

# ─── L3: Data Lake ────────────────────────────────────────────────────────────
module "datalake" {
  source = "./modules/datalake"

  project     = var.project
  environment = var.environment
  account_id  = local.account_id
  tags        = merge(local.common_tags, { Layer = "L3-datalake" })
}

# ─── L2: Streaming ────────────────────────────────────────────────────────────
module "streaming" {
  source = "./modules/streaming"

  project                 = var.project
  environment             = var.environment
  kinesis_shard_count     = var.kinesis_shard_count
  kinesis_retention_hours = var.kinesis_retention_hours
  raw_bucket_name         = module.datalake.raw_bucket_name
  sagemaker_exec_role_arn = module.sagemaker.sagemaker_exec_role_arn
  tags                    = merge(local.common_tags, { Layer = "L2-streaming" })

  depends_on = [module.datalake]
}

# ─── L4–L6: SageMaker ────────────────────────────────────────────────────────
module "sagemaker" {
  source = "./modules/sagemaker"

  project                 = var.project
  environment             = var.environment
  aws_region              = var.aws_region
  account_id              = local.account_id
  sagemaker_instance_type = var.sagemaker_instance_type
  feature_store_bucket    = module.datalake.features_bucket_name
  models_bucket           = module.datalake.models_bucket_name
  tags                    = merge(local.common_tags, { Layer = "L4-sagemaker" })

  depends_on = [module.datalake]
}

# ─── L6: EKS (RL Agent + Recommendation API) ─────────────────────────────────
module "eks" {
  source = "./modules/eks"

  project                 = var.project
  environment             = var.environment
  cluster_version         = var.eks_cluster_version
  node_instance_types     = var.eks_node_instance_types
  node_min_size           = var.eks_node_min_size
  node_max_size           = var.eks_node_max_size
  node_desired_size       = var.eks_node_desired_size
  vpc_id                  = module.vpc.vpc_id
  private_subnet_ids      = module.vpc.private_subnets
  sagemaker_exec_role_arn = module.sagemaker.sagemaker_exec_role_arn
  tags                    = merge(local.common_tags, { Layer = "L6-eks" })

  depends_on = [module.vpc]
}

# ─── L1: Database (Student PII) ──────────────────────────────────────────────
module "database" {
  source = "./modules/database"

  project            = var.project
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnets
  rds_instance_class = var.rds_instance_class
  allocated_storage  = var.rds_allocated_storage
  db_name            = var.rds_db_name
  tags               = merge(local.common_tags, { Layer = "L1-database" })

  depends_on = [module.vpc]
}

# ─── L7: Monitoring & Alerting ───────────────────────────────────────────────
module "monitoring" {
  source = "./modules/monitoring"

  project                        = var.project
  environment                    = var.environment
  aws_region                     = var.aws_region
  account_id                     = local.account_id
  billing_alert_email            = var.billing_alert_email
  billing_threshold_warning_usd  = var.billing_threshold_warning_usd
  billing_threshold_critical_usd = var.billing_threshold_critical_usd
  kinesis_stream_name            = module.streaming.kinesis_stream_name
  sagemaker_exec_role_arn        = module.sagemaker.sagemaker_exec_role_arn
  features_bucket_for_drift      = module.datalake.features_bucket_name
  tags                           = merge(local.common_tags, { Layer = "L7-monitoring" })

  depends_on = [module.streaming, module.sagemaker]
}

# ─── L2 ingestion: Firehose for AWS-native log sources ──────────────────────
module "firehose" {
  source = "./modules/firehose"

  project         = var.project
  environment     = var.environment
  raw_bucket_arn  = module.datalake.raw_bucket_arn
  raw_bucket_name = module.datalake.raw_bucket_name
  kms_key_arn     = module.datalake.datalake_kms_key_arn
  tags            = merge(local.common_tags, { Layer = "L2-ingest-firehose" })

  depends_on = [module.datalake]
}

# ─── L2 ingestion: MSK for high-throughput app logs ─────────────────────────
module "msk" {
  source = "./modules/msk"

  project              = var.project
  environment          = var.environment
  vpc_id               = module.vpc.vpc_id
  private_subnet_ids   = module.vpc.private_subnets
  broker_count         = var.msk_broker_count
  broker_instance_type = var.msk_broker_instance_type
  tags                 = merge(local.common_tags, { Layer = "L2-ingest-msk" })

  depends_on = [module.vpc]
}

# ─── L3 OpenSearch for AD plugin + log search ───────────────────────────────
module "opensearch" {
  source = "./modules/opensearch"

  project            = var.project
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnets
  instance_type      = var.opensearch_instance_type
  instance_count     = var.opensearch_instance_count
  tags               = merge(local.common_tags, { Layer = "L3-search" })

  depends_on = [module.vpc]
}

# ─── L5 GuardDuty + Security Hub ────────────────────────────────────────────
module "guardduty" {
  source = "./modules/guardduty"

  project                    = var.project
  environment                = var.environment
  enable_eks_protection      = true
  enable_s3_protection       = true
  enable_rds_protection      = true
  enable_lambda_protection   = true
  enable_malware_protection  = false
  findings_export_bucket_arn = module.datalake.security_lake_bucket_arn
  tags                       = merge(local.common_tags, { Layer = "L5-threat-intel" })

  depends_on = [module.datalake]
}

module "securityhub" {
  source      = "./modules/securityhub"
  project     = var.project
  environment = var.environment
  tags        = merge(local.common_tags, { Layer = "L5-findings-aggregation" })
}

# ─── Managed Prometheus + Grafana ───────────────────────────────────────────
module "amp" {
  source = "./modules/amp"

  project     = var.project
  environment = var.environment
  remote_write_role_principals = [
    "system:serviceaccount:monitoring:adot-collector",
  ]
  eks_oidc_provider_arn = module.eks.oidc_provider_arn
  eks_oidc_provider_url = module.eks.oidc_provider_url
  tags                  = merge(local.common_tags, { Layer = "L7-metrics" })
}

module "amg" {
  source = "./modules/amg"

  project           = var.project
  environment       = var.environment
  amp_workspace_arn = module.amp.workspace_arn
  tags              = merge(local.common_tags, { Layer = "L7-grafana" })
}

# ─── CloudTrail (account-wide audit log) ────────────────────────────────────
module "cloudtrail" {
  source = "./modules/cloudtrail"

  project             = var.project
  environment         = var.environment
  account_id          = local.account_id
  include_data_events = var.cloudtrail_data_events
  tags                = merge(local.common_tags, { Layer = "L7-audit" })
}

# ─── Billing budget + alarms (us-east-1) ─────────────────────────────────────
module "billing" {
  source = "./modules/billing"

  providers = {
    aws.useast1 = aws.useast1
  }

  project            = var.project
  environment        = var.environment
  alert_email        = var.billing_alert_email
  monthly_budget_usd = var.monthly_budget_usd
  tags               = merge(local.common_tags, { Layer = "L7-billing" })
}

# ─── Cognito (student auth) ──────────────────────────────────────────────────
module "cognito" {
  source = "./modules/cognito"

  project           = var.project
  environment       = var.environment
  callback_urls     = var.cognito_callback_urls
  logout_urls       = var.cognito_logout_urls
  mfa_configuration = var.cognito_mfa_configuration
  tags              = merge(local.common_tags, { Layer = "APP-auth" })
}

# ─── WAFv2 (regional, for the API ALB) ───────────────────────────────────────
module "waf" {
  source = "./modules/waf"

  project               = var.project
  environment           = var.environment
  rate_limit_per_5min   = var.waf_rate_limit_per_5min
  blocked_country_codes = var.waf_blocked_country_codes
  tags                  = merge(local.common_tags, { Layer = "APP-waf" })
}

# ─── ALB (front door for the EKS-hosted API) ─────────────────────────────────
# Optional: only created when api_hostname + acm_certificate_arn are set.
module "alb" {
  count  = var.api_hostname != "" && var.acm_certificate_arn != "" ? 1 : 0
  source = "./modules/alb"

  project                     = var.project
  environment                 = var.environment
  vpc_id                      = module.vpc.vpc_id
  public_subnet_ids           = module.vpc.public_subnets
  acm_certificate_arn         = var.acm_certificate_arn
  api_hostname                = var.api_hostname
  waf_web_acl_arn             = module.waf.web_acl_arn
  cognito_user_pool_arn       = module.cognito.user_pool_arn
  cognito_user_pool_client_id = module.cognito.client_id
  cognito_user_pool_domain    = module.cognito.domain
  access_logs_bucket          = var.alb_access_logs_bucket
  tags                        = merge(local.common_tags, { Layer = "APP-ingress" })

  depends_on = [module.vpc, module.cognito, module.waf]
}

# Route53 alias for the ALB (optional)
resource "aws_route53_record" "api" {
  count = var.api_hostname != "" && var.route53_zone_id != "" && length(module.alb) > 0 ? 1 : 0

  zone_id = var.route53_zone_id
  name    = var.api_hostname
  type    = "A"

  alias {
    name                   = module.alb[0].alb_dns_name
    zone_id                = module.alb[0].alb_zone_id
    evaluate_target_health = true
  }
}

# ─── CI/CD (Model Promotion Pipeline) ────────────────────────────────────────
module "cicd" {
  source = "./modules/cicd"

  project                 = var.project
  environment             = var.environment
  account_id              = local.account_id
  aws_region              = var.aws_region
  models_bucket           = module.datalake.models_bucket_name
  sagemaker_exec_role_arn = module.sagemaker.sagemaker_exec_role_arn
  eks_cluster_name        = module.eks.cluster_name
  tags                    = merge(local.common_tags, { Layer = "L6-cicd" })

  depends_on = [module.sagemaker, module.eks]
}

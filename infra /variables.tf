variable "environment" {
  description = "Deployment environment: dev | qa | prod"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "qa", "prod"], var.environment)
    error_message = "environment must be one of: dev, qa, prod"
  }
}

variable "aws_region" {
  description = "Primary AWS region"
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Project name used in all resource naming and tagging"
  type        = string
  default     = "mlops-learning"
}

variable "owner" {
  description = "Project owner, used in tags"
  type        = string
  default     = "owner"
}

# ─── VPC ──────────────────────────────────────────────────────────────────────
variable "vpc_cidr" {
  description = "CIDR block for the project VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (EKS nodes, RDS)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (NAT GW, ALB)"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
}

# ─── Kinesis ──────────────────────────────────────────────────────────────────
variable "kinesis_shard_count" {
  description = "Number of shards for the student events Kinesis stream"
  type        = number
  default     = 2
}

variable "kinesis_retention_hours" {
  description = "Kinesis stream retention in hours (24–8760)"
  type        = number
  default     = 48
}

# ─── SageMaker ────────────────────────────────────────────────────────────────
variable "sagemaker_instance_type" {
  description = "Default inference instance type — keep cost low (ml.t2.medium ~$0.065/hr)"
  type        = string
  default     = "ml.t2.medium"
}

# ─── EKS ──────────────────────────────────────────────────────────────────────
variable "eks_cluster_version" {
  description = "Kubernetes version for the EKS cluster"
  type        = string
  default     = "1.30"
}

variable "eks_node_instance_types" {
  description = "EC2 instance types for EKS worker nodes"
  type        = list(string)
  default     = ["m5.large"]
}

variable "eks_node_min_size" {
  type    = number
  default = 2
}

variable "eks_node_max_size" {
  type    = number
  default = 6
}

variable "eks_node_desired_size" {
  type    = number
  default = 2
}

# ─── RDS ──────────────────────────────────────────────────────────────────────
variable "rds_instance_class" {
  description = "RDS instance class — db.t3.micro ~$0.017/hr"
  type        = string
  default     = "db.t3.micro"
}

variable "rds_allocated_storage" {
  description = "RDS storage in GB"
  type        = number
  default     = 20
}

variable "rds_db_name" {
  description = "Initial database name"
  type        = string
  default     = "mlops_students"
}

# ─── Billing alerts ───────────────────────────────────────────────────────────
variable "billing_alert_email" {
  description = "Email for billing and ops alerts (CloudWatch SNS)"
  type        = string
  default     = "CHANGE_ME@example.com"
}

variable "billing_threshold_warning_usd" {
  description = "First billing alarm threshold in USD"
  type        = number
  default     = 50
}

variable "billing_threshold_critical_usd" {
  description = "Second billing alarm threshold in USD"
  type        = number
  default     = 100
}

variable "monthly_budget_usd" {
  description = "Hard monthly budget. Triggers progressively at 50/80/100/120 percent."
  type        = number
  default     = 200
}

# ─── ALB / DNS / TLS ──────────────────────────────────────────────────────────
variable "api_hostname" {
  description = "Public hostname for the Recommendation API. Leave empty to skip ALB+DNS+ACM provisioning."
  type        = string
  default     = ""
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN (in same region as ALB) covering `api_hostname`. Required for HTTPS."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID for `api_hostname`. Empty = skip DNS record creation."
  type        = string
  default     = ""
}

variable "alb_access_logs_bucket" {
  description = "Existing S3 bucket for ALB access logs. Must have ELB log-write policy."
  type        = string
  default     = ""
}

# ─── Cognito ─────────────────────────────────────────────────────────────────
variable "cognito_callback_urls" {
  description = "OAuth callback URLs for the SPA"
  type        = list(string)
  default     = ["https://localhost:3000/auth/callback"]
}

variable "cognito_logout_urls" {
  type    = list(string)
  default = ["https://localhost:3000/auth/logout"]
}

variable "cognito_mfa_configuration" {
  description = "OFF | ON | OPTIONAL. Use ON in prod."
  type        = string
  default     = "OPTIONAL"
}

# ─── WAF ─────────────────────────────────────────────────────────────────────
variable "waf_rate_limit_per_5min" {
  type    = number
  default = 2000
}

variable "waf_blocked_country_codes" {
  type    = list(string)
  default = []
}

# ─── CloudTrail ──────────────────────────────────────────────────────────────
variable "cloudtrail_data_events" {
  description = "Enable CloudTrail S3/Lambda data events. Expensive on hot buckets."
  type        = bool
  default     = false
}

# ─── MSK ─────────────────────────────────────────────────────────────────────
variable "msk_broker_count" {
  type    = number
  default = 3
}

variable "msk_broker_instance_type" {
  description = "kafka.t3.small in dev (~$33/broker/mo); kafka.m5.large in prod (~$165/broker/mo)"
  type        = string
  default     = "kafka.t3.small"
}

# ─── OpenSearch ──────────────────────────────────────────────────────────────
variable "opensearch_instance_type" {
  description = "t3.small.search dev / r6g.large.search prod"
  type        = string
  default     = "t3.small.search"
}

variable "opensearch_instance_count" {
  type    = number
  default = 2
}

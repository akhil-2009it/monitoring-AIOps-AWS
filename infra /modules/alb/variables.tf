variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "acm_certificate_arn" {
  description = "ACM cert ARN for HTTPS listener. Must cover `api_hostname`."
  type        = string
  default     = ""
}

variable "api_hostname" {
  description = "DNS hostname the ALB will serve (e.g. api.mlops-learning.example.com)"
  type        = string
  default     = ""
}

variable "waf_web_acl_arn" {
  type        = string
  default     = ""
  description = "Optional WAFv2 ACL ARN to associate with this ALB."
}

variable "cognito_user_pool_arn" {
  type        = string
  default     = ""
  description = "Optional Cognito User Pool ARN — when set, ALB does OIDC auth before routing."
}

variable "cognito_user_pool_client_id" {
  type    = string
  default = ""
}

variable "cognito_user_pool_domain" {
  type    = string
  default = ""
}

variable "access_logs_bucket" {
  description = "Existing S3 bucket name for ALB access logs. Must have ELB log-write policy."
  type        = string
  default     = ""
}

variable "internal" {
  description = "Internal ALB (true) vs internet-facing (false)."
  type        = bool
  default     = false
}

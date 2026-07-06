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

variable "enable_eks_protection" {
  description = "Enable EKS audit log monitoring (requires EKS clusters)"
  type        = bool
  default     = true
}

variable "enable_malware_protection" {
  description = "Scan EBS volumes for malware on EC2 (extra cost)"
  type        = bool
  default     = false
}

variable "enable_s3_protection" {
  description = "Detect S3 data exfil patterns"
  type        = bool
  default     = true
}

variable "enable_rds_protection" {
  description = "Login anomaly detection on RDS"
  type        = bool
  default     = true
}

variable "enable_lambda_protection" {
  description = "Network activity monitoring on Lambdas"
  type        = bool
  default     = true
}

variable "findings_export_bucket_arn" {
  description = "Optional S3 bucket ARN to export findings to. Empty = no export."
  type        = string
  default     = ""
}

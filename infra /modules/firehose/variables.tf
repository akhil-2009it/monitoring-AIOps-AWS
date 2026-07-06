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

variable "raw_bucket_arn" {
  type = string
}

variable "raw_bucket_name" {
  type = string
}

variable "kms_key_arn" {
  description = "KMS key ARN used by the raw bucket. Firehose role needs Decrypt + GenerateDataKey on this."
  type        = string
}

variable "buffer_size_mb" {
  type    = number
  default = 64
}

variable "buffer_interval_sec" {
  type    = number
  default = 300
}

variable "enable_dynamic_partitioning" {
  description = "Use record partitioning by source/year/month/day/hour for cheap Athena queries"
  type        = bool
  default     = true
}

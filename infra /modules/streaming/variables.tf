variable "project" {
  type = string
}
variable "environment" {
  type = string
}
variable "kinesis_shard_count" {
  type    = number
  default = 2
}
variable "kinesis_retention_hours" {
  type    = number
  default = 48
}
variable "raw_bucket_name" {
  type = string
}
variable "sagemaker_exec_role_arn" {
  type = string
}
variable "tags" {
  type    = map(string)
  default = {}
}

variable "lambda_memory_mb" {
  description = "Lambda consumer memory in MB"
  type        = number
  default     = 512
}

variable "lambda_timeout_sec" {
  description = "Lambda consumer timeout in seconds"
  type        = number
  default     = 60
}

variable "batch_size" {
  description = "Kinesis batch size for Lambda trigger"
  type        = number
  default     = 100
}

variable "project" {
  type = string
}
variable "environment" {
  type = string
}
variable "aws_region" {
  type = string
}
variable "account_id" {
  type = string
}
variable "feature_store_bucket" {
  type = string
}
variable "models_bucket" {
  type = string
}
variable "tags" {
  type    = map(string)
  default = {}
}

variable "sagemaker_instance_type" {
  description = "Inference instance type. Default ml.t2.medium (~$0.065/hr). Max GPU: ml.g4dn.xlarge."
  type        = string
  default     = "ml.t2.medium"
}

variable "knowledge_tracing_instance_type" {
  description = "Knowledge tracing inference instance (sequence model needs more memory)"
  type        = string
  default     = "ml.c5.large"
}

variable "endpoint_initial_instance_count" {
  type    = number
  default = 1
}

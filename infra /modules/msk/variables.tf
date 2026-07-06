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

variable "private_subnet_ids" {
  type = list(string)
}

variable "broker_count" {
  description = "Number of brokers (must be multiple of subnet count)"
  type        = number
  default     = 3
}

variable "broker_instance_type" {
  description = "Use kafka.t3.small in dev (~$33/month/broker), kafka.m5.large in prod"
  type        = string
  default     = "kafka.t3.small"
}

variable "kafka_version" {
  type    = string
  default = "3.6.0"
}

variable "ebs_volume_size_gb" {
  type    = number
  default = 100
}

variable "client_authentication_iam" {
  description = "Use IAM auth (recommended for AWS-native producers/consumers)"
  type        = bool
  default     = true
}

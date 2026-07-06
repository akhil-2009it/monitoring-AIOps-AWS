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

variable "instance_type" {
  description = "OpenSearch instance type. Use t3.small.search in dev (~$26/month), r6g.large.search in prod"
  type        = string
  default     = "t3.small.search"
}

variable "instance_count" {
  type    = number
  default = 2
}

variable "engine_version" {
  type    = string
  default = "OpenSearch_2.13"
}

variable "ebs_volume_size_gb" {
  type    = number
  default = 50
}

variable "master_user_name" {
  type    = string
  default = "aiops_admin"
}

variable "allowed_iam_role_arns" {
  description = "Roles (e.g. scoring API IRSA, Lambda IRSA) allowed to query OpenSearch"
  type        = list(string)
  default     = []
}

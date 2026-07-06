variable "project" {
  description = "Project name. Defaults match the parent monitoring-mlops project."
  type        = string
  default     = "monitoring-mlops"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "vpc_id" {
  description = "VPC ID from the parent monitoring-mlops cluster"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets where RDS lives"
  type        = list(string)
}

variable "eks_node_security_group_id" {
  description = "EKS node SG; allowed to reach RDS on 3306"
  type        = string
}

variable "raw_bucket_arn" {
  description = "monitoring-mlops raw bucket ARN — slow query logs land here via Firehose"
  type        = string
}

variable "firehose_app_stream_name" {
  description = "monitoring-mlops Firehose stream for app source"
  type        = string
  default     = "monitoring-mlops-dev-app"
}

variable "rds_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "rds_allocated_storage" {
  type    = number
  default = 20
}

variable "tags" {
  type = map(string)
  default = {
    Component = "demo-app"
  }
}

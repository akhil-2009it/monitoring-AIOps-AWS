variable "project" {
  type = string
}
variable "environment" {
  type = string
}
variable "account_id" {
  type = string
}
variable "aws_region" {
  type = string
}
variable "models_bucket" {
  type = string
}
variable "sagemaker_exec_role_arn" {
  type = string
}
variable "eks_cluster_name" {
  type = string
}
variable "tags" {
  type    = map(string)
  default = {}
}

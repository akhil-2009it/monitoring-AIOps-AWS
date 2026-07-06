variable "project" {
  type = string
}
variable "environment" {
  type = string
}
variable "cluster_version" {
  type    = string
  default = "1.28"
}
variable "node_instance_types" {
  type    = list(string)
  default = ["m5.large"]
}
variable "node_min_size" {
  type    = number
  default = 2
}
variable "node_max_size" {
  type    = number
  default = 6
}
variable "node_desired_size" {
  type    = number
  default = 2
}
variable "vpc_id" {
  type = string
}
variable "private_subnet_ids" {
  type = list(string)
}
variable "sagemaker_exec_role_arn" {
  type = string
}
variable "tags" {
  type    = map(string)
  default = {}
}

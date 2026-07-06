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
variable "kinesis_stream_name" {
  type = string
}
variable "sagemaker_exec_role_arn" {
  type = string
}
variable "billing_alert_email" {
  type = string
}
variable "billing_threshold_warning_usd" {
  type    = number
  default = 50
}
variable "billing_threshold_critical_usd" {
  type    = number
  default = 100
}
variable "tags" {
  type    = map(string)
  default = {}
}

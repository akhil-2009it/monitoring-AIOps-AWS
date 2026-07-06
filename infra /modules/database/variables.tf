variable "project" {
  type = string
}
variable "environment" {
  type = string
}
variable "vpc_id" {
  type = string
}
variable "private_subnet_ids" {
  type = list(string)
}
variable "rds_instance_class" {
  type    = string
  default = "db.t3.micro"
}
variable "allocated_storage" {
  type    = number
  default = 20
}
variable "db_name" {
  type    = string
  default = "mlops_students"
}
variable "tags" {
  type    = map(string)
  default = {}
}

variable "multi_az" {
  description = "Enable Multi-AZ (always true in prod)"
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

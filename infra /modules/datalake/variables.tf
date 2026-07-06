variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "account_id" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "raw_retention_days" {
  description = "S3 lifecycle — transition raw data to Glacier after N days"
  type        = number
  default     = 90
}

variable "processed_retention_days" {
  description = "S3 lifecycle — expire processed data after N days"
  type        = number
  default     = 365
}

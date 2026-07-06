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

variable "account_id" {
  type = string
}

variable "include_data_events" {
  description = "Capture S3 + Lambda data events. EXPENSIVE on hot buckets — measure first."
  type        = bool
  default     = false
}

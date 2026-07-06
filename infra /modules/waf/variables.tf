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

variable "rate_limit_per_5min" {
  description = "Per-IP request limit over a 5-minute window"
  type        = number
  default     = 2000
}

variable "blocked_country_codes" {
  description = "ISO country codes to block. Empty = no geo blocking."
  type        = list(string)
  default     = []
}

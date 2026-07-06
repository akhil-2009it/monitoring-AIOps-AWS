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

variable "alert_email" {
  type = string
}

variable "monthly_budget_usd" {
  type    = number
  default = 200
}

variable "thresholds_pct" {
  description = "Budget % thresholds at which to alert (warning, critical)"
  type        = list(number)
  default     = [50, 80, 100, 120]
}

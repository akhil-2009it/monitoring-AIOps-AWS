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

variable "callback_urls" {
  description = "OAuth callback URLs (post-login redirect). Update for prod domain."
  type        = list(string)
  default     = ["https://localhost:3000/auth/callback"]
}

variable "logout_urls" {
  description = "OAuth post-logout redirect URLs."
  type        = list(string)
  default     = ["https://localhost:3000/auth/logout"]
}

variable "password_minimum_length" {
  type    = number
  default = 12
}

variable "mfa_configuration" {
  description = "MFA setting: OFF | ON | OPTIONAL. Use ON in prod."
  type        = string
  default     = "OPTIONAL"
}

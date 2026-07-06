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

variable "alert_manager_definition_yaml" {
  description = "Optional inline alert manager YAML — empty = no alert manager configured"
  type        = string
  default     = ""
}

variable "remote_write_role_principals" {
  description = "IRSA OIDC subjects allowed to remote-write (e.g. system:serviceaccount:monitoring:adot-collector)"
  type        = list(string)
  default     = []
}

variable "eks_oidc_provider_arn" {
  description = "OIDC provider ARN from the EKS module"
  type        = string
  default     = ""
}

variable "eks_oidc_provider_url" {
  description = "OIDC provider URL (no https://) from the EKS module"
  type        = string
  default     = ""
}

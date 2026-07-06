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

variable "amp_workspace_arn" {
  type = string
}

variable "data_sources" {
  type    = list(string)
  default = ["PROMETHEUS", "CLOUDWATCH", "AMAZON_OPENSEARCH_SERVICE", "XRAY"]
}

variable "authentication_providers" {
  type    = list(string)
  default = ["AWS_SSO"]
}

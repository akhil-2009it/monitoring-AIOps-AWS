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

variable "enable_aws_foundational" {
  type    = bool
  default = true
}

variable "enable_cis_v1_4" {
  type    = bool
  default = true
}

variable "enable_pci_dss" {
  type    = bool
  default = false
}

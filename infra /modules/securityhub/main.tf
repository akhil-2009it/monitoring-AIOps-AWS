data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  prefix     = "${var.project}-${var.environment}"
  region     = data.aws_region.current.name
  account_id = data.aws_caller_identity.current.account_id
}

resource "aws_securityhub_account" "main" {
  enable_default_standards = false
}

resource "aws_securityhub_standards_subscription" "aws_foundational" {
  count         = var.enable_aws_foundational ? 1 : 0
  standards_arn = "arn:aws:securityhub:${local.region}::standards/aws-foundational-security-best-practices/v/1.0.0"
  depends_on    = [aws_securityhub_account.main]
}

resource "aws_securityhub_standards_subscription" "cis_v1_4" {
  count         = var.enable_cis_v1_4 ? 1 : 0
  standards_arn = "arn:aws:securityhub:${local.region}::standards/cis-aws-foundations-benchmark/v/1.4.0"
  depends_on    = [aws_securityhub_account.main]
}

resource "aws_securityhub_standards_subscription" "pci_dss" {
  count         = var.enable_pci_dss ? 1 : 0
  standards_arn = "arn:aws:securityhub:${local.region}::standards/pci-dss/v/3.2.1"
  depends_on    = [aws_securityhub_account.main]
}

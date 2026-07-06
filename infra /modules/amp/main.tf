locals {
  prefix = "${var.project}-${var.environment}"
}

resource "aws_prometheus_workspace" "main" {
  alias = "${local.prefix}-amp"

  tags = merge(var.tags, { Name = "${local.prefix}-amp" })
}

resource "aws_prometheus_alert_manager_definition" "main" {
  count        = var.alert_manager_definition_yaml != "" ? 1 : 0
  workspace_id = aws_prometheus_workspace.main.id
  definition   = var.alert_manager_definition_yaml
}

# ─── IRSA — ADOT collector remote-write role ─────────────────────────────────
resource "aws_iam_role" "remote_write" {
  count = var.eks_oidc_provider_arn != "" && length(var.remote_write_role_principals) > 0 ? 1 : 0

  name = "${local.prefix}-amp-remote-write"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      for sub in var.remote_write_role_principals : {
        Effect    = "Allow"
        Principal = { Federated = var.eks_oidc_provider_arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = { "${var.eks_oidc_provider_url}:sub" = sub }
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "remote_write" {
  count = length(aws_iam_role.remote_write)
  name  = "${local.prefix}-amp-remote-write-policy"
  role  = aws_iam_role.remote_write[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "aps:RemoteWrite",
        "aps:GetSeries",
        "aps:GetLabels",
        "aps:GetMetricMetadata",
      ]
      Resource = aws_prometheus_workspace.main.arn
    }]
  })
}

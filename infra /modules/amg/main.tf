locals {
  prefix = "${var.project}-${var.environment}"
}

# ─── IAM role Grafana uses to read AMP / OpenSearch / CW ─────────────────────
resource "aws_iam_role" "grafana" {
  name = "${local.prefix}-grafana-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "grafana.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "amp" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonPrometheusQueryAccess"
}

resource "aws_iam_role_policy_attachment" "cw" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "xray" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayReadOnlyAccess"
}

resource "aws_iam_role_policy" "amg_extras" {
  name = "${local.prefix}-grafana-extras"
  role = aws_iam_role.grafana.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "es:ESHttpGet",
          "es:ESHttpPost",
          "es:DescribeDomain",
        ]
        Resource = "*"
      },
    ]
  })
}

# ─── Managed Grafana workspace ───────────────────────────────────────────────
resource "aws_grafana_workspace" "main" {
  name                     = "${local.prefix}-grafana"
  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = var.authentication_providers
  permission_type          = "SERVICE_MANAGED"
  data_sources             = var.data_sources
  role_arn                 = aws_iam_role.grafana.arn

  tags = merge(var.tags, { Name = "${local.prefix}-grafana" })
}

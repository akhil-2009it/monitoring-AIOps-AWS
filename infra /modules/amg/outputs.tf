output "workspace_id" {
  value = aws_grafana_workspace.main.id
}

output "workspace_endpoint" {
  value = aws_grafana_workspace.main.endpoint
}

output "workspace_url" {
  value = "https://${aws_grafana_workspace.main.endpoint}"
}

output "role_arn" {
  value = aws_iam_role.grafana.arn
}

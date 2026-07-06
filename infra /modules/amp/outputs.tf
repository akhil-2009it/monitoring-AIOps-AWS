output "workspace_id" {
  value = aws_prometheus_workspace.main.id
}

output "workspace_arn" {
  value = aws_prometheus_workspace.main.arn
}

output "remote_write_url" {
  value = "${aws_prometheus_workspace.main.prometheus_endpoint}api/v1/remote_write"
}

output "query_url" {
  value = "${aws_prometheus_workspace.main.prometheus_endpoint}api/v1/query"
}

output "remote_write_role_arn" {
  value = length(aws_iam_role.remote_write) > 0 ? aws_iam_role.remote_write[0].arn : ""
}

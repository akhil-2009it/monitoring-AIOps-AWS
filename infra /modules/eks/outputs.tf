output "resource_arn" { value = aws_eks_cluster.main.arn }
output "resource_name" { value = aws_eks_cluster.main.name }
output "resource_id" { value = aws_eks_cluster.main.id }

output "cluster_name" { value = aws_eks_cluster.main.name }
output "cluster_arn" { value = aws_eks_cluster.main.arn }
output "cluster_endpoint" { value = aws_eks_cluster.main.endpoint }
output "cluster_version" { value = aws_eks_cluster.main.version }

output "cluster_certificate_authority" {
  value     = aws_eks_cluster.main.certificate_authority[0].data
  sensitive = true
}

output "oidc_provider_arn" { value = aws_iam_openid_connect_provider.eks.arn }
output "oidc_provider_url" { value = aws_iam_openid_connect_provider.eks.url }

output "recommendation_api_irsa_arn" {
  description = "IRSA role ARN — annotate the Kubernetes service account with this"
  value       = aws_iam_role.recommendation_api.arn
}

output "ecr_repository_urls" {
  value = { for k, v in aws_ecr_repository.repos : k => v.repository_url }
}

output "node_role_arn" { value = aws_iam_role.eks_nodes.arn }

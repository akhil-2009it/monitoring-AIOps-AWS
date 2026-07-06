output "user_pool_id" {
  value       = aws_cognito_user_pool.students.id
  description = "Cognito User Pool ID — used by API to verify JWTs"
}

output "user_pool_arn" {
  value = aws_cognito_user_pool.students.arn
}

output "user_pool_endpoint" {
  value       = aws_cognito_user_pool.students.endpoint
  description = "Issuer endpoint for JWT verification"
}

output "client_id" {
  value       = aws_cognito_user_pool_client.spa.id
  description = "App client ID for the SPA"
}

output "domain" {
  value       = aws_cognito_user_pool_domain.main.domain
  description = "Hosted UI domain prefix"
}

output "hosted_ui_url" {
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}

data "aws_region" "current" {}

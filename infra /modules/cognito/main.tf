locals {
  prefix = "${var.project}-${var.environment}"
}

# ─── Cognito User Pool — student authentication ──────────────────────────────
resource "aws_cognito_user_pool" "students" {
  name = "${local.prefix}-students"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = var.password_minimum_length
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 3
  }

  mfa_configuration = var.mfa_configuration

  software_token_mfa_configuration {
    enabled = var.mfa_configuration != "OFF"
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "student_id"
    attribute_data_type = "String"
    mutable             = false
    required            = false
    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }

  schema {
    name                = "level"
    attribute_data_type = "String"
    mutable             = true
    required            = false
    string_attribute_constraints {
      min_length = 1
      max_length = 32
    }
  }

  email_configuration {
    email_sending_account = "COGNITO_DEFAULT" # switch to SES in prod for higher quota
  }

  user_pool_add_ons {
    advanced_security_mode = var.environment == "prod" ? "ENFORCED" : "AUDIT"
  }

  deletion_protection = var.environment == "prod" ? "ACTIVE" : "INACTIVE"

  tags = merge(var.tags, { Name = "${local.prefix}-students" })
}

# ─── App Client — used by the React SPA + the FastAPI backend ────────────────
resource "aws_cognito_user_pool_client" "spa" {
  name         = "${local.prefix}-spa-client"
  user_pool_id = aws_cognito_user_pool.students.id

  generate_secret               = false # SPA cannot store a secret
  prevent_user_existence_errors = "ENABLED"

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  access_token_validity  = 60 # minutes
  id_token_validity      = 60
  refresh_token_validity = 30 # days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# ─── Hosted UI domain ────────────────────────────────────────────────────────
resource "aws_cognito_user_pool_domain" "main" {
  domain       = local.prefix
  user_pool_id = aws_cognito_user_pool.students.id
}

# ─── Default groups for level-based access (used as authz claims in JWT) ─────
resource "aws_cognito_user_group" "levels" {
  for_each = toset(["beginner", "intermediate", "advanced", "instructor", "admin"])

  name         = each.key
  user_pool_id = aws_cognito_user_pool.students.id
  description  = "Student level: ${each.key}"
  precedence   = each.key == "admin" ? 1 : (each.key == "instructor" ? 2 : 10)
}

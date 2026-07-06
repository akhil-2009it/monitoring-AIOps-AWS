# Cognito — Production Pre-Apply Checklist

Before `terraform apply` against a `prod` workspace:

- [ ] **callback_urls / logout_urls** updated to your real production hostnames (HTTPS only)
- [ ] **mfa_configuration = "ON"** in prod (currently `OPTIONAL` default)
- [ ] **email_sending_account = "DEVELOPER"** with verified SES identity (Cognito default has 50/day cap)
- [ ] **advanced_security_mode = "ENFORCED"** is set automatically when `var.environment == "prod"` — verify
- [ ] **deletion_protection = "ACTIVE"** is set automatically in prod — verify in console after apply
- [ ] **Custom domain** (e.g. `auth.your-domain.com`) configured via `aws_cognito_user_pool_domain` with ACM cert — currently uses default `*.amazoncognito.com`
- [ ] **WAF associated** with the User Pool ARN (block credential-stuffing)
- [ ] **Triggers** defined for `pre-signup` (email-domain allowlist for FERPA), `post-confirmation` (write student_id to RDS)
- [ ] **GDPR / FERPA**: document where PII (email, name) is stored and your data subject access process
- [ ] **Token validity** review: 60-min access tokens are reasonable; if you need shorter, drop to 15
- [ ] **Backup**: User pools cannot be backed up natively — keep `student_id` in RDS as the durable record

## Out of scope for this scaffold
- Federated identity (Google / Apple / SAML SSO) — add via `aws_cognito_identity_provider` per IdP
- Adaptive auth rules (block IP ranges, require MFA from new device) — configured in console post-apply

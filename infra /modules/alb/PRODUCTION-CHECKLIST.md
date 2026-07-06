# ALB — Production Pre-Apply Checklist

- [ ] **acm_certificate_arn** set — without it, ALB serves HTTP only (insecure). Issue cert in same region as ALB (ap-south-1).
- [ ] **api_hostname** matches the SAN/CN on the ACM cert
- [ ] **access_logs_bucket** set to a private S3 bucket with the [ELB account logging policy](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/enable-access-logging.html#attach-bucket-policy). Must be in same region.
- [ ] **enable_deletion_protection** auto-on in prod — verify
- [ ] **drop_invalid_header_fields = true** — already set; reject malformed headers (CVE mitigation)
- [ ] **ssl_policy** is TLS 1.3 by default; do not downgrade to TLS-1-0
- [ ] **HTTP→HTTPS redirect** verified working (curl `http://<host>` should return 301)
- [ ] **Health check** path `/health` reachable from ALB SG (currently allows from anywhere internet → SG; SG → EKS pods is via TGB)
- [ ] **WAF associated** before exposing publicly — see `../waf/PRODUCTION-CHECKLIST.md`
- [ ] **Cognito on listener** redirects to hosted UI on unauth — confirm callback URL whitelisted in Cognito client
- [ ] **Route53 record** pointing to ALB — not handled by this module; add an `aws_route53_record` in root or a separate dns module

## Cost
- ALB: ~$22/month + $0.008/LCU-hour
- For ~50M req/month: ~$60-80/month total

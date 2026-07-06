# WAFv2 — Production Pre-Apply Checklist

- [ ] `rate_limit_per_5min` calibrated to your expected peak (default 2000 req/5min/IP). For 500K students, monitor "blocked legitimate" in CloudWatch and tune up.
- [ ] **Anonymous IP rule** is set to `count` mode by default — flip to `block` once you've validated no internal infra hits via VPN/proxy
- [ ] **CommonRuleSet** has known false positives for JSON bodies > 8KB. Add `RuleActionOverride` for `SizeRestrictions_BODY` if you accept large submissions
- [ ] **Bot Control** managed rule (extra cost: $10/month + $1/million requests) — add for credential stuffing protection
- [ ] **Logging redaction** covers `authorization` + `cookie` only — add any custom auth headers
- [ ] **Sampled request inspection** — review captured samples weekly during ramp-up
- [ ] **Cognito User Pool**: Cognito UserPool WAF requires a *separate* WAF ACL (the User Pool itself, not just the API ALB). Add a second `aws_wafv2_web_acl` with `scope = REGIONAL` if not already.

## Cost
- Web ACL base: $5/month
- Each managed rule group: $1/month
- $0.60 per million requests inspected
- Estimated for 50M req/month: ~$40/month

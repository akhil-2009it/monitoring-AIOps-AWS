# Runbook — DDoS detected

**Triggers**:
- WAF rate-based rule blocked > N requests in 5m
- `ddos-distinct-ips` static rule fired (distinct src_ips > 10000/min)
- RCF metric detector flagged `request_rate_5m` anomaly score > 5

## First 2 minutes
1. Confirm volume: AMG → "AIOps overview" dashboard → request_rate panel.
2. Identify scope:
   ```bash
   aws wafv2 get-sampled-requests \
     --web-acl-arn $(terraform -chdir='infra ' output -raw waf_web_acl_arn) \
     --rule-metric-name RateLimitPerIP --scope REGIONAL \
     --time-window StartTime=...,EndTime=... --max-items 100
   ```
3. Check whether GuardDuty also raised a finding (`UnauthorizedAccess:S3/MaliciousIPCaller.Custom`, `Recon:EC2/PortProbeUnprotectedPort`).

## Mitigations
| Action | Command |
|---|---|
| Tighten WAF rate limit | Update `var.waf_rate_limit_per_5min` and re-apply |
| Block country / ASN | Add to `var.waf_blocked_country_codes`; or update WAFv2 ACL via console |
| Drop anonymous IP rule from `count` to `block` | Edit `infra /modules/waf/main.tf` |
| Front with CloudFront | If origin ALB is direct, move to CloudFront + Shield Advanced |
| Enable Shield Advanced | One-off purchase; gives DDoS Response Team access |

## Escalation
- ≥ 50% packet loss: page on-call + AWS Shield team
- Confirmed L7 attack > 30 min: post-incident review + WAF rule tuning

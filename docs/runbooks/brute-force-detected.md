# Runbook — Brute force / credential stuffing

**Triggers**:
- `iforest-logs` flagged a (source=app, host=…, window) bucket with `auth_failure_rate > 0.5`
- Streaming `zscore-auth_failure_rate` rule fired
- GuardDuty `UnauthorizedAccess:IAMUser/ConsoleLogin` or `:RDS/Cred*` finding

## First 5 minutes
1. Pull the failed login pattern:
   ```sql
   -- in OpenSearch dashboards (KQL)
   source: "app" AND status: 401 AND path: *login*
   | stats count() by src_ip, user
   | sort -count
   ```
2. Are the targets few users (account takeover) or many (stuffing)?
3. Check Cognito AdvancedSecurity findings (if enforced).

## Mitigations
| Risk | Action |
|---|---|
| Targeted account | Force MFA reset, invalidate refresh tokens for the user |
| Multiple accounts | WAF block on attacker IP set; rotate API keys |
| Stuffing | Enable Cognito advanced security adaptive risk; disable email-based password reset for X hours |

## Tagging the alert
- Use `POST /feedback` with `label=true_positive` once confirmed; this trains the next retrain cycle.

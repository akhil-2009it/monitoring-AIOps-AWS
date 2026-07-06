# Service Level Objectives — AIOps Platform

| Service | SLI | SLO | Window |
|---|---|---|---|
| Anomaly Scoring API | p99 request latency | < 250 ms | 30-day |
| Anomaly Scoring API | Availability (2xx + 4xx)/total | ≥ 99.5 % | 30-day |
| Anomaly Scoring API | Error rate (5xx/total) | < 0.5 % | 30-day |
| Streaming detector | MTTD (alert vs anomaly onset) | < 90 s | per-incident |
| ML detector | MTTD after training cycle | < 5 min | per-incident |
| Firehose ingest | iterator age / S3 lag | < 5 min p99 | 5-min rolling |
| MSK consumer | ConsumerLag | < 60 s p99 | 5-min rolling |
| OpenSearch | Cluster status `green` | ≥ 99.5 % uptime | 30-day |
| Per-detector | False-positive rate | < 5 % | 30-day rolling, after labels |
| Auto-retrain | Drift alarm → deployed model | < 6 h | per-incident |

## Error budget — API
For 99.5% availability over 30 days:
- Allowed downtime: **3.6 hours / month**
- Multi-window multi-burn-rate alerts:
  - 2 % budget burned in 1 h → page
  - 5 % burned in 6 h → page
  - 10 % burned in 3 d → ticket

## False-positive budget
After 30 days of analyst feedback (`POST /feedback`):
- Per-detector precision target ≥ 95% on top-1% scores.
- Below 90% for a week → pause auto-retrain, run false-positive-review runbook, tune.

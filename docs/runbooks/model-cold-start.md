# Runbook — Model cold-start

The platform ships in two operational modes:

| State | What's running | Coverage |
|---|---|---|
| **Day 0–7**  | Streaming statistical + AWS-managed (GuardDuty + WAF) only | Volume / rate / threshold rules; managed threat intel |
| **Day 7+**   | Above + 4 SageMaker detectors live | Statistical + ML; richer feature space |

## How to know which state you're in

```bash
curl -s "$API/health" | jq '.sagemaker_endpoints'
```
- `[]` → cold-start. ML models not yet live.
- `["rcf_metrics", ...]` → warm.

## Going from cold to warm

1. Enough data: confirm at least **7 days** of representative log + metric volume in `s3://monitoring-mlops-{env}-processed/`. Less = unstable detectors.
2. Run all 4 pipelines once in `--upsert-only` mode to register them in SageMaker Pipelines:
   ```bash
   gh workflow run ml-pipeline-trigger.yml -f model=rcf-metrics    -f environment=dev -f upsert_only=true
   gh workflow run ml-pipeline-trigger.yml -f model=iforest-logs   -f environment=dev -f upsert_only=true
   gh workflow run ml-pipeline-trigger.yml -f model=lstm-ae-traces -f environment=dev -f upsert_only=true
   gh workflow run ml-pipeline-trigger.yml -f model=log-embedding-anomaly -f environment=dev -f upsert_only=true
   ```
3. Run each without `--upsert-only` to actually train. Watch SageMaker Pipelines console.
4. Manually approve the model package in SageMaker Model Registry.
5. CodePipeline deploys to the endpoint; the ConfigMap for the API picks up the endpoint name (or set `MLOPS_ENDPOINT_RCF_METRICS=…` env var directly).
6. `helm rollout status` to confirm the API picked up the new env.

## During cold-start, what's caught vs missed

**Caught**:
- Volume/rate spikes (DDoS-shaped traffic)
- Threshold breaches (5xx > 5%)
- Z-score outliers on individual metrics
- All AWS-managed threat intel (GuardDuty, Security Hub)

**Missed** (until warm):
- Subtle multi-feature anomalies (RCF / IForest catch these)
- Trace-sequence anomalies (LSTM-AE)
- Log-line semantic anomalies (LogBERT-lite)

This is by design — you can't have ML detection without first observing normal.

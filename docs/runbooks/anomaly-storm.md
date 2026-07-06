# Runbook — Anomaly storm (too many alerts at once)

**Symptom**: alert volume spikes to 100s in a 5-minute window. Almost always one of:
1. Real correlated incident (database failover → 100 services see latency spike at once).
2. Detector input drift (e.g. baseline shifted because of a deploy).
3. Statistical-rule mis-tuning (too tight a z-score threshold).

## First 5 minutes
1. **Don't disable detectors** — that hides the real signal.
2. Group alerts by `metric_key` to see whether they share a dimension:
   ```bash
   curl -s "$API/alerts?limit=500" | jq 'group_by(.metric_key) | map({k:.[0].metric_key, n: length}) | sort_by(.n) | reverse | .[:10]'
   ```
3. Check input-PSI on affected detector. If PSI > 0.30 across many features, this is drift, not attack.
4. Cross-reference with deploys: did anything ship in the last 60 min? (CodeDeploy / GitHub Actions audit).

## Mitigations
- **If real incident**: route to incident commander; the alerts will quiet once the root cause is fixed.
- **If drift from deploy**: bump the detector's contamination/threshold via env var or trigger early retrain.
- **If mis-tuning**: edit `ml/streaming/rules.yaml` (or the rule defaults in `ml/streaming/detector.py::default_detector`) and redeploy.

## Long-term
- Add an "alert dedup" stage in the API that suppresses identical alerts within N minutes per metric_key.
- Add a "peer-group anomaly" — if 50+ services see the same anomaly, escalate as a single platform-level event, not 50 alerts.

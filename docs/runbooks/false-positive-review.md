# Runbook — False-positive review

False positives are inevitable in unsupervised anomaly detection. Goal:
keep FP rate < 5% (rolling 30 day) once we have feedback labels.

## Weekly process
1. Pull last week's alerts grouped by detector + label:
   ```bash
   curl -s "$API/alerts?since=$(date -u -v-7d +%FT%TZ)&limit=1000" \
     | jq 'group_by(.detector) | map({detector: .[0].detector, total: length, fp: map(select(.label=="false_positive")) | length})'
   ```
2. Compute precision per detector. Anything < 70% precision needs tuning.
3. Pick the loudest false-positive `metric_key`; inspect feature contributions.

## Knobs
| Lever | Effect |
|---|---|
| `iforest --contamination` | lower = fewer alerts but might miss real ones |
| `zscore.threshold` | raise from 4.0 → 5.0 to be stricter |
| Feature pruning | drop a feature whose noise dominates the score |
| Detector cooldown | per metric_key, suppress repeats for N min |

## Don't do
- Disable a detector to silence FPs — quietly hides real anomalies.
- Globally raise thresholds — may miss the rare-but-critical signal.
- Use in-prod as a labelled set without sampling — analyst time is the constraint.

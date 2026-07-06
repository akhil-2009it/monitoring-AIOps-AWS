# Runbook — Bring Your Own (Pre-Trained) Model

This is the path for skipping the 7-day cold-start by importing a model
that was trained somewhere else (staging, a research notebook, a
co-located prod environment).

**Before you read this**: read `model-cold-start.md` first. The headline
caveat there applies here too: a model trained on traffic that doesn't
match your production traffic will fire false positives until you retrain
on your own data. "Working in 1 hour" means *the endpoint is up*, not
*the alerts are useful*.

---

## Supported detectors

| Detector | Artifact format | Inference container |
|---|---|---|
| `iforest-logs` | sklearn `.joblib` (`IsolationForest` or `Pipeline`) | sagemaker-scikit-learn |
| `log-embedding-anomaly` | sklearn `.joblib` (`Pipeline(TfidfVectorizer, IsolationForest)`) | sagemaker-scikit-learn |
| `lstm-ae-traces` | PyTorch `.pt` with state_dict + vocab metadata | pytorch-inference |
| `rcf-metrics` | SageMaker-built RCF `model.tar.gz` | randomcutforest builtin |

**RCF is rare to import** — it's almost always retrained inside SageMaker.
The script supports it for completeness, but most teams just run the
SageMaker Pipeline.

---

## Required artifact format

### iforest-logs

Pickled `IsolationForest` (or sklearn `Pipeline` ending in one):

```python
from sklearn.ensemble import IsolationForest
import joblib

clf = IsolationForest(n_estimators=200, contamination=0.01)
clf.fit(X_train)   # X_train shape: (n_samples, n_features)
joblib.dump(clf, "iforest_logs.joblib")
```

Feature order **must match** `LOG_FEATURE_COLUMNS` in
`ml/feature_engineering/security_features.py`:

```
request_count, rate_4xx, rate_5xx, distinct_ips, distinct_paths,
auth_failure_rate, p99_latency_ms, p50_latency_ms, avg_bytes,
entropy_path, entropy_src_ip, user_agent_distinct
```

### log-embedding-anomaly

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
import joblib

pipe = Pipeline([
    ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4),
                              max_features=10_000, sublinear_tf=True)),
    ("if",    IsolationForest(n_estimators=200, contamination=0.01,
                              n_jobs=-1, random_state=42)),
])
pipe.fit(log_lines)   # list[str] of raw log messages
joblib.dump(pipe, "log_embedding.joblib")
```

### lstm-ae-traces

The checkpoint **must** include the vocab and dimensions used at training,
because the inference container needs them to construct the model:

```python
torch.save({
    "state_dict":   model.state_dict(),
    "feature_dim":  num_services + num_ops + 2,
    "hidden_dim":   64,
    "max_seq_len":  64,
    "vocab": {
        "num_services": num_services,
        "num_ops":      num_ops,
        "svc_to_id":    svc_to_id,   # dict[str, int]
        "op_to_id":     op_to_id,    # dict[str, int]
    },
}, "lstm_ae.pt")
```

### rcf-metrics

Take the `model.tar.gz` produced by the SageMaker training job verbatim
(found in the `output/` S3 prefix of the job).

---

## Procedure

### 1. Pre-flight check (your laptop)

```bash
# Confirm the artifact loads + has the expected shape.
python -c "
import joblib
m = joblib.load('iforest_logs.joblib')
print(type(m).__name__, getattr(m, 'n_features_in_', '?'))
"
```

### 2. Import

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ROLE_ARN=arn:aws:iam::${ACCOUNT}:role/monitoring-mlops-prod-sagemaker-exec-role
BUCKET=monitoring-mlops-prod-models

python scripts/import_pretrained_model.py \\
    --detector iforest-logs \\
    --artifact ./iforest_logs.joblib \\
    --env prod \\
    --region ap-south-1 \\
    --models-bucket "$BUCKET" \\
    --role-arn "$ROLE_ARN"
```

The script:
1. Loads the artifact locally and validates it.
2. Wraps it in a `model.tar.gz` with an inference handler script.
3. Uploads to `s3://<bucket>/imported/<detector>/<timestamp>/model.tar.gz`.
4. Registers a SageMaker Model Package in `<Detector>ModelGroup` with
   status `PendingManualApproval`.

Output ends with the next steps and the `kubectl` env-var command you'll
run after deployment.

### 3. Approve in SageMaker Model Registry

```bash
# CLI alternative to the console click:
aws sagemaker update-model-package \\
    --model-package-arn arn:aws:sagemaker:ap-south-1:ACCOUNT:model-package/IForestLogsModelGroup/123 \\
    --model-approval-status Approved
```

CodePipeline `monitoring-mlops-prod-iforest-logs-promotion` is watching the
group; on approval it deploys to the endpoint config + endpoint
(~25–30 min to InService).

### 4. Wire the endpoint name into the API

```bash
aws eks update-kubeconfig --name monitoring-mlops-prod --region ap-south-1

kubectl -n api set env deployment/anomaly-scoring-api \\
    MLOPS_ENDPOINT_IFOREST_LOGS=iforest-logs-prod
kubectl -n api rollout status deployment/anomaly-scoring-api
```

After the rollout completes, the next call to `POST /score` will fan out
to your imported model.

### 5. Verify

```bash
# Endpoint health
aws sagemaker describe-endpoint --endpoint-name iforest-logs-prod \\
    --query "EndpointStatus"

# API picks it up
curl -s "$API/health" | jq '.sagemaker_endpoints'
# → ["iforest_logs", ...]

# Scoring smoke test
bash scripts/smoke_test.sh --env prod
```

---

## Auto-approve (dev only)

For dev iteration you can skip the manual gate:

```bash
python scripts/import_pretrained_model.py \\
    --detector iforest-logs --artifact ./model.joblib \\
    --env dev --models-bucket monitoring-mlops-dev-models \\
    --role-arn $ROLE_ARN \\
    --auto-approve --wait-for-endpoint
```

`--wait-for-endpoint` blocks until `InService` so you can chain a smoke test.
Don't use `--auto-approve` in prod — the manual gate is a real audit point.

---

## Operational mode after import: "advisory" period

A pre-trained model that hasn't seen *your* traffic should not page on-call
on day 1. Run it in advisory mode for 48 hours:

1. Don't add it to the alarm SNS topic right away. Alerts still land in
   `s3://<anomalies>/anomalies/iforest-logs/...` and the API returns them
   in `/alerts`.
2. Have an analyst label them via `POST /feedback`:
   ```
   POST /feedback {"alert_id": "...", "label": "false_positive"}
   ```
3. After 24h, compute precision:
   ```bash
   curl -s "$API/alerts?since=$(date -u -v-1d +%FT%TZ)&limit=2000" \\
     | jq '[.[] | select(.detector=="iforest-logs")] |
            {tp: map(select(.label=="true_positive")) | length,
             fp: map(select(.label=="false_positive")) | length,
             unlabelled: map(select(.label==null)) | length}'
   ```
4. If precision ≥ 70%, promote to paging tier (CloudWatch alarm + SNS).
5. If precision < 50%, the model isn't a good fit. Two options:
   - Fine-tune: collect 7 days of your real labelled data, run
     `gh workflow run ml-pipeline-trigger.yml -f model=iforest-logs ...`
   - Disable the endpoint temporarily; lean on streaming statistical +
     GuardDuty for now.

---

## Constraints / gotchas

- **Feature order is load-bearing.** If you trained with the columns in a
  different order than `LOG_FEATURE_COLUMNS`, predictions are nonsense
  (the model will treat `request_count` as `rate_4xx`).
- **Vocab compatibility (LSTM-AE).** If a service or operation name in
  prod isn't in `vocab.svc_to_id`, the inference handler in this script
  silently skips it. Best practice: re-map unknowns to `<UNK>` before
  scoring, or retrain when vocab drifts.
- **Container version.** The inference container is pinned to a specific
  framework version (sklearn 1.2.1, PyTorch 2.1). Models trained with
  newer versions can deserialize but may behave subtly differently.
- **Reproducibility.** Stash the original training data, code, and
  hyperparameters somewhere version-controlled. Pre-trained imports lose
  the audit trail unless you keep this metadata.
- **Drift Lambda still runs.** Even after import, `monitoring/drift_lambda.tf`
  will compute PSI on detector inputs and trigger retrain on alarm. This
  is what closes the gap between "imported model" and "model that knows
  your data".

---

## Cost note

A SageMaker endpoint left running after import costs:
- `iforest-logs`           on `ml.m5.large`:  ~$3/day
- `log-embedding-anomaly`  on `ml.c5.xlarge`: ~$5/day
- `lstm-ae-traces`         on `ml.c5.large`:  ~$2/day
- `rcf-metrics`            on `ml.t2.medium`: ~$1.50/day

If you import a model just to test the wiring, delete the endpoint when
done — `aws sagemaker delete-endpoint --endpoint-name iforest-logs-dev`.

The model package and S3 artifact are cheap to keep; the endpoint is the
expensive part.

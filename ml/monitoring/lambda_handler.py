"""
Lambda entrypoint — scheduled drift check.

Triggered hourly by EventBridge (separate from the existing
`retrain-trigger` Lambda which fires on alarm STATE CHANGE).

Steps:
  1. Read the latest features parquet from S3 (current window).
  2. Read the baseline statistics + constraints from S3.
  3. Compute per-feature PSI, KL, missing-rate, out-of-bounds.
  4. Push metrics to CloudWatch.
  5. Append a JSON report to s3://<features>/drift-reports/{model}/{ts}.json.

Environment variables:
  MODEL_NAME           e.g. perf-predictor
  ENVIRONMENT          dev | qa | prod
  FEATURES_BUCKET      S3 bucket for features + reports
  BASELINE_PREFIX      e.g. baselines/perf-predictor/
  CURRENT_FEATURES_KEY e.g. features/perf-predictor/current.parquet
  PSI_WARN             default 0.10
  PSI_ALERT            default 0.20
"""
from __future__ import annotations

import io
import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NAMESPACE = "mlops-learning/drift"
s3 = boto3.client("s3")


def _download(bucket: str, key: str) -> bytes:
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def _ensure_baseline_local(bucket: str, baseline_prefix: str) -> str:
    """Pull baseline files into /tmp so the drift detector can read them."""
    local = "/tmp/baseline"
    os.makedirs(local, exist_ok=True)
    for name in ("statistics.json", "constraints.json"):
        body = _download(bucket, f"{baseline_prefix.rstrip('/')}/{name}")
        with open(f"{local}/{name}", "wb") as fh:
            fh.write(body)
    return local


def handler(event, context):  # noqa: ARG001 — Lambda signature
    import pandas as pd
    from ml.monitoring.drift_detector import emit_cloudwatch, evaluate_drift

    model       = os.environ["MODEL_NAME"]
    environment = os.environ["ENVIRONMENT"]
    bucket      = os.environ["FEATURES_BUCKET"]
    baseline    = os.environ["BASELINE_PREFIX"]
    current     = os.environ["CURRENT_FEATURES_KEY"]
    psi_warn    = float(os.getenv("PSI_WARN", "0.10"))
    psi_alert   = float(os.getenv("PSI_ALERT", "0.20"))

    logger.info("Drift run: model=%s env=%s bucket=%s baseline=%s current=%s",
                model, environment, bucket, baseline, current)

    current_bytes = _download(bucket, current)
    df = pd.read_parquet(io.BytesIO(current_bytes))
    if df.empty:
        logger.warning("Current features parquet is empty — skipping run.")
        return {"status": "no-data"}

    from pathlib import Path
    baseline_dir = Path(_ensure_baseline_local(bucket, baseline))
    reports = evaluate_drift(baseline_dir, df, psi_warn, psi_alert)
    emit_cloudwatch(reports, NAMESPACE, model, environment)

    body = {
        "model": model,
        "environment": environment,
        "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
        "psi_warn": psi_warn,
        "psi_alert": psi_alert,
        "reports": [r.to_dict() for r in reports],
        "alerts": [r.feature for r in reports if r.severity == "alert"],
    }

    key = f"drift-reports/{model}/{datetime.now(timezone.utc).strftime('%Y/%m/%d/%H%M%S')}.json"
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(body).encode(), ContentType="application/json")
    logger.info("Drift report written to s3://%s/%s — %d alerts", bucket, key, len(body["alerts"]))
    return {"status": "ok", "alerts": body["alerts"], "report_s3_uri": f"s3://{bucket}/{key}"}

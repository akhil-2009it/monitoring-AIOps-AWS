"""Evaluate log-embedding anomaly: precision @ top-1% with synthetic labels."""
from __future__ import annotations
import json, os, tarfile
from pathlib import Path
import joblib, numpy as np
from sklearn.metrics import precision_score

MODEL = Path("/opt/ml/processing/model")
EVAL  = Path("/opt/ml/processing/eval")
OUT   = Path("/opt/ml/processing/output"); OUT.mkdir(parents=True, exist_ok=True)
for tgz in MODEL.glob("*.tar.gz"):
    with tarfile.open(tgz) as t: t.extractall(MODEL)

pipe = joblib.load(next(MODEL.rglob("model.joblib")))
lines = (next(EVAL.rglob("lines.txt"))).read_text().splitlines()
scores = -pipe.named_steps["if"].score_samples(pipe.named_steps["tfidf"].transform(lines))
top_thresh = np.percentile(scores, 99)
y_pred = (scores >= top_thresh).astype(int)
# Synthetic labels: lines containing "error|fail|denied|exception" treated as anomalies
import re
keywords = re.compile(r"\b(error|fail|denied|exception|panic|fatal|crash|timeout)\b", re.I)
y_true = np.array([1 if keywords.search(l) else 0 for l in lines])

report = {
    "metrics": {
        "precision_at_top1pct": float(precision_score(y_true, y_pred, zero_division=0)),
        "anomaly_rate":         float(y_pred.mean()),
        "n_test":               int(len(lines)),
    },
}
(OUT / "evaluation.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report["metrics"]))

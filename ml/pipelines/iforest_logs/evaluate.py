"""Evaluate IF: precision @ top-1% (synthetic labels via z-score)."""
from __future__ import annotations
import json, os, tarfile
from pathlib import Path
import joblib, numpy as np, pandas as pd
from sklearn.metrics import precision_score, recall_score

MODEL = Path("/opt/ml/processing/model")
EVAL  = Path("/opt/ml/processing/eval")
OUT   = Path("/opt/ml/processing/output"); OUT.mkdir(parents=True, exist_ok=True)
for tgz in MODEL.glob("*.tar.gz"):
    with tarfile.open(tgz) as t: t.extractall(MODEL)

clf = joblib.load(next(MODEL.rglob("model.joblib")))
X = pd.read_csv(next(EVAL.rglob("*.csv")), header=None).to_numpy(dtype=float)

scores = -clf.score_samples(X)  # higher = more anomalous
thresh = np.percentile(scores, 99)  # top 1%

# Synthetic labels: top 1% by combined z-score
mean = X.mean(0); std = X.std(0) + 1e-9
z = np.abs((X-mean)/std).max(axis=1)
y_true = (z >= np.percentile(z, 99)).astype(int)
y_pred = (scores >= thresh).astype(int)

report = {
    "metrics": {
        "precision_at_top1pct": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall_at_top1pct":    float(recall_score(y_true, y_pred, zero_division=0)),
        "n_test":               int(len(y_true)),
    }
}
(OUT / "evaluation.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report["metrics"]))

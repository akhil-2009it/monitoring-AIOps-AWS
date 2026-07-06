"""Build per-(host, metric, window) feature CSV for RCF.

Input: parquet/jsonl of CommonEvent metric samples in /opt/ml/processing/input/
Output: train + test CSVs (no label, just features) in METRIC_FEATURE_COLUMNS order.
"""
from __future__ import annotations
import json, os, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

INPUT = Path(os.getenv("PROCESSING_INPUT", "/opt/ml/processing/input"))
TRAIN = Path(os.getenv("PROCESSING_TRAIN", "/opt/ml/processing/train")); TRAIN.mkdir(parents=True, exist_ok=True)
TEST  = Path(os.getenv("PROCESSING_TEST",  "/opt/ml/processing/test"));  TEST.mkdir(parents=True, exist_ok=True)
WINDOW_SEC = int(os.getenv("WINDOW_SEC", "300"))
SEED  = int(os.getenv("SEED", "42"))

# Inline because SageMaker container won't have the project package available.
METRIC_FEATURE_COLUMNS = ("value_p50", "value_p95", "value_p99", "value_max", "delta_p50", "slope")


def _percentile(xs, q):
    if not xs: return 0.0
    s = sorted(xs); n = len(s)
    if n == 1: return float(s[0])
    import math
    k = (n - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return float(s[lo]) if lo == hi else float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def _slope(points):
    n = len(points)
    if n < 2: return 0.0
    sx = sum(p[0] for p in points); sy = sum(p[1] for p in points)
    sxy = sum(p[0]*p[1] for p in points); sxx = sum(p[0]*p[0] for p in points)
    denom = n*sxx - sx*sx
    return 0.0 if denom == 0 else (n*sxy - sx*sy)/denom


def load(path: Path):
    rows = []
    for f in sorted(path.rglob("*")):
        if f.suffix.lower() == ".parquet":
            rows.extend(pd.read_parquet(f).to_dict(orient="records"))
        elif f.suffix.lower() == ".jsonl":
            for line in f.read_text().splitlines():
                if line.strip(): rows.append(json.loads(line))
    return rows


def main():
    events = load(INPUT)
    if not events:
        print("No data", file=sys.stderr); sys.exit(2)

    # Group by (host, metric, window-floor)
    buckets = defaultdict(list)
    for ev in events:
        attrs = ev.get("attrs") or {}
        m = attrs.get("metric")
        try:
            v = float(attrs.get("value"))
        except (TypeError, ValueError): continue
        try:
            from datetime import datetime
            ts = datetime.fromisoformat((ev["ts"] or "").replace("Z","+00:00")).timestamp()
        except Exception: continue
        win = int(ts) - (int(ts) % WINDOW_SEC)
        key = (ev.get("host") or "", m or "", win)
        buckets[key].append((ts, v))

    prev_p50 = {}
    rows = []
    for (host, metric, win), pts in sorted(buckets.items(), key=lambda kv: kv[0][2]):
        values = [v for _, v in pts]
        p50 = _percentile(values, 0.5); p95 = _percentile(values, 0.95)
        p99 = _percentile(values, 0.99); vmax = max(values) if values else 0
        delta = p50 - prev_p50.get((host, metric), p50)
        prev_p50[(host, metric)] = p50
        rows.append([p50, p95, p99, vmax, delta, _slope(pts)])

    if len(rows) < 100:
        print(f"Only {len(rows)} feature rows — need ≥ 100 for RCF", file=sys.stderr); sys.exit(2)

    rng = np.random.RandomState(SEED)
    perm = rng.permutation(len(rows))
    n_test = max(20, int(len(rows) * 0.20))
    test, train = [rows[i] for i in perm[:n_test]], [rows[i] for i in perm[n_test:]]

    pd.DataFrame(train).to_csv(TRAIN / "data.csv", index=False, header=False)
    pd.DataFrame(test ).to_csv(TEST  / "data.csv", index=False, header=False)
    print(f"train={len(train)} test={len(test)} columns={list(METRIC_FEATURE_COLUMNS)}")


if __name__ == "__main__":
    main()

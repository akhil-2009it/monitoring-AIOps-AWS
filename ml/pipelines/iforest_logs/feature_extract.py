"""Build LOG_FEATURE_COLUMNS rows per (source, host, window). Inline computation
(SageMaker container can't import the project package)."""
from __future__ import annotations
import json, math, os, sys, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

INPUT = Path(os.getenv("PROCESSING_INPUT", "/opt/ml/processing/input"))
TRAIN = Path(os.getenv("PROCESSING_TRAIN", "/opt/ml/processing/train")); TRAIN.mkdir(parents=True, exist_ok=True)
TEST  = Path(os.getenv("PROCESSING_TEST",  "/opt/ml/processing/test"));  TEST.mkdir(parents=True, exist_ok=True)
WINDOW_SEC = int(os.getenv("WINDOW_SEC", "300"))
SEED  = int(os.getenv("SEED", "42"))

LOG_FEATURE_COLUMNS = (
    "request_count", "rate_4xx", "rate_5xx",
    "distinct_ips", "distinct_paths", "auth_failure_rate",
    "p99_latency_ms", "p50_latency_ms", "avg_bytes",
    "entropy_path", "entropy_src_ip", "user_agent_distinct",
)
AUTH_HINTS = ("login", "auth", "signin", "logon", "token")


def percentile(xs, q):
    if not xs: return 0.0
    s = sorted(xs); n = len(s)
    if n == 1: return float(s[0])
    k = (n - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return float(s[lo]) if lo == hi else float(s[lo] + (s[hi]-s[lo])*(k-lo))


def entropy(values):
    counts = Counter(values); total = sum(counts.values())
    if total <= 1: return 0.0
    return -sum((c/total)*math.log2(c/total) for c in counts.values() if c)


def load(path):
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

    buckets = defaultdict(list)
    for ev in events:
        try:
            ts = datetime.fromisoformat(ev["ts"].replace("Z","+00:00")).timestamp()
        except Exception: continue
        win = int(ts) - (int(ts) % WINDOW_SEC)
        buckets[(ev.get("source",""), ev.get("host") or "", win)].append(ev)

    rows = []
    for _, evs in buckets.items():
        n = len(evs)
        statuses = [e["status"] for e in evs if isinstance(e.get("status"), int)]
        src_ips = [e.get("src_ip") for e in evs if e.get("src_ip")]
        paths = [e.get("path") or "" for e in evs]
        uas = [e.get("user_agent") for e in evs if e.get("user_agent")]
        bytes_ = [e["bytes"] for e in evs if isinstance(e.get("bytes"), (int,float))]
        lats = [e["latency_ms"] for e in evs if isinstance(e.get("latency_ms"), (int,float))]
        auth_fail = sum(1 for e in evs if e.get("severity") in ("ERROR","WARN")
                        and any(h in (e.get("path") or "") for h in AUTH_HINTS))
        rows.append([
            n,
            sum(1 for s in statuses if 400<=s<500)/n,
            sum(1 for s in statuses if 500<=s<600)/n,
            len(set(src_ips)),
            len(set(paths)),
            auth_fail/n,
            percentile(lats, 0.99),
            percentile(lats, 0.50),
            statistics.mean(bytes_) if bytes_ else 0.0,
            entropy(paths),
            entropy(src_ips),
            len(set(uas)),
        ])

    if len(rows) < 100:
        print(f"Only {len(rows)} rows — need ≥ 100", file=sys.stderr); sys.exit(2)

    rng = np.random.RandomState(SEED)
    perm = rng.permutation(len(rows))
    n_test = max(20, int(len(rows)*0.20))
    test = [rows[i] for i in perm[:n_test]]
    train = [rows[i] for i in perm[n_test:]]
    pd.DataFrame(train).to_csv(TRAIN/"data.csv", index=False, header=False)
    pd.DataFrame(test ).to_csv(TEST /"data.csv", index=False, header=False)
    print(f"train={len(train)} test={len(test)}")


if __name__ == "__main__":
    main()

"""
Security feature engineering.

Two feature shapes used by the detectors:

  LOG  features  (Detector 2 — Isolation Forest on tabular log features)
      grouped by (source, host, window_start_iso)
      ▷ request_count            : N events in the window
      ▷ rate_4xx                 : count(status 400-499) / N
      ▷ rate_5xx                 : count(status 500-599) / N
      ▷ distinct_ips             : approx-distinct count of src_ip
      ▷ distinct_paths           : approx-distinct of path
      ▷ auth_failure_rate        : count(severity=ERROR + path~login|auth) / N
      ▷ p99_latency_ms           : 99th percentile of latency_ms
      ▷ p50_latency_ms           : 50th percentile of latency_ms
      ▷ avg_bytes                : mean of bytes
      ▷ entropy_path             : Shannon entropy over path → catches scanners
      ▷ entropy_src_ip           : Shannon entropy over src_ip
      ▷ user_agent_distinct      : distinct UA count

  METRIC features (Detector 1 — RCF on numeric metric streams)
      grouped by (source, host, metric_name, window_start_iso)
      ▷ value_p50, p95, p99
      ▷ value_max
      ▷ delta_p50  (current p50 vs previous window)
      ▷ slope      (linear regression over the window)

Both shapes are deliberately small + numeric so they slot into RCF / IsolationForest
without one-hot encoding.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence


LOG_FEATURE_COLUMNS = (
    "request_count",
    "rate_4xx",
    "rate_5xx",
    "distinct_ips",
    "distinct_paths",
    "auth_failure_rate",
    "p99_latency_ms",
    "p50_latency_ms",
    "avg_bytes",
    "entropy_path",
    "entropy_src_ip",
    "user_agent_distinct",
)

METRIC_FEATURE_COLUMNS = (
    "value_p50",
    "value_p95",
    "value_p99",
    "value_max",
    "delta_p50",
    "slope",
)


# ───────────────────────────────────────────────────────────────────────────
def _percentile(xs: Sequence[float], q: float) -> float:
    if not xs:
        return 0.0
    if len(xs) == 1:
        return float(xs[0])
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo = math.floor(k); hi = math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def _entropy(values: Iterable) -> float:
    counts = Counter(values)
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts.values() if c)


def _slope(points: list[tuple[float, float]]) -> float:
    """OLS slope over (x, y) pairs."""
    n = len(points)
    if n < 2:
        return 0.0
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _parse_ts(s: str | datetime) -> datetime:
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ───────────────────────────────────────────────────────────────────────────
def bucket_events_by_window(
    events: Iterable[Mapping],
    window_seconds: int = 300,
) -> dict[tuple, list[Mapping]]:
    """Group events into (source, host, window_start) buckets."""
    buckets: dict[tuple, list[Mapping]] = defaultdict(list)
    for ev in events:
        try:
            ts = _parse_ts(ev["ts"])
        except (KeyError, ValueError):
            continue
        bucket_start = ts.replace(microsecond=0)
        bucket_start = bucket_start - timedelta(
            seconds=bucket_start.second % window_seconds + bucket_start.minute * 60 % window_seconds,
        )
        # Floor to nearest window
        epoch = int(ts.timestamp())
        floor = epoch - (epoch % window_seconds)
        bucket_start = datetime.fromtimestamp(floor, tz=timezone.utc)
        buckets[(ev.get("source", ""), ev.get("host") or "", bucket_start.isoformat())].append(ev)
    return buckets


# ───────────────────────────────────────────────────────────────────────────
_AUTH_PATH_HINTS = ("login", "auth", "signin", "logon", "token")


def compute_log_features_for_window(events: Sequence[Mapping]) -> dict:
    """Build the LOG feature dict for a single (source, host, window) bucket."""
    n = len(events)
    if not n:
        return {col: 0.0 for col in LOG_FEATURE_COLUMNS}

    statuses = [int(e["status"]) for e in events if isinstance(e.get("status"), int)]
    rate_4xx = sum(1 for s in statuses if 400 <= s < 500) / n
    rate_5xx = sum(1 for s in statuses if 500 <= s < 600) / n

    src_ips = [e.get("src_ip") for e in events if e.get("src_ip")]
    paths   = [e.get("path") or "" for e in events]
    uas     = [e.get("user_agent") for e in events if e.get("user_agent")]
    bytes_  = [e["bytes"] for e in events if isinstance(e.get("bytes"), (int, float))]
    lats    = [e["latency_ms"] for e in events if isinstance(e.get("latency_ms"), (int, float))]

    auth_failures = sum(
        1 for e in events
        if (e.get("severity") in ("ERROR", "WARN"))
        and any(h in (e.get("path") or "") for h in _AUTH_PATH_HINTS)
    )

    return {
        "request_count":       float(n),
        "rate_4xx":            float(rate_4xx),
        "rate_5xx":            float(rate_5xx),
        "distinct_ips":        float(len(set(src_ips))),
        "distinct_paths":      float(len(set(paths))),
        "auth_failure_rate":   float(auth_failures / n),
        "p99_latency_ms":      _percentile(lats, 0.99),
        "p50_latency_ms":      _percentile(lats, 0.50),
        "avg_bytes":           float(statistics.mean(bytes_)) if bytes_ else 0.0,
        "entropy_path":        _entropy(paths),
        "entropy_src_ip":      _entropy(src_ips),
        "user_agent_distinct": float(len(set(uas))),
    }


def compute_metric_features_for_window(samples: Sequence[Mapping], previous_p50: float | None = None) -> dict:
    """Build the METRIC feature dict for a single (source, host, metric, window) bucket.
    Each sample dict must have `attrs.value` and `ts`.
    """
    if not samples:
        return {col: 0.0 for col in METRIC_FEATURE_COLUMNS}

    values: list[float] = []
    points: list[tuple[float, float]] = []
    for s in samples:
        v = (s.get("attrs") or {}).get("value")
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        values.append(v)
        try:
            ts = _parse_ts(s["ts"])
            points.append((ts.timestamp(), v))
        except (KeyError, ValueError):
            pass

    p50 = _percentile(values, 0.5)
    return {
        "value_p50":  p50,
        "value_p95":  _percentile(values, 0.95),
        "value_p99":  _percentile(values, 0.99),
        "value_max":  float(max(values)) if values else 0.0,
        "delta_p50":  float(p50 - (previous_p50 or p50)),
        "slope":      _slope(points),
    }

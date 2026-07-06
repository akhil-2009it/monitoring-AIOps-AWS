"""Tests for security_features."""
from __future__ import annotations

from ml.feature_engineering.security_features import (
    LOG_FEATURE_COLUMNS,
    METRIC_FEATURE_COLUMNS,
    bucket_events_by_window,
    compute_log_features_for_window,
    compute_metric_features_for_window,
)


def _ev(ts, **kw):
    return {"ts": ts, "source": kw.pop("source", "alb"), "host": kw.pop("host", "h1"),
            "status": kw.pop("status", 200), **kw}


def test_compute_log_features_normal():
    events = [_ev(f"2024-01-02T10:00:{i:02d}Z", status=200, path="/x", src_ip=f"1.1.1.{i % 5}",
                  latency_ms=50 + i, bytes=1024) for i in range(20)]
    feats = compute_log_features_for_window(events)
    assert set(feats) == set(LOG_FEATURE_COLUMNS)
    assert feats["request_count"] == 20.0
    assert feats["rate_4xx"] == 0
    assert feats["rate_5xx"] == 0


def test_compute_log_features_attack_shape():
    events = [_ev(f"2024-01-02T10:00:{i:02d}Z", status=500, path="/login",
                  severity="ERROR", src_ip=f"1.1.1.{i}") for i in range(10)]
    feats = compute_log_features_for_window(events)
    assert feats["rate_5xx"] == 1.0
    assert feats["distinct_ips"] == 10.0
    assert feats["auth_failure_rate"] == 1.0


def test_metric_features():
    samples = [{"ts": f"2024-01-02T10:00:{i:02d}Z", "attrs": {"value": float(i)}} for i in range(10)]
    feats = compute_metric_features_for_window(samples, previous_p50=2.0)
    assert set(feats) == set(METRIC_FEATURE_COLUMNS)
    assert feats["value_max"] == 9.0
    assert feats["delta_p50"] != 0


def test_bucketing():
    events = [_ev(f"2024-01-02T10:0{m}:00Z") for m in range(8)]
    buckets = bucket_events_by_window(events, window_seconds=300)  # 5-min
    # 8 minutes spans 2 windows
    assert len(buckets) == 2

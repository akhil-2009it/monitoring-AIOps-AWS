"""Tests for the streaming statistical detector — cold-start ruleset."""
from __future__ import annotations

import time

from ml.streaming.detector import (
    DistinctCounterRule,
    EWMARule,
    RateOfChangeRule,
    StaticThresholdRule,
    StreamingDetector,
    ZScoreRule,
    default_detector,
)


def test_zscore_no_alert_on_stable_signal():
    rule = ZScoreRule(name="z", window_size=60, threshold=4.0)
    out = []
    for i in range(200):
        out.append(rule.update("k", 100.0 + (i % 3) * 0.1, time.time() + i))
    assert all(o is None for o in out)


def test_zscore_fires_on_outlier():
    rule = ZScoreRule(name="z", window_size=60, threshold=4.0)
    for i in range(200):
        rule.update("k", 100.0 + (i % 3) * 0.1, time.time() + i)
    a = rule.update("k", 1_000.0, time.time() + 1000)
    assert a is not None
    assert a.detector == "z"
    assert a.score >= 1.0


def test_ewma_fires_on_persistent_shift():
    rule = EWMARule(name="ewma", alpha=0.3, k_sigma=3.0)
    # Warm up with mild noise so sigma > 0
    import random
    rng = random.Random(42)
    for _ in range(60):
        rule.update("k", 1.0 + rng.uniform(-0.05, 0.05), time.time())
    # Sudden persistent shift
    a = None
    for _ in range(5):
        a = rule.update("k", 50.0, time.time())
        if a:
            break
    assert a is not None


def test_rate_of_change():
    rule = RateOfChangeRule(name="roc", threshold_pct=200.0)
    rule.update("k", 1.0, time.time())
    a = rule.update("k", 5.0, time.time())  # +400% jump
    assert a is not None


def test_static_threshold():
    rule = StaticThresholdRule(name="t", threshold=0.05, direction=">")
    assert rule.update("k", 0.04, time.time()) is None
    a = rule.update("k", 0.10, time.time())
    assert a is not None and a.score >= 1.0


def test_distinct_counter():
    rule = DistinctCounterRule(name="ddos", threshold=1000)
    assert rule.update("k", 500, time.time()) is None
    assert rule.update("k", 5000, time.time()) is not None


def test_default_detector_orchestrates_all_rules():
    det = default_detector()
    assert len(det.rules) == 5
    # No alert on a stable signal
    out = det.update("k", 100.0, time.time())
    assert isinstance(out, list)

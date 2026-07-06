"""
Streaming statistical detector — works from minute one (no model training).

Each Rule consumes a stream of `(metric_key, value, ts)` and emits Anomalies
when its check fires. Rules maintain bounded state per `metric_key`, so a
single detector instance can handle many parallel keys.

This module is the cold-start fallback. SageMaker ML detectors layer on top
once trained; their outputs go through the same Anomaly schema so the API
treats them uniformly.

Designed to run inside a Lambda triggered by Firehose / Kinesis. Pure
stdlib so the deployment package stays tiny.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence


@dataclass
class Anomaly:
    detector:    str        # rule name, e.g. "zscore-error_rate"
    metric_key:  str        # logical key, e.g. "alb:host-1:error_rate_5m"
    ts_seen:     float      # epoch seconds
    value:       float      # observed value
    baseline:    float      # mean / median / threshold
    score:       float      # severity (≥ 0; 1.0 = at threshold; > 3.0 = strong)
    explanation: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── Rule base ─────────────────────────────────────────────────────────────

@dataclass
class Rule:
    name: str

    def update(self, key: str, value: float, ts: float) -> Anomaly | None:
        raise NotImplementedError


# ── Z-score over a fixed sliding window ──────────────────────────────────
@dataclass
class ZScoreRule(Rule):
    window_size: int = 60          # samples
    threshold:   float = 4.0       # |z| above which we alert
    _buffers: dict[str, deque] = field(default_factory=dict)

    def update(self, key: str, value: float, ts: float) -> Anomaly | None:
        buf = self._buffers.setdefault(key, deque(maxlen=self.window_size))
        buf.append(value)
        if len(buf) < max(10, self.window_size // 6):
            return None
        mean = sum(buf) / len(buf)
        variance = sum((x - mean) ** 2 for x in buf) / max(len(buf) - 1, 1)
        std = math.sqrt(variance)
        if std == 0:
            return None
        z = (value - mean) / std
        if abs(z) >= self.threshold:
            return Anomaly(
                detector=self.name,
                metric_key=key,
                ts_seen=ts,
                value=value,
                baseline=mean,
                score=abs(z) / self.threshold,
                explanation=f"z={z:.2f} (mean={mean:.3f}, std={std:.3f}, threshold={self.threshold})",
            )
        return None


# ── EWMA + ±k σ band ──────────────────────────────────────────────────────
@dataclass
class EWMARule(Rule):
    alpha:     float = 0.3
    k_sigma:   float = 3.0
    _state: dict[str, dict] = field(default_factory=dict)

    def update(self, key: str, value: float, ts: float) -> Anomaly | None:
        st = self._state.setdefault(key, {"ewma": value, "evar": 0.0, "n": 0})
        # Score the *new* observation against the pre-update mean + variance
        # so a sudden shift fires on the first sample, not after the EWMA
        # has already absorbed it.
        prev_mean  = st["ewma"]
        prev_var   = st["evar"]
        st["n"] += 1
        st["ewma"] = self.alpha * value + (1 - self.alpha) * prev_mean
        st["evar"] = self.alpha * (value - prev_mean) ** 2 + (1 - self.alpha) * prev_var
        if st["n"] < 20:
            return None
        sigma = math.sqrt(prev_var)
        if sigma == 0:
            return None
        deviation = abs(value - prev_mean)
        if deviation > self.k_sigma * sigma:
            return Anomaly(
                detector=self.name,
                metric_key=key,
                ts_seen=ts,
                value=value,
                baseline=prev_mean,
                score=deviation / (self.k_sigma * sigma),
                explanation=f"EWMA deviation {deviation:.3f} > {self.k_sigma}σ (σ={sigma:.3f})",
            )
        return None


# ── Step rate-of-change ───────────────────────────────────────────────────
@dataclass
class RateOfChangeRule(Rule):
    threshold_pct: float = 200.0  # +200% jump
    _last: dict[str, float] = field(default_factory=dict)

    def update(self, key: str, value: float, ts: float) -> Anomaly | None:
        prev = self._last.get(key)
        self._last[key] = value
        if prev is None or prev == 0:
            return None
        pct = ((value - prev) / abs(prev)) * 100
        if pct >= self.threshold_pct:
            return Anomaly(
                detector=self.name,
                metric_key=key,
                ts_seen=ts,
                value=value,
                baseline=prev,
                score=pct / self.threshold_pct,
                explanation=f"+{pct:.0f}% over previous window (was {prev:.3f})",
            )
        return None


# ── Static threshold (e.g. error_rate > 5%) ──────────────────────────────
@dataclass
class StaticThresholdRule(Rule):
    threshold: float = 0.05
    direction: str   = ">"  # ">" or "<"

    def update(self, key: str, value: float, ts: float) -> Anomaly | None:
        breach = (value > self.threshold) if self.direction == ">" else (value < self.threshold)
        if not breach:
            return None
        return Anomaly(
            detector=self.name,
            metric_key=key,
            ts_seen=ts,
            value=value,
            baseline=self.threshold,
            score=abs(value - self.threshold) / max(abs(self.threshold), 1e-9),
            explanation=f"{value:.3f} {self.direction} threshold {self.threshold:.3f}",
        )


# ── Distinct-counter (e.g. distinct_src_ips > 10000 / minute = DDoS) ─────
@dataclass
class DistinctCounterRule(Rule):
    threshold: int = 10_000

    def update(self, key: str, value: float, ts: float) -> Anomaly | None:
        if value <= self.threshold:
            return None
        return Anomaly(
            detector=self.name,
            metric_key=key,
            ts_seen=ts,
            value=value,
            baseline=self.threshold,
            score=value / self.threshold,
            explanation=f"distinct count {value:.0f} > threshold {self.threshold}",
        )


# ── Detector orchestrator ─────────────────────────────────────────────────
class StreamingDetector:
    """Holds many rules. update() returns all anomalies for a single sample."""

    def __init__(self, rules: Sequence[Rule]) -> None:
        self._rules = list(rules)

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(self._rules)

    def update(self, key: str, value: float, ts: float | None = None) -> list[Anomaly]:
        ts = ts if ts is not None else time.time()
        out: list[Anomaly] = []
        for rule in self._rules:
            try:
                a = rule.update(key, value, ts)
            except Exception:  # noqa: BLE001
                a = None
            if a is not None:
                out.append(a)
        return out

    def feed(self, samples: Iterable[tuple[str, float, float]]) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        for key, value, ts in samples:
            anomalies.extend(self.update(key, value, ts))
        return anomalies


# ── Reasonable defaults for the AIOps platform ────────────────────────────
def default_detector() -> StreamingDetector:
    return StreamingDetector([
        ZScoreRule(name="zscore", window_size=60, threshold=4.0),
        EWMARule(name="ewma", alpha=0.3, k_sigma=3.0),
        RateOfChangeRule(name="rate-of-change", threshold_pct=200.0),
        StaticThresholdRule(name="error-rate-static", threshold=0.05, direction=">"),
        DistinctCounterRule(name="ddos-distinct-ips", threshold=10_000),
    ])

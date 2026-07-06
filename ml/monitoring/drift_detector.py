"""
Drift detection: PSI + KL divergence + missing-rate vs the saved baseline.

Pure numpy/pandas — no ML framework dependency, so it runs anywhere
(Lambda, EKS sidecar, SageMaker Processing).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass
class DriftReport:
    feature: str
    psi: float
    kl_divergence: float
    missing_rate: float
    out_of_bounds_pct: float
    severity: str    # ok | warn | alert

    def to_dict(self) -> dict:
        return self.__dict__


def _safe_log(x: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    return np.log(np.clip(x, eps, None))


def psi(reference_hist: dict, current_values: np.ndarray) -> float:
    """Population Stability Index across the reference histogram bins."""
    edges = np.asarray(reference_hist["edges"])
    if edges.size == 0:
        return 0.0
    ref_counts = np.asarray(reference_hist["counts"], dtype=float)
    cur_counts, _ = np.histogram(current_values[np.isfinite(current_values)], bins=edges)
    cur_counts = cur_counts.astype(float)

    # Normalize, with smoothing.
    ref_p = (ref_counts + 1e-6) / (ref_counts.sum() + 1e-6 * len(ref_counts))
    cur_p = (cur_counts + 1e-6) / (cur_counts.sum() + 1e-6 * len(cur_counts))

    return float(np.sum((cur_p - ref_p) * (_safe_log(cur_p) - _safe_log(ref_p))))


def kl_divergence(reference_hist: dict, current_values: np.ndarray) -> float:
    """KL(current || reference) — sensitive to mode collapse."""
    edges = np.asarray(reference_hist["edges"])
    if edges.size == 0:
        return 0.0
    ref_counts = np.asarray(reference_hist["counts"], dtype=float)
    cur_counts, _ = np.histogram(current_values[np.isfinite(current_values)], bins=edges)
    cur_counts = cur_counts.astype(float)

    p = (cur_counts + 1e-6) / (cur_counts.sum() + 1e-6 * len(cur_counts))
    q = (ref_counts + 1e-6) / (ref_counts.sum() + 1e-6 * len(ref_counts))
    return float(np.sum(p * (_safe_log(p) - _safe_log(q))))


def severity(psi_value: float, psi_warn: float, psi_alert: float) -> str:
    if psi_value >= psi_alert:
        return "alert"
    if psi_value >= psi_warn:
        return "warn"
    return "ok"


def evaluate_drift(
    baseline_path: Path,
    current_df: pd.DataFrame,
    psi_warn: float = 0.10,
    psi_alert: float = 0.20,
) -> list[DriftReport]:
    """Run drift checks for every numeric feature present in both baseline and current."""
    stats = json.loads((baseline_path / "statistics.json").read_text())
    constraints = json.loads((baseline_path / "constraints.json").read_text())

    reports: list[DriftReport] = []
    for feature, feat_stats in stats.items():
        if feature not in current_df.columns:
            continue
        col = current_df[feature].astype(float)
        arr = col.to_numpy()
        finite = arr[np.isfinite(arr)]

        feature_psi = psi(feat_stats["histogram"], finite)
        feature_kl  = kl_divergence(feat_stats["histogram"], finite)
        missing     = float(col.isna().mean())

        bounds = constraints.get(feature, {})
        oob_pct = 0.0
        if "min" in bounds and "max" in bounds and finite.size:
            oob_pct = float(((finite < bounds["min"]) | (finite > bounds["max"])).mean())

        reports.append(DriftReport(
            feature=feature,
            psi=feature_psi,
            kl_divergence=feature_kl,
            missing_rate=missing,
            out_of_bounds_pct=oob_pct,
            severity=severity(feature_psi, psi_warn, psi_alert),
        ))
    return reports


def emit_cloudwatch(
    reports: Iterable[DriftReport],
    namespace: str,
    model_name: str,
    environment: str,
) -> None:
    """Push per-feature PSI to CloudWatch under the given namespace."""
    import boto3

    cw = boto3.client("cloudwatch")
    metrics = []
    for r in reports:
        metrics.append({
            "MetricName": "PSI",
            "Dimensions": [
                {"Name": "Model",       "Value": model_name},
                {"Name": "Environment", "Value": environment},
                {"Name": "Feature",     "Value": r.feature},
            ],
            "Value": r.psi,
            "Unit":  "None",
        })
    # CloudWatch limit: 20 metrics per put_metric_data
    for batch_start in range(0, len(metrics), 20):
        cw.put_metric_data(Namespace=namespace, MetricData=metrics[batch_start:batch_start + 20])

"""
Compute the Model Monitor baseline statistics from a reference dataset.

Builds:
  - statistics.json   : per-feature mean / std / min / max / quantiles / histograms
  - constraints.json  : tolerance bounds (auto = mean ± k*std for numerics, value enum for categoricals)

Usage:
    python -m ml.monitoring.baseline \\
        --reference-parquet s3://.../features/baseline.parquet \\
        --output-dir artifacts/baselines/perf-predictor/
        --bins 20 --tolerance-sigma 3
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def compute_histogram(values: np.ndarray, bins: int) -> dict:
    """A simple equal-width histogram representation we'll re-use in PSI."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"edges": [], "counts": []}
    lo, hi = float(finite.min()), float(finite.max())
    if hi == lo:
        hi = lo + 1e-9
    edges = np.linspace(lo, hi, bins + 1)
    counts, _ = np.histogram(finite, bins=edges)
    return {"edges": edges.tolist(), "counts": counts.astype(int).tolist()}


def baseline_statistics(df: pd.DataFrame, bins: int) -> dict:
    out = {}
    for col in df.select_dtypes(include="number").columns:
        s = df[col]
        arr = s.dropna().to_numpy()
        if arr.size == 0:
            continue
        out[col] = {
            "count":       int(s.size),
            "missing":     int(s.isna().sum()),
            "mean":        float(np.nanmean(arr)),
            "std":         float(np.nanstd(arr)) or 1e-9,
            "min":         float(np.nanmin(arr)),
            "max":         float(np.nanmax(arr)),
            "p01":         float(np.nanpercentile(arr, 1)),
            "p25":         float(np.nanpercentile(arr, 25)),
            "p50":         float(np.nanpercentile(arr, 50)),
            "p75":         float(np.nanpercentile(arr, 75)),
            "p99":         float(np.nanpercentile(arr, 99)),
            "histogram":   compute_histogram(arr, bins),
        }
    return out


def constraints_from_baseline(stats: dict, tolerance_sigma: float) -> dict:
    out = {}
    for col, s in stats.items():
        out[col] = {
            "min": s["mean"] - tolerance_sigma * s["std"],
            "max": s["mean"] + tolerance_sigma * s["std"],
            "max_missing_rate": 0.05,
        }
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reference-parquet", required=True, help="Path to a Parquet file with feature rows.")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--bins", type=int, default=20)
    p.add_argument("--tolerance-sigma", type=float, default=3.0)
    args = p.parse_args()

    df = pd.read_parquet(args.reference_parquet)
    if df.empty:
        sys.exit(f"Reference dataset {args.reference_parquet} is empty.")

    stats = baseline_statistics(df, args.bins)
    constraints = constraints_from_baseline(stats, args.tolerance_sigma)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "statistics.json").write_text(json.dumps(stats, indent=2))
    (args.output_dir / "constraints.json").write_text(json.dumps(constraints, indent=2))
    print(f"Wrote baseline to {args.output_dir}")


if __name__ == "__main__":
    main()

"""sklearn IsolationForest entrypoint."""
from __future__ import annotations
import argparse, os
from pathlib import Path
import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n-estimators", type=int, default=200)
    p.add_argument("--contamination", type=float, default=0.01)
    p.add_argument("--max-samples", default="auto")
    args = p.parse_args()

    train_dir = Path(os.environ["SM_CHANNEL_TRAIN"])
    df = pd.read_csv(next(train_dir.rglob("*.csv")), header=None)
    X = df.values

    clf = IsolationForest(
        n_estimators=args.n_estimators,
        contamination=args.contamination,
        max_samples=args.max_samples if args.max_samples == "auto" else int(args.max_samples),
        random_state=42, n_jobs=-1,
    )
    clf.fit(X)
    out = Path(os.environ["SM_MODEL_DIR"])
    joblib.dump(clf, out / "model.joblib")
    print(f"Saved Isolation Forest to {out}/model.joblib")

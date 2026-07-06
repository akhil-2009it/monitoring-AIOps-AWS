"""TF-IDF char-ngram + IsolationForest fit on raw log lines."""
from __future__ import annotations
import argparse, os
from pathlib import Path
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ngram-min", type=int, default=2)
    p.add_argument("--ngram-max", type=int, default=4)
    p.add_argument("--max-features", type=int, default=10_000)
    p.add_argument("--contamination", type=float, default=0.01)
    args = p.parse_args()

    train_dir = Path(os.environ["SM_CHANNEL_TRAIN"])
    lines = (train_dir / "lines.txt").read_text().splitlines()

    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(args.ngram_min, args.ngram_max),
            max_features=args.max_features,
            sublinear_tf=True,
        )),
        ("if", IsolationForest(
            n_estimators=200,
            contamination=args.contamination,
            n_jobs=-1, random_state=42,
        )),
    ])
    pipe.fit(lines)

    out = Path(os.environ["SM_MODEL_DIR"])
    joblib.dump(pipe, out / "model.joblib")
    print(f"Saved log-embedding model to {out}/model.joblib")

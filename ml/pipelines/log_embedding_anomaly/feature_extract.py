"""Extract one log line per row → text file (consumed by TfidfVectorizer)."""
from __future__ import annotations
import json, os, sys
from pathlib import Path

INPUT = Path(os.getenv("PROCESSING_INPUT", "/opt/ml/processing/input"))
TRAIN = Path(os.getenv("PROCESSING_TRAIN", "/opt/ml/processing/train")); TRAIN.mkdir(parents=True, exist_ok=True)
TEST  = Path(os.getenv("PROCESSING_TEST",  "/opt/ml/processing/test"));  TEST.mkdir(parents=True, exist_ok=True)
SEED  = int(os.getenv("SEED", "42"))
import random


def load(path):
    rows = []
    for f in sorted(path.rglob("*")):
        if f.suffix.lower() in (".jsonl", ".json"):
            for line in f.read_text().splitlines():
                if line.strip():
                    try:
                        rec = json.loads(line)
                        msg = (rec.get("message") or "").strip()
                        if msg:
                            rows.append(msg)
                    except ValueError:
                        continue
    return rows


def main():
    rows = load(INPUT)
    if len(rows) < 200:
        print(f"Only {len(rows)} log lines — need ≥ 200", file=sys.stderr); sys.exit(2)
    random.Random(SEED).shuffle(rows)
    n_test = max(50, int(len(rows)*0.20))
    test, train = rows[:n_test], rows[n_test:]
    (TRAIN / "lines.txt").write_text("\n".join(train))
    (TEST  / "lines.txt").write_text("\n".join(test))
    print(f"train={len(train)} test={len(test)}")


if __name__ == "__main__":
    main()

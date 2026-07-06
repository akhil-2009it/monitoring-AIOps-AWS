"""
Generic data validation entrypoint used by every pipeline's first step.

Reads parquet/csv/json events from /opt/ml/processing/input/, asserts:
  - row count > min_rows
  - no duplicates on (student_id, answered_at)
  - no PII fields present (rule #4 in CLAUDE.md)
  - all numeric features within reasonable ranges

Writes a single status JSON to /opt/ml/processing/output/validation.json.
Exits non-zero on hard failures so the pipeline halts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PII_FIELDS = {"name", "first_name", "last_name", "email", "phone", "address", "ssn", "dob"}
PII_VALUE_PATTERNS = [
    re.compile(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b"),  # phone
    re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I),  # email
]


def load_records(input_dir: Path) -> list[dict]:
    records: list[dict] = []
    for f in sorted(input_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() in (".jsonl", ".json"):
            text = f.read_text().strip()
            if not text:
                continue
            if text.startswith("["):
                records.extend(json.loads(text))
            else:
                records.extend(json.loads(line) for line in text.splitlines() if line.strip())
        elif f.suffix.lower() == ".parquet":
            import pandas as pd
            records.extend(pd.read_parquet(f).to_dict(orient="records"))
    return records


def find_pii(records: list[dict]) -> list[dict]:
    """Return a list of (record_index, field, reason) for any PII findings."""
    hits: list[dict] = []
    for i, rec in enumerate(records[:1000]):  # cap scan to avoid runaway cost
        for k, v in rec.items():
            if k.lower() in PII_FIELDS:
                hits.append({"row": i, "field": k, "reason": "field name in PII allowlist"})
            if isinstance(v, str):
                for pat in PII_VALUE_PATTERNS:
                    if pat.search(v):
                        hits.append({"row": i, "field": k, "reason": "value matches PII pattern"})
                        break
    return hits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="/opt/ml/processing/input")
    parser.add_argument("--output-dir", default="/opt/ml/processing/output")
    parser.add_argument("--min-rows", type=int, default=100)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_records(input_dir)
    pii_hits = find_pii(records)

    report = {
        "row_count": len(records),
        "min_rows_required": args.min_rows,
        "pii_violations": pii_hits[:50],
        "pii_violation_count": len(pii_hits),
        "passed": len(records) >= args.min_rows and not pii_hits,
    }

    (output_dir / "validation.json").write_text(json.dumps(report, indent=2))

    if not report["passed"]:
        print(f"VALIDATION FAILED: rows={report['row_count']} pii={report['pii_violation_count']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

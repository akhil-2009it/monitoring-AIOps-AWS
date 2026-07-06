"""Group OTEL spans by trace_id → variable-length sequence of (service_id, op_id, dur_ms, status)."""
from __future__ import annotations
import json, os, sys
from collections import defaultdict
from pathlib import Path

INPUT    = Path(os.getenv("PROCESSING_INPUT",   "/opt/ml/processing/input"))
TRAIN    = Path(os.getenv("PROCESSING_TRAIN",   "/opt/ml/processing/train")); TRAIN.mkdir(parents=True, exist_ok=True)
TEST     = Path(os.getenv("PROCESSING_TEST",    "/opt/ml/processing/test"));  TEST.mkdir(parents=True, exist_ok=True)
METADATA = Path(os.getenv("PROCESSING_META",    "/opt/ml/processing/metadata")); METADATA.mkdir(parents=True, exist_ok=True)
MAX_SEQ  = int(os.getenv("MAX_SEQ_LEN", "64"))


def load(path):
    rows = []
    for f in sorted(path.rglob("*")):
        if f.suffix.lower() == ".jsonl":
            for line in f.read_text().splitlines():
                if line.strip(): rows.append(json.loads(line))
    return rows


def main():
    events = load(INPUT)
    if not events:
        print("No data", file=sys.stderr); sys.exit(2)

    services, ops = set(), set()
    by_trace = defaultdict(list)
    for ev in events:
        attrs = ev.get("attrs") or {}
        tid = attrs.get("trace_id")
        if not tid: continue
        svc = attrs.get("service.name") or "unknown"
        op  = attrs.get("name") or "unknown"
        services.add(svc); ops.add(op)
        by_trace[tid].append({
            "service":  svc,
            "op":       op,
            "dur_ms":   float(ev.get("latency_ms") or 0),
            "status":   int(attrs.get("status_code") or 0),
            "ts":       ev.get("ts", ""),
        })

    svc_to_id = {s: i for i, s in enumerate(sorted(services))}
    op_to_id  = {o: i for i, o in enumerate(sorted(ops))}

    seqs = []
    for tid, spans in by_trace.items():
        spans.sort(key=lambda s: s["ts"])
        seq = [(svc_to_id[s["service"]], op_to_id[s["op"]], s["dur_ms"], s["status"]) for s in spans[:MAX_SEQ]]
        if len(seq) >= 3:
            seqs.append({"trace_id": tid, "spans": seq})

    if len(seqs) < 50:
        print(f"Only {len(seqs)} traces — need ≥ 50", file=sys.stderr); sys.exit(2)

    n_test = max(10, int(len(seqs) * 0.15))
    test, train = seqs[:n_test], seqs[n_test:]

    with (TRAIN / "sequences.jsonl").open("w") as f:
        for s in train: f.write(json.dumps(s) + "\n")
    with (TEST / "sequences.jsonl").open("w") as f:
        for s in test: f.write(json.dumps(s) + "\n")

    (METADATA / "vocab.json").write_text(json.dumps({
        "num_services": len(services), "num_ops": len(ops),
        "svc_to_id": svc_to_id, "op_to_id": op_to_id,
        "max_seq_len": MAX_SEQ,
    }, indent=2))
    print(f"train={len(train)} test={len(test)} services={len(services)} ops={len(ops)}")


if __name__ == "__main__":
    main()

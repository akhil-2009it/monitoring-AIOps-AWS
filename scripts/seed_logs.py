#!/usr/bin/env python3
"""Generate synthetic logs across all 14 sources for local model training.

  python scripts/seed_logs.py --num-events 100000 --output data/events.jsonl --seed 42

The output JSONL is the same CommonEvent schema produced by ml/parsers/.
This is the single dataset all four detectors train against in dev.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SOURCES = [
    "cloudfront", "alb", "waf", "app", "eks", "nginx",
    "kafka", "mysql", "mongodb", "redis",
    "node-metrics", "container-metrics", "prometheus", "otel-traces",
]

PATHS  = ["/api/v1/users", "/api/v1/orders", "/api/v1/login", "/api/v1/health",
          "/static/main.js", "/api/v1/admin", "/api/v1/products", "/api/v1/cart"]
HOSTS  = [f"node-{i:02d}" for i in range(1, 11)]
PODS   = [f"app-{n}-{i:02d}" for n in ("api", "worker", "billing") for i in range(1, 4)]
UAS    = ["Mozilla/5.0 (X11; Linux x86_64)", "curl/7.81", "PostmanRuntime/7.32",
          "AWS-SDK-Java/1.12", "Mozilla/5.0 (Macintosh; Intel Mac OS X)"]
METRICS = ["cpu_util", "mem_used_bytes", "request_rate", "p99_latency_ms",
           "disk_io_bytes", "net_rx_bytes"]


def _ts(rng, base):
    return (base + timedelta(seconds=rng.randint(0, 14*24*3600))).isoformat().replace("+00:00", "Z")


def gen_alb(rng, base):
    status = rng.choices([200, 200, 200, 301, 400, 401, 404, 500, 502], k=1)[0]
    return {
        "ts": _ts(rng, base), "source": "alb",
        "host": rng.choice(HOSTS), "severity": "ERROR" if status >= 500 else None,
        "status": status, "latency_ms": rng.gauss(120, 60),
        "bytes": rng.randint(200, 50_000),
        "src_ip": f"203.0.{rng.randint(0,254)}.{rng.randint(0,254)}",
        "path": rng.choice(PATHS), "user_agent": rng.choice(UAS),
        "message": f"GET {rng.choice(PATHS)} -> {status}", "attrs": {},
    }


def gen_cloudfront(rng, base):
    status = rng.choices([200, 200, 304, 403, 404, 500], k=1)[0]
    return {**gen_alb(rng, base), "source": "cloudfront", "status": status,
            "host": "MAA50-P1", "attrs": {"edge_result_type": "Hit" if status == 200 else "Miss"}}


def gen_waf(rng, base):
    action = rng.choices(["ALLOW", "ALLOW", "ALLOW", "BLOCK", "COUNT", "CHALLENGE"], k=1)[0]
    return {
        "ts": _ts(rng, base), "source": "waf",
        "host": "webacl-main",
        "severity": "ERROR" if action == "BLOCK" else None,
        "src_ip": f"198.51.{rng.randint(0,254)}.{rng.randint(0,254)}",
        "path": rng.choice(PATHS), "user_agent": rng.choice(UAS),
        "message": f"{action} {rng.choice(PATHS)}",
        "attrs": {"action": action, "country": rng.choice(["US", "IN", "CN", "BR", "DE"])},
    }


def gen_app(rng, base):
    level = rng.choices(["INFO","INFO","INFO","DEBUG","WARN","ERROR"], k=1)[0]
    status = rng.choice([200, 200, 401, 500])
    return {
        "ts": _ts(rng, base), "source": "app",
        "host": rng.choice(PODS), "severity": level, "status": status,
        "latency_ms": rng.gauss(80, 40),
        "user": f"user-{rng.randint(1,1000)}", "path": rng.choice(PATHS),
        "message": rng.choice([
            "Order processed successfully", "Login attempt", "Cache hit",
            "Failed authentication for user", "Database query timeout", "Internal error",
        ]),
        "attrs": {"trace_id": uuid.uuid4().hex},
    }


def gen_eks(rng, base):
    verb = rng.choice(["get","list","create","update","delete","watch"])
    return {
        "ts": _ts(rng, base), "source": "eks",
        "host": uuid.uuid4().hex, "severity": "INFO",
        "user": f"system:serviceaccount:default:{rng.choice(['app','worker','admin'])}",
        "src_ip": f"10.0.{rng.randint(0,254)}.{rng.randint(0,254)}",
        "path": f"core/{rng.choice(['pods','services','configmaps'])}/{rng.randint(1,9999)}",
        "message": f"{verb} {rng.choice(['pods','services'])}",
        "attrs": {"verb": verb, "namespace": rng.choice(["default","api","monitoring"])},
    }


def gen_nginx(rng, base):
    base_event = gen_alb(rng, base)
    base_event["source"] = "nginx"
    return base_event


def gen_kafka(rng, base):
    level = rng.choices(["INFO","INFO","DEBUG","WARN","ERROR"], k=1)[0]
    return {
        "ts": _ts(rng, base), "source": "kafka",
        "severity": level,
        "message": rng.choice([
            "Started replica fetcher",
            "Closing socket connection to /10.0.0.5",
            "Replication factor below configured value",
            "Failed to send producer request",
        ]),
        "attrs": {"logger": rng.choice(["kafka.server","kafka.controller","kafka.network"])},
    }


def gen_mysql(rng, base):
    qt = abs(rng.gauss(0.3, 0.5))
    return {
        "ts": _ts(rng, base), "source": "mysql",
        "severity": "WARN" if qt > 1 else "INFO",
        "latency_ms": qt * 1000,
        "src_ip": f"10.0.{rng.randint(0,254)}.{rng.randint(0,254)}",
        "user": rng.choice(["app","analytics","backup"]),
        "message": "SELECT * FROM orders WHERE created_at > NOW() - INTERVAL 1 DAY",
        "attrs": {"lock_time": rng.uniform(0, 0.05)},
    }


def gen_mongodb(rng, base):
    return {
        "ts": _ts(rng, base), "source": "mongodb",
        "host": rng.choice(HOSTS),
        "severity": rng.choices(["INFO","INFO","WARN","ERROR"], k=1)[0],
        "message": rng.choice([
            "Connection accepted",
            "Slow query (200ms): db.users.find()",
            "Replica set heartbeat failed",
            "Cursor not found",
        ]),
        "attrs": {"component": rng.choice(["NETWORK","REPL","STORAGE"])},
    }


def gen_redis(rng, base):
    return {
        "ts": _ts(rng, base), "source": "redis",
        "severity": "INFO",
        "message": rng.choice([
            "Background saving terminated with success",
            "DB loaded from disk: 0.123 seconds",
            "Slow query: HGETALL took 50ms",
        ]),
        "attrs": {"role": rng.choice(["M","S"])},
    }


def gen_metric(rng, base, source):
    metric = rng.choice(METRICS)
    base_val = {"cpu_util": 0.4, "mem_used_bytes": 5e8, "request_rate": 200,
                "p99_latency_ms": 80, "disk_io_bytes": 1e6, "net_rx_bytes": 5e6}[metric]
    return {
        "ts": _ts(rng, base), "source": source,
        "host": rng.choice(HOSTS),
        "message": f"{metric}=...",
        "attrs": {"metric": metric, "value": float(rng.gauss(base_val, base_val * 0.2)),
                  "instance": rng.choice(HOSTS)},
    }


def gen_otel(rng, base):
    dur_ms = abs(rng.gauss(60, 40))
    status = rng.choices([1, 1, 1, 2], k=1)[0]
    return {
        "ts": _ts(rng, base), "source": "otel-traces",
        "host": rng.choice(PODS),
        "severity": "ERROR" if status == 2 else "INFO",
        "latency_ms": dur_ms,
        "message": f"{rng.choice(['HTTP GET /api','SQL SELECT','HTTP POST /orders'])} ({dur_ms:.0f}ms)",
        "attrs": {
            "trace_id": uuid.uuid4().hex, "span_id": uuid.uuid4().hex[:16],
            "service.name": rng.choice(["api","worker","billing"]),
            "name": rng.choice(["GET /api/users","db.query","kafka.produce"]),
            "status_code": status,
            "http.status_code": rng.choice([200, 200, 404, 500]),
        },
    }


GENERATORS = {
    "cloudfront": gen_cloudfront, "alb": gen_alb, "waf": gen_waf,
    "app": gen_app, "eks": gen_eks, "nginx": gen_nginx,
    "kafka": gen_kafka, "mysql": gen_mysql, "mongodb": gen_mongodb, "redis": gen_redis,
    "node-metrics":      lambda r, b: gen_metric(r, b, "node-metrics"),
    "container-metrics": lambda r, b: gen_metric(r, b, "container-metrics"),
    "prometheus":        lambda r, b: gen_metric(r, b, "prometheus"),
    "otel-traces":       gen_otel,
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--num-events", type=int, default=10_000)
    p.add_argument("--output", type=Path, default=REPO_ROOT / "data" / "events.jsonl")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    rng = random.Random(args.seed)
    base = datetime.now(timezone.utc) - timedelta(days=14)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts = {s: 0 for s in SOURCES}
    with args.output.open("w") as f:
        for _ in range(args.num_events):
            src = rng.choice(SOURCES)
            ev = GENERATORS[src](rng, base)
            ev.setdefault("ingest_ts", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
            f.write(json.dumps(ev) + "\n")
            counts[src] += 1

    print(f"Wrote {args.num_events} events -> {args.output}")
    for s, c in counts.items():
        print(f"  {s:>20s}: {c}")


if __name__ == "__main__":
    main()

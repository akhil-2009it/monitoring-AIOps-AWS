"""Inject simulated attacks into the event stream / Kinesis Firehose to validate detection.

Patterns:
  - ddos:        burst of high-rate requests from many src_ips
  - brute-force: thousands of failed logins from a small IP set
  - slow-loris:  long-latency requests holding connections
  - sql-injection: WAF events with `' OR 1=1` in path

Usage:
    python scripts/inject_attack.py --pattern ddos --duration-min 5
    python scripts/inject_attack.py --pattern brute-force --output data/attacks.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _alb_evt(**kwargs):
    base = {
        "ts": _now_iso(), "source": "alb", "host": "alb-1",
        "status": 200, "latency_ms": 100, "bytes": 1024,
        "user_agent": "Mozilla/5.0", "attrs": {},
    }
    base.update(kwargs)
    return base


def gen_ddos(rng, rate, duration_sec):
    end = time.time() + duration_sec
    while time.time() < end:
        for _ in range(rate):
            ip = f"203.0.{rng.randint(0,254)}.{rng.randint(0,254)}"
            yield _alb_evt(
                src_ip=ip, path="/api/v1/health",
                latency_ms=rng.uniform(5, 20), status=200,
                attrs={"injected_attack": "ddos"},
            )
        time.sleep(1)


def gen_brute_force(rng, rate, duration_sec):
    end = time.time() + duration_sec
    attacker_ips = [f"198.51.100.{i}" for i in range(1, 6)]
    for _ in range(int(duration_sec * rate)):
        yield _alb_evt(
            source="app",
            severity="WARN",
            host=f"api-{rng.randint(1,3):02d}",
            src_ip=rng.choice(attacker_ips),
            path="/api/v1/login",
            status=401,
            user=f"victim_{rng.randint(1,100)}",
            message="Failed authentication for user",
            attrs={"injected_attack": "brute-force"},
        )


def gen_slow_loris(rng, rate, duration_sec):
    for _ in range(int(duration_sec * rate)):
        yield _alb_evt(
            src_ip=f"203.0.113.{rng.randint(1,30)}",
            path=rng.choice(["/api/v1/upload", "/api/v1/long-poll"]),
            latency_ms=rng.uniform(30_000, 60_000),
            status=200,
            attrs={"injected_attack": "slow-loris"},
        )


def gen_sqli(rng, rate, duration_sec):
    payloads = ["' OR 1=1--", "1; DROP TABLE users--", "%27%20UNION%20SELECT", "<script>alert(1)</script>"]
    for _ in range(int(duration_sec * rate)):
        yield {
            "ts": _now_iso(),
            "source": "waf",
            "host": "webacl-main",
            "severity": "ERROR",
            "src_ip": f"198.51.100.{rng.randint(1,30)}",
            "path": f"/api/v1/users?q={rng.choice(payloads)}",
            "user_agent": "sqlmap/1.7",
            "message": "BLOCK SQLi",
            "attrs": {"action": "BLOCK", "injected_attack": "sql-injection"},
        }


PATTERNS = {
    "ddos":          gen_ddos,
    "brute-force":   gen_brute_force,
    "slow-loris":    gen_slow_loris,
    "sql-injection": gen_sqli,
}


def to_kinesis(events, stream, region, batch=500):
    import boto3
    client = boto3.client("kinesis", region_name=region)
    buf = []
    for e in events:
        buf.append(e)
        if len(buf) >= batch:
            client.put_records(StreamName=stream, Records=[
                {"Data": json.dumps(b).encode(), "PartitionKey": b.get("src_ip", "k")} for b in buf
            ])
            buf = []
    if buf:
        client.put_records(StreamName=stream, Records=[
            {"Data": json.dumps(b).encode(), "PartitionKey": b.get("src_ip", "k")} for b in buf
        ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pattern", required=True, choices=list(PATTERNS))
    p.add_argument("--duration-min", type=int, default=5)
    p.add_argument("--rate", type=int, default=50, help="events / second")
    p.add_argument("--seed", type=int, default=2025)
    p.add_argument("--stream", default="")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--region", default="ap-south-1")
    args = p.parse_args()

    rng = random.Random(args.seed)
    duration = args.duration_min * 60
    print(f"Injecting {args.pattern} for {duration}s @ {args.rate}/s")

    events = PATTERNS[args.pattern](rng, args.rate, duration)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("a") as f:
            n = 0
            for e in events:
                f.write(json.dumps(e) + "\n")
                n += 1
            print(f"Wrote {n} events to {args.output}")
    elif args.stream:
        to_kinesis(events, args.stream, args.region)
        print("Pushed to Kinesis. Watch CloudWatch for streaming-detector anomalies.")
    else:
        for e in events:
            print(json.dumps(e))


if __name__ == "__main__":
    main()

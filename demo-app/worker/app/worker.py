"""Background worker — pulls jobs off Redis, processes them.

Why this exists in the demo: a worker generates a *different* shape of
log/metric stream than an HTTP API does. Specifically:
  - Latency distribution looks more like batch processing (skewed long tail)
  - Per-job structured log rows
  - Queue depth as a Prometheus Gauge (rare in HTTP services)

Instrumentation:
  - Structured JSON logs to stdout (Fluent Bit captures them)
  - OTEL spans per job (so traces show fan-out from API → queue → worker)
  - Prometheus metrics on /metrics (port 8080 by default)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import socket
import sys
import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)


# ── Structured logging ─────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
            "service": os.getenv("SERVICE_NAME", "demo-worker"),
            "host":    socket.gethostname(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))


# ── Prometheus metrics ─────────────────────────────────────────────────────

JOBS_PROCESSED = Counter("demo_worker_jobs_total", "Jobs processed", ["job_type", "status"])
JOB_LATENCY = Histogram(
    "demo_worker_job_latency_seconds", "Job processing latency",
    ["job_type"], buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
)
QUEUE_DEPTH = Gauge("demo_worker_queue_depth", "Approximate queue depth", ["queue"])
WORKER_INFLIGHT = Gauge("demo_worker_inflight", "Inflight jobs")


# ── OTEL setup ──────────────────────────────────────────────────────────────

def setup_otel():
    otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otlp:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({
            "service.name": os.getenv("SERVICE_NAME", "demo-worker"),
            "service.namespace": "demo",
        }))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp)))
        trace.set_tracer_provider(provider)
        RedisInstrumentor().instrument()
        return trace.get_tracer("demo-worker")
    except ImportError:
        return None


# ── Job processing ─────────────────────────────────────────────────────────

JOB_TYPES = ["resize_image", "send_email", "compute_recommendation", "index_document"]
QUEUE_KEY = os.getenv("QUEUE_KEY", "jobs:demo")
ERROR_RATE = float(os.getenv("DEMO_ERROR_RATE", "0.05"))


async def process_job(job: dict, tracer=None) -> bool:
    job_type = job.get("type", "unknown")
    job_id = job.get("id", "?")

    base_latency = {
        "resize_image":           random.uniform(0.5, 2.0),
        "send_email":             random.uniform(0.1, 0.4),
        "compute_recommendation": random.uniform(1.0, 4.0),
        "index_document":         random.uniform(0.2, 0.8),
    }.get(job_type, 1.0)

    # Realism — long tail of unusually slow jobs (some jobs hit a stale cache).
    if random.random() < 0.03:
        base_latency *= 8

    span_ctx = tracer.start_as_current_span(f"process_{job_type}") if tracer else _noop_ctx()
    with span_ctx:
        WORKER_INFLIGHT.inc()
        t0 = time.perf_counter()
        await asyncio.sleep(base_latency)
        WORKER_INFLIGHT.dec()
        elapsed = time.perf_counter() - t0
        JOB_LATENCY.labels(job_type=job_type).observe(elapsed)

        if random.random() < ERROR_RATE:
            JOBS_PROCESSED.labels(job_type=job_type, status="failed").inc()
            logging.error("job failed job_id=%s job_type=%s elapsed=%.2fs", job_id, job_type, elapsed)
            return False

        JOBS_PROCESSED.labels(job_type=job_type, status="ok").inc()
        logging.info("job ok job_id=%s job_type=%s elapsed=%.2fs", job_id, job_type, elapsed)
        return True


@asynccontextmanager
async def _noop_ctx():
    yield


# ── Main loop ──────────────────────────────────────────────────────────────

async def main_loop():
    configure_logging()
    tracer = setup_otel()
    start_http_server(int(os.getenv("METRICS_PORT", "8080")))

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = aioredis.from_url(redis_url, decode_responses=True)

    logging.info("worker started, polling %s", QUEUE_KEY)

    poll_interval = float(os.getenv("POLL_INTERVAL", "0.5"))
    while True:
        try:
            depth = await r.llen(QUEUE_KEY)
            QUEUE_DEPTH.labels(queue=QUEUE_KEY).set(depth)
        except Exception as exc:  # noqa: BLE001
            logging.warning("queue depth error: %s", exc)
            depth = 0

        # Drain a small batch each loop. If queue is empty, synth a job
        # so the demo always has signal to ship.
        for _ in range(min(int(depth or 1), 5)):
            try:
                raw = await r.lpop(QUEUE_KEY)
                if raw is None:
                    if random.random() < 0.7:  # 70% chance: synth a job for demo realism
                        job = {"id": f"synth-{int(time.time()*1000)}",
                               "type": random.choice(JOB_TYPES)}
                        await process_job(job, tracer)
                    break
                job = json.loads(raw)
                await process_job(job, tracer)
            except Exception:
                logging.exception("poll error")

        await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    asyncio.run(main_loop())

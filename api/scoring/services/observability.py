"""Structured logging + Prometheus metrics + OTEL hooks (optional)."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level":      record.levelname,
            "logger":     record.name,
            "msg":        record.getMessage(),
            "request_id": _request_id.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for noisy in ("uvicorn.access", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def set_request_context(request_id: str) -> None:
    _request_id.set(request_id)


# ── Prometheus ──────────────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST  # type: ignore
except ImportError:
    class _Op:
        def __init__(self, *_, **__): pass
        def labels(self, *_, **__): return self
        def inc(self, *_): pass
        def observe(self, *_): pass
        def set(self, *_): pass
    Counter = Histogram = Gauge = _Op  # type: ignore
    generate_latest = lambda: b""  # type: ignore
    CONTENT_TYPE_LATEST = "text/plain"  # type: ignore


REQUEST_COUNT = Counter("scoring_requests_total", "Total API requests", ["endpoint", "status"])
REQUEST_LATENCY = Histogram("scoring_request_latency_seconds", "Latency", ["endpoint"],
                            buckets=(0.01, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0, 2.0))
ALERTS_INGESTED = Counter("alerts_ingested_total", "Alerts written via /score", ["detector", "severity"])
ALERTS_ANOMALY = Counter("alerts_anomaly_total", "is_anomaly=true outcomes", ["detector"])
ENDPOINT_FAILURES = Counter("endpoint_failures_total", "Failures invoking SageMaker endpoints", ["endpoint_name"])


def setup(app, service_name: str = "scoring-api") -> None:
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if otlp:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp)))
            trace.set_tracer_provider(provider)
            FastAPIInstrumentor.instrument_app(app)
        except ImportError:
            pass


__all__ = [
    "setup", "set_request_context",
    "REQUEST_COUNT", "REQUEST_LATENCY",
    "ALERTS_INGESTED", "ALERTS_ANOMALY", "ENDPOINT_FAILURES",
    "generate_latest", "CONTENT_TYPE_LATEST",
]

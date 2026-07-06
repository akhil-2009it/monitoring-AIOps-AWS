"""Structured logging + OTEL + Prometheus setup for the demo API."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level":      record.levelname,
            "logger":     record.name,
            "msg":        record.getMessage(),
            "request_id": _request_id.get(),
            "trace_id":   _trace_id.get(),
            "service":    os.getenv("SERVICE_NAME", "demo-api"),
            "host":       os.getenv("HOSTNAME", "?"),
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
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def set_request_context(request_id: str, trace_id: str | None = None) -> None:
    _request_id.set(request_id)
    if trace_id:
        _trace_id.set(trace_id)


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


REQUEST_COUNT = Counter("demo_api_requests_total", "Total demo-api requests", ["method", "route", "status"])
REQUEST_LATENCY = Histogram(
    "demo_api_request_latency_seconds",
    "Request latency",
    ["route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
DB_QUERY_LATENCY = Histogram(
    "demo_api_db_query_seconds",
    "DB query latency",
    ["query"],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)
LOGIN_ATTEMPTS = Counter("demo_api_login_attempts_total", "Login attempts", ["status"])
ORDERS_PLACED = Counter("demo_api_orders_total", "Orders placed", ["payment_method"])
INFLIGHT = Gauge("demo_api_inflight_requests", "In-flight requests")


# ── OTEL ─────────────────────────────────────────────────────────────────────

def setup_otel(service_name: str, otlp_endpoint: str | None) -> None:
    if not otlp_endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({
            "service.name": service_name,
            "service.namespace": "demo",
            "service.version": os.getenv("SERVICE_VERSION", "0.1.0"),
        }))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        trace.set_tracer_provider(provider)
    except ImportError:
        pass


def instrument_fastapi(app) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass


def instrument_sqlalchemy(engine) -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine if hasattr(engine, "sync_engine") else engine)
    except ImportError:
        pass


def setup(app, service_name: str = "demo-api") -> None:
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    setup_otel(service_name, os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    instrument_fastapi(app)


__all__ = [
    "setup", "set_request_context",
    "REQUEST_COUNT", "REQUEST_LATENCY", "DB_QUERY_LATENCY",
    "LOGIN_ATTEMPTS", "ORDERS_PLACED", "INFLIGHT",
    "generate_latest", "CONTENT_TYPE_LATEST",
    "instrument_sqlalchemy",
]

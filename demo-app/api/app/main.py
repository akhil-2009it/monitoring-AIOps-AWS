"""Demo e-commerce API — entry point.

Wires the routes with structured logging, OTEL tracing, Prometheus metrics,
and the request-id middleware that tags every log line.

Env vars:
  SERVICE_NAME, SERVICE_VERSION  for OTEL resource attributes
  OTEL_EXPORTER_OTLP_ENDPOINT     point at the ADOT collector (e.g. http://otel-collector.monitoring:4318/v1/traces)
  DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME  the demo MySQL
  DEMO_ERROR_RATE, DEMO_SLOW_RATE, DEMO_SLOW_LATENCY  realism knobs
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .db import engine, init_schema
from .observability import (
    CONTENT_TYPE_LATEST,
    INFLIGHT,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    generate_latest,
    instrument_sqlalchemy,
    set_request_context,
    setup,
)
from .routes import router
from .seed import seed_if_empty

logger = logging.getLogger("demo-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup(app, service_name=os.getenv("SERVICE_NAME", "demo-api"))
    instrument_sqlalchemy(engine)
    await init_schema()
    await seed_if_empty()
    logger.info("demo-api ready")
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Demo e-commerce API", version="0.1.0", lifespan=lifespan)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        # Pull trace_id from current OTEL span if we have one
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            ctx = span.get_span_context()
            trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        except Exception:
            trace_id = None

        set_request_context(request_id, trace_id)
        INFLIGHT.inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            REQUEST_COUNT.labels(method=request.method, route=request.url.path, status="500").inc()
            INFLIGHT.dec()
            raise

        elapsed = time.perf_counter() - start
        INFLIGHT.dec()
        REQUEST_LATENCY.labels(route=request.url.path).observe(elapsed)
        REQUEST_COUNT.labels(method=request.method, route=request.url.path,
                              status=str(response.status_code)).inc()
        response.headers["x-request-id"] = request_id
        response.headers["x-elapsed-ms"] = f"{elapsed * 1000:.1f}"

        # The interesting line — every request emits a structured log row that
        # Fluent Bit ships to MSK, then the AIOps platform parses + features.
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method, request.url.path, response.status_code, elapsed * 1000,
        )
        return response


app.add_middleware(RequestIdMiddleware)
app.include_router(router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run("app.main:app", host=os.getenv("HOST", "0.0.0.0"),
                 port=int(os.getenv("PORT", "8000")), access_log=False)

"""
Anomaly Scoring API for the AIOps platform.

Endpoints:
  POST /score                     score one event with the streaming detector
  GET  /alerts                    list recent alerts (filters: since, source, severity)
  GET  /alerts/{id}               fetch one alert
  GET  /alerts/{id}/explain       contributing features + similar alerts
  POST /feedback                  responder labels an alert (TP/FP/ignore)
  GET  /sources                   per-source ingest health
  GET  /health
  GET  /metrics                   Prometheus

Cold-start path (works minute-one): the StreamingDetector inside the API
processes /score requests with z-score + EWMA + threshold rules.

Warm path (after detectors are trained): /score also fans out to the
SageMaker endpoints (rcf-metrics, iforest-logs, lstm-ae-traces,
log-embedding-anomaly) in parallel. Endpoint configs are env-driven so the
API works with 0..N endpoints; missing endpoints just don't contribute.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from api.scoring.schemas import (
    Alert,
    CommonEvent,
    FeedbackBody,
    HealthResponse,
    ScoreResponse,
    SourceHealth,
)
from api.scoring.services import JsonlAlertStore
from api.scoring.services.auth import auth_dependency, require_role
from api.scoring.services.observability import (
    ALERTS_ANOMALY,
    ALERTS_INGESTED,
    CONTENT_TYPE_LATEST,
    ENDPOINT_FAILURES,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    generate_latest,
    set_request_context,
    setup as setup_observability,
)
from api.scoring.services.sagemaker_invoker import SageMakerEndpointInvoker
from ml.streaming.detector import default_detector

logger = logging.getLogger("scoring-api")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALERTS_LOG_PATH = Path(os.getenv("MLOPS_ALERTS_LOG_PATH", REPO_ROOT / "data" / "alerts.jsonl"))

ENDPOINT_RCF      = os.getenv("MLOPS_ENDPOINT_RCF_METRICS", "")
ENDPOINT_IFOREST  = os.getenv("MLOPS_ENDPOINT_IFOREST_LOGS", "")
ENDPOINT_LSTM     = os.getenv("MLOPS_ENDPOINT_LSTM_AE_TRACES", "")
ENDPOINT_LOG_EMB  = os.getenv("MLOPS_ENDPOINT_LOG_EMBEDDING_ANOMALY", "")
AWS_REGION        = os.getenv("AWS_REGION", "ap-south-1")
RATE_LIMIT_PER_MIN = int(os.getenv("MLOPS_RATE_LIMIT_PER_MIN", "600"))


# ── App state ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_observability(app, service_name="scoring-api")

    state: dict[str, Any] = {
        "alerts":    JsonlAlertStore(ALERTS_LOG_PATH),
        "detector":  default_detector(),
        "invokers":  {},
    }
    if ENDPOINT_RCF:
        state["invokers"]["rcf_metrics"] = SageMakerEndpointInvoker(ENDPOINT_RCF, AWS_REGION)
    if ENDPOINT_IFOREST:
        state["invokers"]["iforest_logs"] = SageMakerEndpointInvoker(ENDPOINT_IFOREST, AWS_REGION)
    if ENDPOINT_LSTM:
        state["invokers"]["lstm_ae_traces"] = SageMakerEndpointInvoker(ENDPOINT_LSTM, AWS_REGION)
    if ENDPOINT_LOG_EMB:
        state["invokers"]["log_embedding_anomaly"] = SageMakerEndpointInvoker(ENDPOINT_LOG_EMB, AWS_REGION)

    app.state.deps = state
    logger.info("Scoring API up: endpoints=%s region=%s", list(state["invokers"]), AWS_REGION)
    try:
        yield
    finally:
        for inv in state["invokers"].values():
            try:
                await inv.close()
            except Exception:  # noqa: BLE001
                pass


app = FastAPI(
    title="AIOps Anomaly Scoring API",
    version="1.0.0",
    description="Real-time anomaly scoring across logs, metrics, traces.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("MLOPS_ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["authorization", "content-type"],
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        set_request_context(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            REQUEST_COUNT.labels(endpoint=request.url.path, status="500").inc()
            raise
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint=request.url.path).observe(elapsed)
        REQUEST_COUNT.labels(endpoint=request.url.path, status=str(response.status_code)).inc()
        response.headers["x-request-id"] = request_id
        response.headers["x-elapsed-ms"] = f"{elapsed * 1000:.1f}"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int) -> None:
        super().__init__(app)
        self._per_minute = per_minute
        self._window: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/metrics"):
            return await call_next(request)
        ip = (request.client.host if request.client else "unknown")
        now = time.time()
        async with self._lock:
            bucket = self._window.setdefault(ip, deque())
            while bucket and now - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= self._per_minute:
                return Response(status_code=429, content="rate limit exceeded")
            bucket.append(now)
        return await call_next(request)


app.add_middleware(RequestIdMiddleware)
app.add_middleware(RateLimitMiddleware, per_minute=RATE_LIMIT_PER_MIN)


def _state() -> dict:
    return app.state.deps


# ── Health & metrics ─────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = _state()
    return HealthResponse(
        status="ok",
        streaming_detector_ready=s["detector"] is not None,
        sagemaker_endpoints=list(s["invokers"].keys()),
    )


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── Score one event ─────────────────────────────────────────────────────────

def _key_and_value(event: CommonEvent) -> tuple[str, float] | None:
    attrs = event.attrs or {}
    if event.source in ("node-metrics", "container-metrics", "prometheus") and "value" in attrs:
        try:
            return f"{event.source}:{event.host or '?'}:{attrs.get('metric','?')}", float(attrs["value"])
        except (TypeError, ValueError):
            return None
    if event.latency_ms is not None:
        return f"{event.source}:{event.host or '?'}:latency_ms", float(event.latency_ms)
    if event.status is not None:
        return f"{event.source}:{event.host or '?'}:status_{event.status // 100}xx", 1.0
    return None


@app.post("/score", response_model=ScoreResponse)
async def score(event: CommonEvent, claims: dict = Depends(auth_dependency)) -> ScoreResponse:
    require_role(claims, "analyst")

    s = _state()
    detector = s["detector"]
    alerts_store = s["alerts"]

    kv = _key_and_value(event)
    if kv is None:
        raise HTTPException(400, "event has no scorable signal (need metric value, latency_ms, or status)")
    key, value = kv

    try:
        ts_epoch = datetime.fromisoformat(event.ts.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        ts_epoch = time.time()

    streaming_anomalies = detector.update(key, value, ts_epoch)

    # Optional: fan out to SageMaker endpoints in parallel
    external = await _fan_out(event)

    is_anomaly = bool(streaming_anomalies) or any(
        (r or {}).get("is_anomaly") for r in external.values()
    )
    detector_label = (streaming_anomalies[0].detector if streaming_anomalies
                      else next((k for k, r in external.items() if (r or {}).get("is_anomaly")), "none"))
    score_val = max(
        [a.score for a in streaming_anomalies] +
        [float((r or {}).get("score", 0)) for r in external.values()] + [0.0]
    )

    explanation = {
        "streaming": [a.to_dict() for a in streaming_anomalies],
        "external":  external,
    }

    if is_anomaly:
        ALERTS_ANOMALY.labels(detector=detector_label).inc()
        alert_record = {
            "detector":   detector_label,
            "metric_key": key,
            "source":     event.source,
            "severity":   event.severity,
            "score":      score_val,
            "value":      value,
            "baseline":   streaming_anomalies[0].baseline if streaming_anomalies else value,
            "explanation": (streaming_anomalies[0].explanation if streaming_anomalies else "external detector"),
            "ts_seen":    ts_epoch,
            "raw_event":  event.model_dump(),
        }
        alerts_store.append(alert_record)
        ALERTS_INGESTED.labels(detector=detector_label, severity=str(event.severity or "")).inc()

    return ScoreResponse(
        score=score_val,
        is_anomaly=is_anomaly,
        detector=detector_label,
        explanation=explanation,
        metric_key=key,
    )


# ── Alerts ──────────────────────────────────────────────────────────────────

@app.get("/alerts", response_model=list[Alert])
def list_alerts(
    since: str | None = Query(None),
    source: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    claims: dict = Depends(auth_dependency),
) -> list[Alert]:
    require_role(claims, "analyst")
    return _state()["alerts"].list(since=since, source=source, severity=severity, limit=limit)


@app.get("/alerts/{alert_id}", response_model=Alert)
def get_alert(alert_id: str, claims: dict = Depends(auth_dependency)) -> Alert:
    require_role(claims, "analyst")
    rec = _state()["alerts"].get(alert_id)
    if rec is None:
        raise HTTPException(404, f"alert {alert_id} not found")
    return rec  # type: ignore[return-value]


@app.get("/alerts/{alert_id}/explain")
def explain_alert(alert_id: str, claims: dict = Depends(auth_dependency)) -> dict:
    require_role(claims, "analyst")
    rec = _state()["alerts"].get(alert_id)
    if rec is None:
        raise HTTPException(404, f"alert {alert_id} not found")

    similar = [
        a for a in _state()["alerts"].list(limit=200)
        if a.get("metric_key") == rec.get("metric_key") and a.get("id") != alert_id
    ][:5]

    return {
        "alert":        rec,
        "metric_key":   rec.get("metric_key"),
        "deviation":    {
            "value":     rec.get("value"),
            "baseline":  rec.get("baseline"),
            "delta":     rec.get("value", 0) - rec.get("baseline", 0),
            "score":     rec.get("score"),
        },
        "explanation":  rec.get("explanation"),
        "similar_recent": similar,
    }


@app.post("/feedback")
def feedback(body: FeedbackBody, claims: dict = Depends(auth_dependency)) -> dict:
    require_role(claims, "responder")
    ok = _state()["alerts"].label(body.alert_id, body.label)
    if not ok:
        raise HTTPException(404, f"alert {body.alert_id} not found")
    return {"alert_id": body.alert_id, "label": body.label}


# ── Source health ───────────────────────────────────────────────────────────

@app.get("/sources", response_model=list[SourceHealth])
def sources(claims: dict = Depends(auth_dependency)) -> list[SourceHealth]:
    require_role(claims, "analyst")
    return _state()["alerts"].source_health()  # type: ignore[return-value]


# ── Internals ───────────────────────────────────────────────────────────────

async def _fan_out(event: CommonEvent) -> dict[str, dict | None]:
    invokers = _state()["invokers"]
    if not invokers:
        return {}
    payload = event.model_dump()

    async def _safe(name, inv):
        try:
            r = await inv.invoke(payload)
            if r is None:
                ENDPOINT_FAILURES.labels(endpoint_name=name).inc()
            return name, r
        except Exception as exc:  # noqa: BLE001
            logger.warning("Invoker %s failed: %s", name, exc)
            ENDPOINT_FAILURES.labels(endpoint_name=name).inc()
            return name, None

    pairs = await asyncio.gather(*[_safe(n, i) for n, i in invokers.items()])
    return dict(pairs)


# ── Local dev entrypoint ────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run(
        "api.scoring.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8087")),
        reload=bool(os.getenv("RELOAD", "")),
        access_log=False,
    )

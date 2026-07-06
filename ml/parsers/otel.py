"""OpenTelemetry trace span parser. Accepts a JSON dict matching the OTLP spec."""
from __future__ import annotations
from . import make_event


def parse_otel_span(span: dict) -> dict | None:
    if not span:
        return None
    attrs = {a["key"]: a["value"].get("stringValue") or a["value"].get("intValue") or a["value"].get("doubleValue")
             for a in span.get("attributes", [])}
    start_ns = int(span.get("startTimeUnixNano", 0))
    end_ns   = int(span.get("endTimeUnixNano", 0))
    dur_ms   = (end_ns - start_ns) / 1_000_000.0

    status_code = (span.get("status") or {}).get("code")  # 0=Unset, 1=OK, 2=Error
    severity = "ERROR" if status_code == 2 else "INFO"

    from datetime import datetime, timezone
    ts_iso = datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    return make_event(
        source="otel-traces",
        ts=ts_iso,
        host=attrs.get("host.name") or attrs.get("k8s.pod.name"),
        severity=severity,
        latency_ms=dur_ms,
        message=f"{span.get('name', '?')} ({dur_ms:.1f}ms)",
        attrs={
            "trace_id": span.get("traceId"),
            "span_id":  span.get("spanId"),
            "parent_span_id": span.get("parentSpanId"),
            "name": span.get("name"),
            "service.name": attrs.get("service.name"),
            "http.status_code": attrs.get("http.status_code"),
            "status_code": status_code,
        },
    )

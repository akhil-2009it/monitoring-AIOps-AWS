"""
Log parsers — every source returns a CommonEvent dict.

Schema (also documented in README.md):
    ts, ingest_ts, source, host, severity, status, latency_ms, bytes,
    src_ip, user, path, user_agent, message, attrs

A CommonEvent is plain dict (not a dataclass) so it serialises trivially to
JSON for Kinesis / MSK / S3 ingestion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Allowed source identifiers — keep in sync with infra /modules/datalake (log_sources)
SOURCES = (
    "cloudfront", "alb", "waf", "app", "eks",
    "nginx", "kafka", "mysql", "mongodb", "redis",
    "node-metrics", "container-metrics", "prometheus", "otel-traces",
)


def make_event(
    *,
    source: str,
    ts: str | datetime,
    host: str | None = None,
    severity: str | None = None,
    status: int | None = None,
    latency_ms: float | None = None,
    bytes_: int | None = None,
    src_ip: str | None = None,
    user: str | None = None,
    path: str | None = None,
    user_agent: str | None = None,
    message: str = "",
    attrs: dict[str, Any] | None = None,
) -> dict:
    """Build a normalised CommonEvent dict."""
    if isinstance(ts, datetime):
        ts_iso = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        ts_iso = ts
    return {
        "ts":         ts_iso,
        "ingest_ts":  datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source":     source,
        "host":       host or "",
        "severity":   severity,
        "status":     status,
        "latency_ms": latency_ms,
        "bytes":      bytes_,
        "src_ip":     src_ip,
        "user":       user,
        "path":       path,
        "user_agent": user_agent,
        "message":    message[:4000],
        "attrs":      attrs or {},
    }


from .alb import parse_alb       # noqa: E402, F401
from .cloudfront import parse_cloudfront  # noqa: E402, F401
from .waf import parse_waf       # noqa: E402, F401
from .app import parse_app       # noqa: E402, F401
from .eks import parse_eks       # noqa: E402, F401
from .nginx import parse_nginx   # noqa: E402, F401
from .kafka import parse_kafka   # noqa: E402, F401
from .mysql import parse_mysql   # noqa: E402, F401
from .mongodb import parse_mongodb  # noqa: E402, F401
from .redis import parse_redis   # noqa: E402, F401
from .metrics import parse_node_metric, parse_container_metric, parse_prometheus_sample  # noqa
from .otel import parse_otel_span  # noqa: E402, F401

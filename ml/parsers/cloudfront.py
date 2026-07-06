"""CloudFront access log parser (W3C extended).

The first two lines of a CF log are headers:
    #Version: 1.0
    #Fields: date time x-edge-location ...

Lines are tab-separated. We capture the high-signal columns.
"""
from __future__ import annotations
from datetime import datetime
from . import make_event

# CloudFront field order (subset). Full list at:
# https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/AccessLogs.html
CF_FIELDS = [
    "date", "time", "x_edge_location", "sc_bytes", "c_ip", "cs_method",
    "cs_host", "cs_uri_stem", "sc_status", "cs_referer", "cs_user_agent",
    "cs_uri_query", "cs_cookie", "x_edge_result_type", "x_edge_request_id",
    "x_host_header", "cs_protocol", "cs_bytes", "time_taken", "x_forwarded_for",
    "ssl_protocol", "ssl_cipher", "x_edge_response_result_type",
]


def parse_cloudfront(line: str) -> dict | None:
    if not line or line.startswith("#"):
        return None
    parts = line.rstrip("\n").split("\t")
    fields = dict(zip(CF_FIELDS, parts))

    if "date" not in fields or "time" not in fields:
        return None
    ts_str = f"{fields['date']}T{fields['time']}Z"

    def _int(v: str | None) -> int:
        try:
            return int(v) if v and v != "-" else 0
        except ValueError:
            return 0

    def _float(v: str | None) -> float:
        try:
            return float(v) if v and v != "-" else 0.0
        except ValueError:
            return 0.0

    status     = _int(fields.get("sc_status"))
    sent_bytes = _int(fields.get("sc_bytes"))
    time_taken = _float(fields.get("time_taken"))

    return make_event(
        source="cloudfront",
        ts=ts_str,
        host=fields.get("x_edge_location"),
        severity="ERROR" if status >= 500 else None,
        status=status,
        latency_ms=time_taken * 1000,
        bytes_=sent_bytes,
        src_ip=fields.get("c_ip"),
        path=fields.get("cs_uri_stem"),
        user_agent=fields.get("cs_user_agent"),
        message=f"{fields.get('cs_method', '?')} {fields.get('cs_uri_stem', '?')} -> {status}",
        attrs={
            "edge_result_type": fields.get("x_edge_result_type"),
            "ssl_protocol":     fields.get("ssl_protocol"),
            "x_forwarded_for":  fields.get("x_forwarded_for"),
        },
    )

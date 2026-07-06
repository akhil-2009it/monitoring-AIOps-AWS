"""ALB access log parser.

ALB log format (space-separated, quoted strings):
  type time elb client:port target:port request_processing_time
  target_processing_time response_processing_time elb_status_code
  target_status_code received_bytes sent_bytes "request" "user_agent" ...

We only consume the high-signal subset.
"""
from __future__ import annotations

import shlex
from datetime import datetime
from . import make_event


def parse_alb(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        parts = shlex.split(line)
    except ValueError:
        return None
    if len(parts) < 14:
        return None

    type_, ts, elb, client_port, target_port, *_rest = parts
    request_processing_time = float(parts[5]) if parts[5] not in ("-1", "-") else None
    target_processing_time  = float(parts[6]) if parts[6] not in ("-1", "-") else None
    response_processing_time = float(parts[7]) if parts[7] not in ("-1", "-") else None
    elb_status = int(parts[8]) if parts[8] != "-" else None
    target_status = int(parts[9]) if parts[9] != "-" else None
    received_bytes = int(parts[10]) if parts[10] != "-" else None
    sent_bytes = int(parts[11]) if parts[11] != "-" else None
    request_line = parts[12] if len(parts) > 12 else ""
    user_agent = parts[13] if len(parts) > 13 else ""

    method = path = ""
    if request_line:
        try:
            method, path, _proto = request_line.split(" ", 2)
        except ValueError:
            method = request_line.split(" ", 1)[0]

    src_ip = client_port.split(":")[0] if client_port else None
    latency_ms = None
    if target_processing_time is not None:
        latency_ms = (request_processing_time or 0) * 1000 + target_processing_time * 1000 + (response_processing_time or 0) * 1000

    return make_event(
        source="alb",
        ts=ts,
        host=elb,
        severity="ERROR" if (elb_status or 0) >= 500 else None,
        status=elb_status,
        latency_ms=latency_ms,
        bytes_=sent_bytes,
        src_ip=src_ip,
        path=path,
        user_agent=user_agent,
        message=f"{method} {path} -> {elb_status}",
        attrs={
            "type":             type_,
            "target":           target_port,
            "received_bytes":   received_bytes,
            "target_status":    target_status,
            "elb_status":       elb_status,
        },
    )

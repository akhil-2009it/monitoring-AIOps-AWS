"""NGINX combined log format parser.
   $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent
   "$http_referer" "$http_user_agent"
"""
from __future__ import annotations
import re
from datetime import datetime
from . import make_event

_NGINX = re.compile(
    r'(?P<ip>\S+) \S+ (?P<user>\S+) \[(?P<ts>[^\]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>\d{3}) (?P<bytes>\d+|-) '
    r'"(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'
)


def parse_nginx(line: str) -> dict | None:
    m = _NGINX.match(line.strip())
    if not m:
        return None
    g = m.groupdict()
    method = path = ""
    parts = g["request"].split(" ", 2)
    if len(parts) >= 2:
        method, path = parts[0], parts[1]

    try:
        ts_dt = datetime.strptime(g["ts"], "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        ts_dt = None

    status = int(g["status"])
    return make_event(
        source="nginx",
        ts=ts_dt or g["ts"],
        host=None,
        severity="ERROR" if status >= 500 else ("WARN" if status >= 400 else None),
        status=status,
        bytes_=int(g["bytes"]) if g["bytes"].isdigit() else None,
        src_ip=g["ip"],
        user=None if g["user"] == "-" else g["user"],
        path=path,
        user_agent=g["ua"],
        message=f"{method} {path} -> {status}",
        attrs={"referer": g["referer"]},
    )

"""Application log parser. Expects structured JSON (preferred) or
Logstash-style key=value lines. Falls back to message-only on parse failure.
"""
from __future__ import annotations
import json
import re
from . import make_event


_KV = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')


def _try_json(line: str) -> dict | None:
    try:
        rec = json.loads(line)
        return rec if isinstance(rec, dict) else None
    except (ValueError, TypeError):
        return None


def _try_kv(line: str) -> dict:
    out = {}
    for m in _KV.finditer(line):
        v = m.group(2)
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1].replace('\\"', '"')
        out[m.group(1)] = v
    return out


def parse_app(line: str | dict) -> dict | None:
    if isinstance(line, dict):
        rec = line
    elif isinstance(line, str):
        rec = _try_json(line) or _try_kv(line) or {"message": line}
    else:
        return None

    return make_event(
        source="app",
        ts=rec.get("ts") or rec.get("timestamp") or rec.get("@timestamp", ""),
        host=rec.get("host") or rec.get("hostname") or rec.get("pod"),
        severity=str(rec.get("level", rec.get("severity", ""))).upper() or None,
        status=int(rec["status"]) if "status" in rec and str(rec["status"]).isdigit() else None,
        latency_ms=float(rec["latency_ms"]) if "latency_ms" in rec else None,
        src_ip=rec.get("src_ip") or rec.get("client_ip"),
        user=rec.get("user") or rec.get("user_id"),
        path=rec.get("path") or rec.get("route"),
        message=rec.get("message", rec.get("msg", str(rec)))[:4000],
        attrs={k: v for k, v in rec.items() if k not in
               {"ts","timestamp","@timestamp","host","hostname","pod","level","severity",
                "status","latency_ms","src_ip","client_ip","user","user_id","path","route","message","msg"}},
    )

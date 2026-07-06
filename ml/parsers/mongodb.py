"""MongoDB log parser. Modern Mongo (4.4+) emits JSON per line."""
from __future__ import annotations
import json
from . import make_event


def parse_mongodb(line: str | dict) -> dict | None:
    rec = json.loads(line) if isinstance(line, str) else line
    if not rec:
        return None

    severity_map = {"D1": "DEBUG", "D2": "DEBUG", "I": "INFO", "W": "WARN", "E": "ERROR", "F": "CRITICAL"}
    return make_event(
        source="mongodb",
        ts=(rec.get("t") or {}).get("$date", ""),
        host=rec.get("host"),
        severity=severity_map.get(rec.get("s", ""), None),
        message=rec.get("msg", "")[:4000],
        attrs={
            "component": rec.get("c"),
            "context":   rec.get("ctx"),
            "id":        rec.get("id"),
            "attr":      rec.get("attr"),
        },
    )

"""Redis log parser.
Redis logs aren't structured. Format:
  pid:role timestamp loglevel message
  e.g.: '12345:M 02 Jan 2024 10:11:12.345 * Background saving terminated with success'
"""
from __future__ import annotations
import re
from . import make_event

_REDIS = re.compile(
    r"^(?P<pid>\d+):(?P<role>[A-Z]) (?P<ts>\d{1,2} \w{3} \d{4} \d{2}:\d{2}:\d{2}\.\d{3}) "
    r"(?P<lvl>[\.\-\*\#])\s+(?P<msg>.*)$"
)
_LEVEL_MAP = {".": "DEBUG", "-": "INFO", "*": "INFO", "#": "WARN"}


def parse_redis(line: str) -> dict | None:
    m = _REDIS.match(line.strip())
    if not m:
        return None
    g = m.groupdict()
    return make_event(
        source="redis",
        ts=g["ts"],
        severity=_LEVEL_MAP.get(g["lvl"], "INFO"),
        message=g["msg"],
        attrs={"pid": g["pid"], "role": g["role"]},
    )

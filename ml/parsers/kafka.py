"""Kafka broker log4j parser.
Format:
  [2024-01-02 10:11:12,345] INFO [GroupCoordinator 1]: ... (kafka.coordinator.group.GroupCoordinator)
"""
from __future__ import annotations
import re
from . import make_event

_KFK = re.compile(
    r'\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\] '
    r'(?P<level>DEBUG|INFO|WARN|ERROR|FATAL|TRACE) '
    r'(?P<msg>.*?)(?: \((?P<logger>[\w.]+)\))?$'
)


def parse_kafka(line: str) -> dict | None:
    m = _KFK.match(line.strip())
    if not m:
        return None
    g = m.groupdict()
    return make_event(
        source="kafka",
        ts=g["ts"].replace(",", ".") + "Z",  # rough ISO; broker logs lack TZ
        severity=g["level"],
        message=g["msg"],
        attrs={"logger": g["logger"]},
    )

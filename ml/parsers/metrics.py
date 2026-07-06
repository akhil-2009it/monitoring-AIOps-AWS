"""Metric ingest parsers.

Node / container / Prometheus metrics arrive as Prometheus text-format or
remote-write protobuf. We reduce them to a CommonEvent where:
  ts:    sample timestamp
  host:  the `instance` label (or pod / node)
  status: integer-cast value (0 if non-int)
  attrs: full label set + `metric` name + `value` (float)
"""
from __future__ import annotations
from . import make_event


def _from_sample(source: str, name: str, labels: dict, value: float, ts_iso: str) -> dict:
    return make_event(
        source=source,
        ts=ts_iso,
        host=labels.get("instance") or labels.get("pod") or labels.get("node"),
        message=f"{name}={value}",
        attrs={"metric": name, "value": float(value), **labels},
    )


def parse_node_metric(name: str, labels: dict, value: float, ts_iso: str) -> dict:
    return _from_sample("node-metrics", name, labels, value, ts_iso)


def parse_container_metric(name: str, labels: dict, value: float, ts_iso: str) -> dict:
    return _from_sample("container-metrics", name, labels, value, ts_iso)


def parse_prometheus_sample(name: str, labels: dict, value: float, ts_iso: str) -> dict:
    return _from_sample("prometheus", name, labels, value, ts_iso)

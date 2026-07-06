"""Smoke tests for the per-source log parsers — they should each return a
CommonEvent dict with the required keys, or None for unparseable input."""
from __future__ import annotations

import json
import pytest

from ml.parsers import (
    parse_alb, parse_cloudfront, parse_waf, parse_app, parse_eks,
    parse_nginx, parse_kafka, parse_mysql, parse_mongodb, parse_redis,
    parse_node_metric, parse_otel_span,
)


REQUIRED_KEYS = {"ts", "ingest_ts", "source", "host", "message", "attrs"}


def _check(ev: dict, expected_source: str):
    assert ev is not None
    assert REQUIRED_KEYS.issubset(ev.keys())
    assert ev["source"] == expected_source


def test_alb():
    line = (
        'h2 2024-01-02T10:11:12.345Z app/elb 203.0.113.1:54321 10.0.1.1:8080 '
        '0.001 0.05 0.001 200 200 1024 4096 "GET /api HTTP/2.0" "Mozilla/5.0" '
        'TLS_AES "tlsv1.2" - example.com'
    )
    _check(parse_alb(line), "alb")


def test_cloudfront():
    header = "#Fields: date time x-edge-location sc-bytes c-ip cs-method cs(Host) cs-uri-stem sc-status\n"
    line = "2024-01-02\t10:11:12\tMAA50-P1\t1024\t203.0.113.5\tGET\texample.com\t/index.html\t200\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t100\t-\t-\t-\t-"
    assert parse_cloudfront(header) is None
    _check(parse_cloudfront(line), "cloudfront")


def test_waf():
    rec = {
        "timestamp": "2024-01-02T10:11:12Z",
        "webaclId":  "webacl-main",
        "action":    "BLOCK",
        "httpRequest": {"clientIp": "1.2.3.4", "uri": "/api", "headers": [], "httpMethod": "GET", "country": "US"},
    }
    ev = parse_waf(rec)
    _check(ev, "waf")
    assert ev["severity"] == "ERROR"


def test_app_json():
    rec = {"ts": "2024-01-02T10:11:12Z", "level": "info", "host": "api-1",
           "status": 200, "latency_ms": 45.2, "user": "u1", "path": "/api/users",
           "message": "Order processed"}
    _check(parse_app(rec), "app")


def test_eks_audit():
    rec = {
        "kind": "Event", "verb": "delete",
        "user": {"username": "system:serviceaccount:default:app"},
        "objectRef": {"resource": "pods", "namespace": "api", "name": "x"},
        "sourceIPs": ["10.0.1.1"], "stageTimestamp": "2024-01-02T10:11:12Z",
    }
    _check(parse_eks(rec), "eks")


def test_nginx():
    line = '203.0.113.5 - - [02/Jan/2024:10:11:12 +0000] "GET /index.html HTTP/1.1" 200 1024 "-" "curl/8"'
    _check(parse_nginx(line), "nginx")


def test_kafka():
    line = "[2024-01-02 10:11:12,345] INFO Started replica fetcher (kafka.server)"
    _check(parse_kafka(line), "kafka")


def test_mysql_block():
    block = (
        "# Time: 2024-01-02T10:11:12Z\n"
        "# User@Host: app[app] @ host [10.0.1.1]\n"
        "# Query_time: 0.123  Lock_time: 0.001 Rows_sent: 5\n"
        "SET timestamp=1700000000;\n"
        "SELECT * FROM users WHERE id = 1;\n"
    )
    ev = parse_mysql(block)
    _check(ev, "mysql")
    assert ev["latency_ms"] is not None


def test_mongodb():
    rec = {"t": {"$date": "2024-01-02T10:11:12.000+00:00"}, "s": "I", "c": "NETWORK", "msg": "Connection accepted"}
    _check(parse_mongodb(rec), "mongodb")


def test_redis():
    line = "12345:M 02 Jan 2024 10:11:12.345 * Background saving terminated"
    _check(parse_redis(line), "redis")


def test_node_metric():
    ev = parse_node_metric("cpu_util", {"instance": "node-1"}, 0.42, "2024-01-02T10:11:12Z")
    _check(ev, "node-metrics")
    assert ev["attrs"]["value"] == 0.42


def test_otel_span():
    span = {
        "traceId": "abc123", "spanId": "s1", "name": "GET /api",
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano":   "1700000000050000000",
        "status": {"code": 1},
        "attributes": [
            {"key": "service.name", "value": {"stringValue": "api"}},
            {"key": "http.status_code", "value": {"intValue": "200"}},
        ],
    }
    _check(parse_otel_span(span), "otel-traces")

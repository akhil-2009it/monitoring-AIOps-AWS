"""
Lambda entrypoint — streaming statistical detection.

Triggered by Firehose-transformed batches (JSON-lines) or by Kinesis
records directly. We re-aggregate to per-(source, host, metric, window)
features, feed each value into the StreamingDetector, and emit anomalies
to S3 + EventBridge.

State persistence: this Lambda is stateless across invocations. The rolling
window therefore covers only the records in the current invocation. For
true streaming with state, deploy this same code as a Kinesis Data Analytics
(KDA) for Apache Flink job — the rule API is unchanged.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _decode_records(event: dict) -> list[dict]:
    """Yield decoded JSON records from a Firehose or Kinesis batch."""
    if "records" in event:                 # Firehose data transformation
        for r in event["records"]:
            try:
                yield json.loads(base64.b64decode(r["data"]))
            except Exception:  # noqa: BLE001
                logger.exception("Failed to decode record %s", r.get("recordId"))
    elif "Records" in event:               # Kinesis trigger
        for r in event["Records"]:
            data = r.get("kinesis", {}).get("data") or r.get("data")
            if not data:
                continue
            try:
                yield json.loads(base64.b64decode(data))
            except Exception:
                logger.exception("Failed to decode kinesis record")


def _emit_to_s3(s3, bucket: str, anomalies: list[dict]) -> None:
    if not anomalies:
        return
    now = datetime.now(timezone.utc)
    key = f"anomalies/streaming/year={now.year}/month={now.month:02d}/day={now.day:02d}/hour={now.hour:02d}/{int(time.time()*1000)}.jsonl"
    body = "\n".join(json.dumps(a) for a in anomalies).encode()
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")


def _emit_to_eventbridge(events_client, bus_name: str, anomalies: list[dict]) -> None:
    if not anomalies:
        return
    entries = [
        {
            "Source": "aiops.streaming",
            "DetailType": "AnomalyDetected",
            "Detail": json.dumps(a),
            "EventBusName": bus_name,
        }
        for a in anomalies[:10]
    ]
    events_client.put_events(Entries=entries)


def handler(event, context):  # noqa: ARG001
    import boto3

    bucket    = os.environ["ANOMALIES_BUCKET"]
    bus_name  = os.environ.get("EVENT_BUS_NAME", "default")

    s3 = boto3.client("s3")
    eb = boto3.client("events")

    from ml.streaming.detector import default_detector

    detector = default_detector()
    anomalies_out: list[dict] = []
    samples = 0

    for ev in _decode_records(event):
        # Map a CommonEvent → (key, value)
        attrs = ev.get("attrs") or {}
        if ev.get("source") in ("node-metrics", "container-metrics", "prometheus") and "value" in attrs:
            key   = f"{ev['source']}:{ev.get('host', '?')}:{attrs.get('metric','?')}"
            value = float(attrs["value"])
        elif ev.get("latency_ms") is not None:
            key   = f"{ev['source']}:{ev.get('host', '?')}:latency_ms"
            value = float(ev["latency_ms"])
        elif ev.get("status") is not None:
            key   = f"{ev['source']}:{ev.get('host', '?')}:status_{ev['status'] // 100}xx"
            value = 1.0
        else:
            continue
        samples += 1

        ts = ev.get("ts")
        try:
            ts_epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else time.time()
        except Exception:  # noqa: BLE001
            ts_epoch = time.time()

        for a in detector.update(key, value, ts_epoch):
            anomalies_out.append(a.to_dict())

    _emit_to_s3(s3, bucket, anomalies_out)
    _emit_to_eventbridge(eb, bus_name, anomalies_out)

    logger.info("Processed %d samples → %d anomalies", samples, len(anomalies_out))
    return {"samples": samples, "anomalies": len(anomalies_out)}

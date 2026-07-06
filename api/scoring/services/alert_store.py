"""Alert store — abstraction over wherever anomalies persist.

Implementations:
  - InMemoryAlertStore  : tests, ephemeral runs
  - JsonlAlertStore     : local dev, file-backed append
  - (TODO) S3PartitionedAlertStore + OpenSearchAlertStore for production reads.
"""
from __future__ import annotations

import json
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Protocol


class AlertStore(Protocol):
    def append(self, alert: Mapping) -> dict: ...
    def get(self, alert_id: str) -> dict | None: ...
    def list(self, *, since: str | None = None, source: str | None = None,
             severity: str | None = None, limit: int = 100) -> list[dict]: ...
    def label(self, alert_id: str, label: str) -> bool: ...
    def source_health(self) -> list[dict]: ...


def _make_id() -> str:
    return f"al_{uuid.uuid4().hex[:16]}"


class InMemoryAlertStore:
    def __init__(self, max_size: int = 100_000) -> None:
        self._buf: deque[dict] = deque(maxlen=max_size)
        self._by_id: dict[str, dict] = {}
        self._last_seen_by_source: dict[str, str] = {}
        self._lock = threading.Lock()

    def append(self, alert: Mapping) -> dict:
        record = dict(alert)
        record.setdefault("id", _make_id())
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        record.setdefault("label", None)
        with self._lock:
            self._buf.append(record)
            self._by_id[record["id"]] = record
            self._last_seen_by_source[record.get("source", "unknown")] = record["created_at"]
        return record

    def get(self, alert_id: str) -> dict | None:
        with self._lock:
            return self._by_id.get(alert_id)

    def list(self, *, since=None, source=None, severity=None, limit=100):
        with self._lock:
            out = []
            for r in reversed(self._buf):
                if since and r["created_at"] < since:
                    continue
                if source and r.get("source") != source:
                    continue
                if severity and r.get("severity") != severity:
                    continue
                out.append(r)
                if len(out) >= limit:
                    break
            return out

    def label(self, alert_id: str, label: str) -> bool:
        with self._lock:
            rec = self._by_id.get(alert_id)
            if rec is None:
                return False
            rec["label"] = label
            return True

    def source_health(self) -> list[dict]:
        with self._lock:
            return [
                {"source": s, "last_seen": ts, "count": sum(1 for r in self._buf if r.get("source") == s)}
                for s, ts in self._last_seen_by_source.items()
            ]


class JsonlAlertStore(InMemoryAlertStore):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            for line in self._path.read_text().splitlines():
                if line.strip():
                    super().append(json.loads(line))

    def append(self, alert: Mapping) -> dict:
        record = super().append(alert)
        with self._path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        return record

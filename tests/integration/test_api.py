"""End-to-end test of the Anomaly Scoring API."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("api")
    os.environ["MLOPS_AUTH_DISABLED"] = "1"
    os.environ["MLOPS_ALERTS_LOG_PATH"] = str(workdir / "alerts.jsonl")

    from importlib import reload
    import api.scoring.main as main_mod
    reload(main_mod)
    with TestClient(main_mod.app) as client:
        yield client


def test_health(api):
    r = api.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["streaming_detector_ready"] is True


def test_score_normal_event(api):
    payload = {
        "ts":         "2024-01-02T10:00:00Z",
        "source":     "alb",
        "host":       "alb-1",
        "status":     200,
        "latency_ms": 50,
        "src_ip":     "203.0.113.1",
        "path":       "/api/health",
        "attrs":      {},
    }
    r = api.post("/score", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "score" in body and "is_anomaly" in body and "detector" in body


def test_score_then_list_alerts(api):
    # Push enough z-score history so an outlier triggers
    for i in range(80):
        api.post("/score", json={
            "ts": f"2024-01-02T10:01:{i % 60:02d}Z",
            "source": "node-metrics", "host": "node-1",
            "attrs": {"metric": "cpu_util", "value": 0.4},
        })
    # Outlier
    r = api.post("/score", json={
        "ts": "2024-01-02T10:02:00Z",
        "source": "node-metrics", "host": "node-1",
        "attrs": {"metric": "cpu_util", "value": 99.0},
    })
    body = r.json()
    assert body["is_anomaly"] is True

    alerts = api.get("/alerts").json()
    assert len(alerts) >= 1
    alert_id = alerts[0]["id"]

    # Explain
    explain = api.get(f"/alerts/{alert_id}/explain").json()
    assert "deviation" in explain

    # Feedback
    fb = api.post("/feedback", json={"alert_id": alert_id, "label": "true_positive"})
    assert fb.status_code == 200

    # Confirm label persisted
    rec = api.get(f"/alerts/{alert_id}").json()
    assert rec["label"] == "true_positive"


def test_invalid_event_400(api):
    r = api.post("/score", json={"ts": "2024-01-02T10:00:00Z", "source": "alb", "attrs": {}})
    assert r.status_code == 400

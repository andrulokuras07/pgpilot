"""Tests del endpoint POST /workload — E3."""

from __future__ import annotations

import io
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def _stub(**kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        return {"detections": [], "recommendations": []}

    monkeypatch.setattr("backend.main.analyze_query", _stub)
    app.state.appdb_pool = object()
    app.state.snapshot = {"schema": {}, "sizes": {}, "stats": {}}
    app.state.sandbox_pool = None
    try:
        yield TestClient(app)
    finally:
        for key in ("appdb_pool", "snapshot", "sandbox_pool"):
            if hasattr(app.state, key):
                delattr(app.state, key)


CSV_SAMPLE = (
    "query,calls,total_exec_time,mean_exec_time,rows\n"
    "SELECT * FROM users WHERE id = $1,500,2500.0,5.0,500\n"
    "INSERT INTO logs VALUES ($1),10000,1000.0,0.1,10000\n"
    "SELECT count(*) FROM orders,3,15000.0,5000.0,3\n"
)


def test_workload_csv_upload(client: TestClient) -> None:
    r = client.post(
        "/workload",
        files={"file": ("stats.csv", io.BytesIO(CSV_SAMPLE.encode()), "text/csv")},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["top"]) == 3
    assert data["top"][0]["query"] == "SELECT count(*) FROM orders"


def test_workload_raw_body(client: TestClient) -> None:
    r = client.post(
        "/workload",
        content=CSV_SAMPLE.encode(),
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 200
    assert len(r.json()["top"]) == 3


def test_workload_empty_file(client: TestClient) -> None:
    r = client.post(
        "/workload",
        content=b"  ",
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 422


def test_workload_top_10_limit(client: TestClient) -> None:
    lines = ["query,calls,total_exec_time,mean_exec_time,rows"]
    for i in range(20):
        lines.append(f"SELECT {i},{i},100.0,10.0,1")
    csv = "\n".join(lines) + "\n"
    r = client.post(
        "/workload",
        content=csv.encode(),
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 200
    assert len(r.json()["top"]) == 10


def test_workload_cors(client: TestClient) -> None:
    r = client.options(
        "/workload",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

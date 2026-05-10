"""Tests del endpoint /analyze (B13).

Verifican el contrato del endpoint y la configuración de CORS para que
el frontend (B14) pueda llamarlo desde localhost:5173.
"""

from __future__ import annotations


def test_analyze_devuelve_estructura_vacia(client):
    """El stub responde con detections y recommendations vacías."""
    r = client.post("/analyze", json={"query": "SELECT 1"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"detections": [], "recommendations": []}


def test_analyze_funciona_con_query_compleja(client):
    """El stub aún no parsea, así que cualquier SQL es aceptado."""
    sql = (
        "SELECT u.name, count(*) FROM users u "
        "JOIN orders o ON u.id = o.user_id "
        "WHERE o.created_at >= '2026-01-01' GROUP BY u.name"
    )
    r = client.post("/analyze", json={"query": sql})
    assert r.status_code == 200
    assert r.json() == {"detections": [], "recommendations": []}


def test_analyze_rechaza_body_sin_query(client):
    """Sin `query` en el body, FastAPI valida con 422."""
    r = client.post("/analyze", json={})
    assert r.status_code == 422


def test_analyze_rechaza_query_vacia(client):
    """`query` vacía viola min_length=1."""
    r = client.post("/analyze", json={"query": ""})
    assert r.status_code == 422


def test_health_responde_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

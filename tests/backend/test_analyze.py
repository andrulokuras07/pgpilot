"""Tests del endpoint /analyze (B13 + C9).

Cubren el contrato del endpoint y CORS. La pipeline real
(`backend.orchestrator.analyze_query`) se testea aparte en
`test_orchestrator.py`; acá solo se ejercita el wiring HTTP →
orquestador → respuesta.

`client` (definido en conftest.py) viene con `analyze_query` stubeado
a vacío, replicando el contrato pre-C9 sin necesidad de levantar
AppDB. `unconfigured_client` simula el estado "AppDB no inicializada"
para verificar el 503.
"""

from __future__ import annotations

from typing import Any

from backend.main import app


def test_analyze_devuelve_estructura_vacia(client):
    """Sin detecciones, ambas listas vacías y status 200."""
    r = client.post("/analyze", json={"query": "SELECT 1"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"detections": [], "recommendations": []}


def test_analyze_funciona_con_query_compleja(client):
    """El endpoint no analiza el SQL, solo lo pasa al orquestador."""
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


def test_analyze_devuelve_503_si_appdb_no_configurada(unconfigured_client):
    """C9: sin `app.state.appdb_pool`, el endpoint responde 503 con
    mensaje claro indicando qué env vars faltan."""
    r = unconfigured_client.post("/analyze", json={"query": "SELECT 1"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "APPDB_HOST" in detail


def test_analyze_propaga_payload_del_orquestador(client, monkeypatch):
    """El endpoint pasa el dict del orquestador tal cual al body de
    respuesta. Esto verifica que C9 enriquece detections/recommendations
    sin que el endpoint los ré-empaquete (defensa contra drop accidental
    de campos)."""
    fake_payload = {
        "detections": [
            {
                "type": "seq_scan_on_large_table",
                "found": True,
                "confidence": 1.0,
                "evidence": {"matches": [{"table": "public.posts"}]},
            }
        ],
        "recommendations": [
            {
                "kind": "create_index",
                "table": "public.posts",
                "column": "author_id",
                "create_index_sql": "CREATE INDEX idx_x ON public.posts (author_id);",
                "sandbox_verdict": "validated",
                "explanation": {"text": "...", "source": "template", "confidence": 0.8},
            }
        ],
    }

    def fake_analyze_query(**kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        return fake_payload

    monkeypatch.setattr("backend.main.analyze_query", fake_analyze_query)

    r = client.post("/analyze", json={"query": "SELECT * FROM posts WHERE author_id = 42"})
    assert r.status_code == 200
    body = r.json()
    assert body["detections"][0]["type"] == "seq_scan_on_large_table"
    assert body["recommendations"][0]["sandbox_verdict"] == "validated"
    assert body["recommendations"][0]["explanation"]["source"] == "template"


def test_analyze_traduce_analyze_error_a_status_indicado(client, monkeypatch):
    """C9: errores del orquestador se mapean al status code que
    `AnalyzeError` indica (400 sintaxis, 403 read-only, 504 timeout)."""
    from backend.orchestrator import AnalyzeError

    def boom(**kwargs: Any) -> Any:
        raise AnalyzeError(403, "Solo lectura")

    monkeypatch.setattr("backend.main.analyze_query", boom)

    r = client.post("/analyze", json={"query": "UPDATE posts SET x=1"})
    assert r.status_code == 403
    assert "Solo lectura" in r.json()["detail"]


def test_analyze_pasa_request_id_al_orquestador(client, monkeypatch):
    """Cada request genera un `request_id` que se propaga al orquestador
    (y de ahí al log de C8). Verificamos que llega como kwarg y es
    string no vacío."""
    captured: dict[str, Any] = {}

    def capture_analyze_query(**kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        captured.update(kwargs)
        return {"detections": [], "recommendations": []}

    monkeypatch.setattr("backend.main.analyze_query", capture_analyze_query)
    r = client.post("/analyze", json={"query": "SELECT 1"})

    assert r.status_code == 200
    assert isinstance(captured.get("request_id"), str)
    assert len(captured["request_id"]) >= 16


def test_analyze_pasa_appdb_y_sandbox_pools_del_state(client, monkeypatch):
    """El endpoint lee `app.state.appdb_pool/snapshot/sandbox_pool` y los
    pasa al orquestador. Esto blinda el wiring del lifespan."""
    sentinel_appdb = object()
    sentinel_sandbox = object()
    sentinel_snapshot = {"schema": {"a": {}}, "sizes": {}, "stats": {}}

    app.state.appdb_pool = sentinel_appdb
    app.state.sandbox_pool = sentinel_sandbox
    app.state.snapshot = sentinel_snapshot

    captured: dict[str, Any] = {}

    def capture(**kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        captured.update(kwargs)
        return {"detections": [], "recommendations": []}

    monkeypatch.setattr("backend.main.analyze_query", capture)

    client.post("/analyze", json={"query": "SELECT 1"})

    assert captured["appdb_pool"] is sentinel_appdb
    assert captured["sandbox_pool"] is sentinel_sandbox
    assert captured["snapshot"] is sentinel_snapshot


def test_health_responde_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

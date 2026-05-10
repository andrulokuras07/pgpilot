"""Tests de configuración CORS (B13/B14).

El frontend corre en localhost:5173 y debe poder hacer POST a /analyze
sin que el navegador lo bloquee. Estos tests simulan la negociación de
CORS que hace el navegador antes de enviar la request real.
"""

from __future__ import annotations

ORIGEN_FRONTEND = "http://localhost:5173"


def test_preflight_permite_post_desde_frontend(client):
    """Preflight OPTIONS desde el origen del frontend dev."""
    r = client.options(
        "/analyze",
        headers={
            "Origin": ORIGEN_FRONTEND,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ORIGEN_FRONTEND
    metodos = r.headers.get("access-control-allow-methods", "")
    assert "POST" in metodos


def test_post_real_incluye_header_de_origen_permitido(client):
    """En el POST real, el backend devuelve el header que permite al
    navegador entregar la respuesta al JS del frontend."""
    r = client.post(
        "/analyze",
        json={"query": "SELECT 1"},
        headers={"Origin": ORIGEN_FRONTEND},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ORIGEN_FRONTEND


def test_origen_no_permitido_no_recibe_header_cors(client):
    """Un origen distinto al frontend no debería recibir el header
    Access-Control-Allow-Origin (el navegador bloquearía la respuesta)."""
    r = client.post(
        "/analyze",
        json={"query": "SELECT 1"},
        headers={"Origin": "http://attacker.example.com"},
    )
    assert r.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}

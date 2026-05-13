"""Test de integración: cobertura del endpoint público /analyze contra las
20 queries plantadas en AppDB v1.

A diferencia de `test_coverage_appdb_v1.py` (que prueba los detectores
del motor directamente), este test verifica el **endpoint HTTP completo**:
query → EXPLAIN → parse → 18 detectores → recommend → findings →
response JSON. Es el "hecho-cuando" del fix del orquestador que conectó
los 18 detectores al endpoint.

Requiere:
- AppDB corriendo (`docker compose up appdb -d`).
- Stats frescas (`ANALYZE` ejecutado).

Marker: `integration` — no corre en CI sin AppDB.

Nota: Q19 (NOT IN sin índice) puede dar timeout con el
statement_timeout por defecto (5s). El test tolera 504 y lo
cuenta como no-detección; el umbral ≥16 absorbe ese caso.

Uso típico:
    docker compose up appdb -d
    .venv/bin/pytest tests/integration/test_analyze_endpoint_covers_planted_queries.py -v
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.main import app

pytestmark = pytest.mark.integration


# =====================================================================
# Queries plantadas — misma lista que test_coverage_appdb_v1.py
# =====================================================================
# (qid, sql, expected_covered)
# Q05 y Q10 son xfail conocidos (seed insuficiente).

PLANTED_QUERIES: list[tuple[str, str, bool]] = [
    ("Q01", "SELECT * FROM posts WHERE author_id = 5000", True),
    (
        "Q02",
        "SELECT id FROM posts WHERE author_id = 100 OR mentioned_user_id = 100",
        True,
    ),
    ("Q03", "SELECT id FROM posts WHERE content LIKE '%bitcoin%'", True),
    (
        "Q04",
        "SELECT count(*) FROM posts WHERE EXTRACT(YEAR FROM created_at) = 2024",
        True,
    ),
    (
        "Q05",
        (
            "SELECT u.username, count(l.id) AS like_count "
            "FROM users u JOIN likes l ON l.user_id = u.id "
            "GROUP BY u.username ORDER BY like_count DESC"
        ),
        False,  # D3 mergeado pero sort cabe en work_mem
    ),
    (
        "Q06",
        (
            "SELECT p.id, c.content FROM posts p, comments c "
            "WHERE p.id = c.post_id AND p.author_id BETWEEN 1 AND 100"
        ),
        True,
    ),
    (
        "Q07",
        "SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '7 days'",
        True,
    ),
    (
        "Q08",
        (
            "SELECT id, created_at FROM posts "
            "WHERE author_id = 5000 ORDER BY created_at DESC LIMIT 20"
        ),
        True,
    ),
    (
        "Q09",
        (
            "SELECT id, (SELECT count(*) FROM comments WHERE post_id = posts.id) "
            "FROM posts WHERE author_id = 1000 LIMIT 50"
        ),
        True,
    ),
    (
        "Q10",
        "SELECT count(*) FROM tags WHERE use_count > 100",
        False,  # D2 ratio bajo umbral 10×
    ),
    (
        "Q11",
        "SELECT id FROM notifications WHERE user_id = 1000 AND read = false",
        True,
    ),
    ("Q12", "SELECT * FROM users WHERE username::text = '12345'", True),
    (
        "Q13",
        (
            "SELECT p.id, u.username FROM posts p "
            "JOIN users u ON u.id = p.author_id "
            "WHERE u.is_verified = true AND u.is_active = true "
            "AND p.is_deleted = false"
        ),
        True,
    ),
    (
        "Q14",
        (
            "WITH active_users AS MATERIALIZED ("
            "SELECT id FROM users WHERE last_login > NOW() - INTERVAL '30 days'"
            ") "
            "SELECT count(*) FROM active_users "
            "JOIN posts ON posts.author_id = active_users.id"
        ),
        True,
    ),
    (
        "Q15",
        (
            "SELECT id FROM posts "
            "WHERE created_at > NOW() - INTERVAL '2 years' AND likes_count > 950"
        ),
        True,
    ),
    (
        "Q16",
        "SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 1000",
        True,
    ),
    (
        "Q17",
        (
            "SELECT id FROM users WHERE id IN ("
            "SELECT author_id FROM posts WHERE created_at > NOW() - INTERVAL '7 days'"
            ")"
        ),
        True,
    ),
    (
        "Q18",
        "SELECT * FROM comments ORDER BY created_at DESC LIMIT 50",
        True,
    ),
    (
        "Q19",
        "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts) LIMIT 10",
        True,
    ),
    ("Q20", "SELECT count(*) FROM posts", True),
]

# Queries que se excluyen de la cuenta de cobertura (seed insuficiente).
_XFAIL_QUERIES = frozenset({"Q05", "Q10"})


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture(scope="module")
def integration_client(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[TestClient]:
    """TestClient con AppDB real vía lifespan.

    Seteamos las env vars de AppDB para que el lifespan de FastAPI cree
    el pool y extraiga el snapshot normalmente (como en producción). Esto
    es más fiel al flujo real que poblar app.state a mano.
    """
    tmp = tmp_path_factory.mktemp("llm_logs")

    # Env vars para que el lifespan conecte a AppDB
    env_overrides = {
        "APPDB_HOST": os.getenv("APPDB_HOST", "localhost"),
        "APPDB_PORT": os.getenv("APPDB_PORT", "5434"),
        "APPDB_DB": os.getenv("APPDB_DB", "appdb"),
        "APPDB_USER": os.getenv("APPDB_USER", "app_user"),
        "APPDB_PASSWORD": os.getenv("APPDB_PASSWORD", "app_pass"),
        "LLM_ENABLED": "false",
        "PGPILOT_LLM_LOG_PATH": str(tmp / "log.jsonl"),
    }

    old_env: dict[str, str | None] = {}
    for key, val in env_overrides.items():
        old_env[key] = os.environ.get(key)
        os.environ[key] = val

    try:
        with TestClient(app) as client:
            yield client
    finally:
        for key, old_val in old_env.items():
            if old_val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_val


# =====================================================================
# Tests
# =====================================================================


def test_endpoint_cubre_al_menos_16_queries_plantadas(
    integration_client: TestClient,
) -> None:
    """Hecho-cuando del fix del orquestador: las 20 queries plantadas
    en AppDB v1, enviadas al endpoint público /analyze, producen al
    menos 16 detecciones (rúbrica)."""
    detected: list[str] = []
    failed: list[str] = []

    for code, sql, expected in PLANTED_QUERIES:
        if code in _XFAIL_QUERIES:
            continue  # xfail conocido, seed insuficiente

        resp = integration_client.post("/analyze", json={"query": sql})

        if resp.status_code == 504:
            # Q19 puede dar timeout — acepta y anota como no-detección
            failed.append(f"{code}: timeout 504")
            continue

        assert resp.status_code == 200, f"{code}: HTTP {resp.status_code} {resp.text}"
        body = resp.json()

        if body["detections"]:
            detected.append(code)
        else:
            failed.append(f"{code}: sin detecciones")

    assert len(detected) >= 16, (
        f"Cobertura insuficiente: {len(detected)}/{20 - len(_XFAIL_QUERIES)} "
        f"detectadas vía endpoint (objetivo: ≥16). "
        f"Detectadas: {detected}. "
        f"Fallidas: {failed}"
    )


def test_q01_dispara_missing_index(integration_client: TestClient) -> None:
    """Q01 (SELECT * FROM posts WHERE author_id = ...) debe disparar D16
    con CREATE INDEX sobre author_id. Caso canónico del fix."""
    resp = integration_client.post(
        "/analyze",
        json={"query": "SELECT * FROM posts WHERE author_id = 100;"},
    )
    assert resp.status_code == 200
    body = resp.json()

    codes = {d["code"] for d in body["detections"]}
    assert "D16" in codes, f"D16 no disparó para Q01. Códigos detectados: {codes}"

    # Recomendación de create_index sobre author_id
    create_index_recs = [
        r
        for r in body["recommendations"]
        if r["kind"] == "create_index" and r.get("column") == "author_id"
    ]
    assert len(create_index_recs) >= 1, (
        f"No hay recomendación create_index sobre author_id. "
        f"Recomendaciones: {[(r['kind'], r.get('column')) for r in body['recommendations']]}"
    )
    assert "CREATE INDEX" in create_index_recs[0]["create_index_sql"]
    assert "author_id" in create_index_recs[0]["create_index_sql"]

"""D14 — Tests de cobertura sobre AppDB v1.

Para cada una de las 20 queries plantadas, ejecuta EXPLAIN contra la
AppDB real, corre los 13 detectores activos y verifica que al menos uno
de ellos dispara cuando se espera cobertura.

Los tests son parametrizados sobre `PLANTED` (catálogo compartido con
`scripts/measure_coverage.py`). Cada entrada lleva `expected_covered:
bool`: si es True, la query DEBE dispararle a algún detector; si es
False, está documentado en `pending_detector` cuál detector falta
(D2/D3/D20/D22).

Línea segura de la rúbrica: 16/20. El test agregador
`test_coverage_meets_rubric_target` verifica que ≥16 queries quedan
cubiertas; medición 2026-05-12 = 16/20 estable (D7 alcanza Q19 bajo
`APPDB_TEST_TIMEOUT_MS=180000`). El test es de bloqueo: si en el futuro
la cobertura baja, rompe y obliga a investigar la regresión.

Marker: `integration` — requiere AppDB corriendo en `localhost:5434`.

Uso típico:
    docker compose up appdb -d
    pytest tests/integration/test_coverage_appdb_v1.py -v
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from motor import (
    Detection,
    detect_cardinality_misestimate,
    detect_correlated_subquery,
    detect_function_in_where,
    detect_like_leading_wildcard,
    detect_missing_covering_index,
    detect_missing_index,
    detect_nested_loop_large_outer,
    detect_or_across_tables,
    detect_partial_index_opportunity,
    detect_select_star,
    detect_seq_scan_on_large_table,
    detect_type_mismatch,
    detect_unnecessary_cte_materialize,
    parse_explain,
)

pytestmark = pytest.mark.integration


DETECTORS: tuple[tuple[str, Callable[..., Detection]], ...] = (
    ("C1", detect_seq_scan_on_large_table),
    ("D4", detect_like_leading_wildcard),
    ("D5", detect_function_in_where),
    ("D6", detect_or_across_tables),
    ("D7", detect_correlated_subquery),
    ("D8", detect_nested_loop_large_outer),
    ("D9", detect_select_star),
    ("D10", detect_missing_covering_index),
    ("D11", detect_type_mismatch),
    ("D12", detect_unnecessary_cte_materialize),
    ("D16", detect_missing_index),
    ("D17", detect_partial_index_opportunity),
    ("D18", detect_cardinality_misestimate),
)


@dataclass(frozen=True)
class PlantedQuery:
    qid: str
    antipattern: str
    sql: str
    expected_covered: bool  # ¿debería disparar al menos un detector hoy?
    pending_detector: str = ""  # código del detector pendiente cuando expected=False


# Mismo orden y SQLs que `scripts/measure_c1_coverage.py.PLANTED`. La
# columna `expected_covered` refleja el estado real medido el 2026-05-12
# con los 13 detectores activos (C1 + D4..D12 + D16..D18). El día que
# aterricen D20/D22/D2/D3, se flippea el flag correspondiente.
PLANTED: tuple[PlantedQuery, ...] = (
    PlantedQuery(
        "Q01",
        "Seq scan sin índice en author_id",
        "SELECT * FROM posts WHERE author_id = 5000",
        expected_covered=True,  # D16 + D9
    ),
    PlantedQuery(
        "Q02",
        "OR cross-column",
        "SELECT id FROM posts WHERE author_id = 100 OR mentioned_user_id = 100",
        expected_covered=True,  # D16
    ),
    PlantedQuery(
        "Q03",
        "LIKE wildcard inicial",
        "SELECT id FROM posts WHERE content LIKE '%bitcoin%'",
        expected_covered=True,  # D4
    ),
    PlantedQuery(
        "Q04",
        "Función no-immutable en WHERE",
        "SELECT count(*) FROM posts WHERE EXTRACT(YEAR FROM created_at) = 2024",
        expected_covered=True,  # D5
    ),
    PlantedQuery(
        "Q05",
        "Sort spill to disk",
        (
            "SELECT u.username, count(l.id) AS like_count "
            "FROM users u JOIN likes l ON l.user_id = u.id "
            "GROUP BY u.username ORDER BY like_count DESC"
        ),
        expected_covered=False,
        pending_detector="D3 (sort spill — pendiente)",
    ),
    PlantedQuery(
        "Q06",
        "Nested loop ineficiente",
        (
            "SELECT p.id, c.content FROM posts p, comments c "
            "WHERE p.id = c.post_id AND p.author_id BETWEEN 1 AND 100"
        ),
        expected_covered=True,  # D16
    ),
    PlantedQuery(
        "Q07",
        "SELECT * sobre tabla grande",
        "SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '7 days'",
        expected_covered=True,  # D9
    ),
    PlantedQuery(
        "Q08",
        "Falta índice cubriente",
        (
            "SELECT id, created_at FROM posts "
            "WHERE author_id = 5000 ORDER BY created_at DESC LIMIT 20"
        ),
        expected_covered=True,  # D16
    ),
    PlantedQuery(
        "Q09",
        "Subquery correlacionada",
        (
            "SELECT id, (SELECT count(*) FROM comments WHERE post_id = posts.id) "
            "FROM posts WHERE author_id = 1000 LIMIT 50"
        ),
        expected_covered=True,  # D7 + D16
    ),
    PlantedQuery(
        "Q10",
        "Stats obsoletas en tags",
        "SELECT count(*) FROM tags WHERE use_count > 100",
        expected_covered=False,
        pending_detector="D2 (stats obsoletas — pendiente)",
    ),
    PlantedQuery(
        "Q11",
        "Falta índice parcial",
        "SELECT id FROM notifications WHERE user_id = 1000 AND read = false",
        expected_covered=True,  # D17
    ),
    PlantedQuery(
        "Q12",
        "Cast en columna indexada",
        "SELECT * FROM users WHERE username::text = '12345'",
        expected_covered=True,  # D9
    ),
    PlantedQuery(
        "Q13",
        "Cardinalidad multi-condición",
        (
            "SELECT p.id, u.username FROM posts p "
            "JOIN users u ON u.id = p.author_id "
            "WHERE u.is_verified = true AND u.is_active = true "
            "AND p.is_deleted = false"
        ),
        expected_covered=True,  # D18
    ),
    PlantedQuery(
        "Q14",
        "CTE MATERIALIZED",
        (
            "WITH active_users AS MATERIALIZED ("
            "SELECT id FROM users WHERE last_login > NOW() - INTERVAL '30 days'"
            ") "
            "SELECT count(*) FROM active_users "
            "JOIN posts ON posts.author_id = active_users.id"
        ),
        expected_covered=True,  # D12
    ),
    PlantedQuery(
        "Q15",
        "Recheck con alta filter ratio",
        (
            "SELECT id FROM posts "
            "WHERE created_at > NOW() - INTERVAL '2 years' AND likes_count > 950"
        ),
        expected_covered=True,  # D16
    ),
    PlantedQuery(
        "Q16",
        "HAVING que debería ser WHERE",
        "SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 1000",
        expected_covered=True,  # D16
    ),
    PlantedQuery(
        "Q17",
        "IN con subquery vs EXISTS",
        (
            "SELECT id FROM users WHERE id IN ("
            "SELECT author_id FROM posts WHERE created_at > NOW() - INTERVAL '7 days'"
            ")"
        ),
        expected_covered=False,
        pending_detector="D20 (IN→EXISTS — pendiente)",
    ),
    PlantedQuery(
        "Q18",
        "ORDER BY+LIMIT sin índice",
        "SELECT * FROM comments ORDER BY created_at DESC LIMIT 50",
        expected_covered=True,  # D9
    ),
    PlantedQuery(
        "Q19",
        "NOT IN con NULL",
        "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts) LIMIT 10",
        expected_covered=True,  # D7 dispara por el SubPlan del NOT IN
        # D7 cubre la presencia del SubPlan pero NO el bug específico
        # del NULL trap (el resultado puede ser silenciosamente vacío
        # si la subquery devuelve NULL). D21 sigue pendiente para la
        # prosa específica de ese caso. Si Q19 excede
        # `APPDB_TEST_TIMEOUT_MS`, el test se vuelve FN y el agregador
        # lo reporta como regresión (no como flake).
    ),
    PlantedQuery(
        "Q20",
        "count(*) sobre tabla grande",
        "SELECT count(*) FROM posts",
        expected_covered=False,
        pending_detector="D22 (count(*) tabla grande — pendiente)",
    ),
)


def _explain(pool, sql: str) -> tuple[Any, str | None]:
    """Ejecuta EXPLAIN ANALYZE. Devuelve `(raw_json, error_msg)`. Nunca
    levanta — el caller decide si saltarse el test o registrar el FN.
    """
    try:
        with pool.connection() as conn:
            cur = conn.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
            row = cur.fetchone()
            return (row[0] if row else None, None)
    except Exception as exc:  # noqa: BLE001 — todo se reporta tabulado
        return (None, str(exc))


def _run_all_detectors(plan, snapshot, sql: str) -> dict[str, Detection]:
    """Detectores con firma extendida (D9, D11) reciben `sql`."""
    out: dict[str, Detection] = {}
    for code, fn in DETECTORS:
        params = inspect.signature(fn).parameters
        if "sql" in params:
            out[code] = fn(plan, snapshot, sql=sql)
        else:
            out[code] = fn(plan, snapshot)
    return out


@pytest.fixture(scope="session")
def coverage_results(appdb_pool, appdb_snapshot) -> dict[str, dict[str, Any]]:
    """Corre EXPLAIN + 13 detectores sobre las 20 queries una sola vez.

    Si una query falla (timeout, error de SQL), el resultado guarda
    `error` y `covered=False`. El test individual decide si saltarse o
    fallar. Cachear es importante: el test parametrizado pediría 20 ×
    snapshot, pero compartir la sesión vuelve los tests rápidos.
    """
    results: dict[str, dict[str, Any]] = {}
    for q in PLANTED:
        raw, error = _explain(appdb_pool, q.sql)
        if error is not None:
            results[q.qid] = {
                "error": error,
                "covered": False,
                "fired": [],
                "detections": {},
            }
            continue
        plan = parse_explain(raw)
        detections = _run_all_detectors(plan, appdb_snapshot, q.sql)
        results[q.qid] = {
            "error": None,
            "detections": detections,
            "covered": any(d.found for d in detections.values()),
            "fired": [code for code, d in detections.items() if d.found],
            "top": plan.root.node_type,
        }
    return results


@pytest.mark.parametrize("planted", PLANTED, ids=lambda q: q.qid)
def test_coverage_per_query(planted: PlantedQuery, coverage_results) -> None:
    """Una query plantada debe estar cubierta por al menos un detector
    si `expected_covered=True`. Las queries marcadas como False hoy se
    saltan con razón explícita (apuntan al detector pendiente).

    Si EXPLAIN falló (timeout/SQL error) y la query estaba marcada como
    `expected_covered=False`, se documenta como xfail; si estaba
    marcada como `expected_covered=True`, falla el test (el error es
    una regresión que hay que mirar).
    """
    result = coverage_results[planted.qid]

    if not planted.expected_covered:
        reason = planted.pending_detector
        if result.get("error"):
            reason = f"{reason}; EXPLAIN: {result['error']}"
        pytest.xfail(f"{planted.qid} ({planted.antipattern}) pendiente: {reason}")

    if result.get("error"):
        pytest.fail(
            f"{planted.qid} EXPLAIN falló contra AppDB: {result['error']}. "
            f"La query estaba marcada como cubierta — investigar regresión."
        )

    assert result["covered"], (
        f"{planted.qid} ({planted.antipattern}) NO detectada por ningún detector. "
        f"Top node: {result.get('top')}. "
        f"Detectores que dispararon: {result['fired']}"
    )


def test_coverage_total_matches_expected(coverage_results) -> None:
    """Hoy 15/20 deben quedar cubiertas (medición empírica 2026-05-12)."""
    covered = sum(1 for r in coverage_results.values() if r["covered"])
    expected = sum(1 for q in PLANTED if q.expected_covered)
    assert covered == expected, (
        f"Cobertura medida {covered}/20 ≠ esperada {expected}/20. "
        f"Disparos por query: "
        f"{[(q, r['fired']) for q, r in coverage_results.items() if r['covered']]}"
    )


def test_coverage_meets_rubric_target(coverage_results) -> None:
    """Objetivo rúbrica Criterio 2.1: ≥16/20 queries detectadas (80%).

    Test de bloqueo: rompe si la cobertura baja. Medición confiable
    2026-05-12 = 16/20.
    """
    covered = sum(1 for r in coverage_results.values() if r["covered"])
    assert covered >= 16, f"Cobertura {covered}/20 por debajo del objetivo rúbrica (16)."

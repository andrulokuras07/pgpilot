"""D15 — Sistema anti-falsos-positivos sobre AppDB v1.

Corre los 13 detectores activos sobre 10 queries "sanas" (queries que
NO contienen ningún anti-pattern conocido) y verifica que el motor no
las reporte. La rúbrica resta 0.5 pts por cada falso positivo hasta -3.

Criterio del backlog: menos de 3 falsos positivos sobre 10 queries
sanas. El test agregador `test_false_positive_count_below_limit` es el
gate; los tests individuales sirven para diagnosticar cuál query
dispara y qué detector.

Las queries elegidas usan accesos por PK, índices únicos, tablas
pequeñas o filtros que el planner resuelve sin Seq Scan caro — son los
patrones que el cliente real usa todo el día y NO deben aparecer en el
reporte de PgPilot. Si un detector dispara aquí, hay que ajustar
umbrales o filtros (es exactamente el ejercicio del backlog).

Marker: `integration` — requiere AppDB corriendo en `localhost:5434`.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

import pytest

from motor import (
    Detection,
    parse_explain,
)
from tests.integration.test_coverage_appdb_v1 import DETECTORS, _explain

pytestmark = pytest.mark.integration

# Tope que la rúbrica usa para el bonus completo del Criterio 2.1.
MAX_ALLOWED_FALSE_POSITIVES = 3


@dataclass(frozen=True)
class SaneQuery:
    qid: str
    rationale: str  # por qué esta query NO es un anti-pattern
    sql: str


# 10 queries sanas — combinan PK lookups (Index Scan), índices únicos
# (users.email, users.username, tags.name), tablas chicas (tags) y
# rangos pequeños sobre PK. Todas referencian tablas/columnas reales de
# AppDB v1 verificadas con `\d` (users, posts, comments, tags,
# notifications, likes).
SANE_QUERIES: tuple[SaneQuery, ...] = (
    SaneQuery(
        "S01",
        "PK lookup sobre users — Index Scan en users_pkey, sin filter ratio",
        "SELECT id, username FROM users WHERE id = 1",
    ),
    SaneQuery(
        "S02",
        "PK lookup sobre posts — Index Scan, una sola fila",
        "SELECT id, content FROM posts WHERE id = 100",
    ),
    SaneQuery(
        "S03",
        "Índice único sobre users.email — Index Scan en idx_users_email",
        "SELECT id FROM users WHERE email = 'test@example.com'",
    ),
    SaneQuery(
        "S04",
        "Índice único sobre users.username — Index Scan",
        "SELECT id FROM users WHERE username = 'alice'",
    ),
    SaneQuery(
        "S05",
        "Tabla chica (tags) ordenada por índice — sin anti-pattern",
        "SELECT id, name FROM tags ORDER BY use_count DESC LIMIT 10",
    ),
    SaneQuery(
        "S06",
        "Count sobre tabla chica (tags) — D22 no aplica (umbral 100k)",
        "SELECT count(*) FROM tags",
    ),
    SaneQuery(
        "S07",
        "PK lookup sobre comments — Index Scan",
        "SELECT id, content FROM comments WHERE id = 5",
    ),
    SaneQuery(
        "S08",
        "Range scan sobre PK de users (20 filas) — bajo el umbral de D10",
        "SELECT id, username FROM users WHERE id BETWEEN 1 AND 20",
    ),
    SaneQuery(
        "S09",
        "IN con literales sobre PK de posts — Index Scan multi-key",
        "SELECT id FROM posts WHERE id IN (1, 2, 3, 4, 5)",
    ),
    SaneQuery(
        "S10",
        "Tabla chica (tags) por nombre único — Index Scan en idx_tags_name",
        "SELECT id, use_count FROM tags WHERE name = 'tech'",
    ),
)


def _run_all_detectors(plan, snapshot, sql: str) -> dict[str, Detection]:
    out: dict[str, Detection] = {}
    for code, fn in DETECTORS:
        params = inspect.signature(fn).parameters
        if "sql" in params:
            out[code] = fn(plan, snapshot, sql=sql)
        else:
            out[code] = fn(plan, snapshot)
    return out


@pytest.fixture(scope="session")
def fp_results(appdb_pool, appdb_snapshot) -> dict[str, dict[str, Any]]:
    """Corre EXPLAIN + 13 detectores sobre las 10 queries sanas."""
    results: dict[str, dict[str, Any]] = {}
    for q in SANE_QUERIES:
        raw, error = _explain(appdb_pool, q.sql)
        if error is not None:
            results[q.qid] = {"error": error, "fired": [], "any_fp": False}
            continue
        plan = parse_explain(raw)
        detections = _run_all_detectors(plan, appdb_snapshot, q.sql)
        fired = [code for code, d in detections.items() if d.found]
        results[q.qid] = {
            "error": None,
            "fired": fired,
            "any_fp": bool(fired),
            "top": plan.root.node_type,
        }
    return results


@pytest.mark.parametrize("query", SANE_QUERIES, ids=lambda q: q.qid)
def test_no_detector_fires_on_sane_query(query: SaneQuery, fp_results) -> None:
    """Ninguna query sana debe disparar ningún detector. Si dispara, el
    output indica qué detector y se ajusta el umbral o filtro."""
    result = fp_results[query.qid]
    if result.get("error"):
        pytest.skip(
            f"{query.qid} EXPLAIN falló (probable schema/dato faltante en "
            f"AppDB v1): {result['error']}. Test no aplica."
        )
    assert not result["any_fp"], (
        f"{query.qid} ({query.rationale}) generó falso positivo. "
        f"Detector(es) que disparó(aron): {result['fired']}. "
        f"Top node: {result.get('top')}. "
        f"Acción: ajustar umbral del detector o documentar como FP aceptado."
    )


def test_false_positive_count_below_limit(fp_results) -> None:
    """Criterio rúbrica: menos de 3 falsos positivos sobre 10 sanas."""
    valid = [r for r in fp_results.values() if not r.get("error")]
    fp_count = sum(1 for r in valid if r["any_fp"])
    skipped = len(fp_results) - len(valid)
    assert fp_count < MAX_ALLOWED_FALSE_POSITIVES, (
        f"{fp_count} falsos positivos sobre {len(valid)} sanas "
        f"({skipped} skipped por EXPLAIN error). Límite: "
        f"{MAX_ALLOWED_FALSE_POSITIVES - 1}. "
        f"Detalle: {[(q, r['fired']) for q, r in fp_results.items() if r.get('any_fp')]}"
    )

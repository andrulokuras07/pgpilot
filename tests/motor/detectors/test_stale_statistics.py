"""Tests del detector D2 — Stats obsoletas (mismatch plan_rows/actual_rows).

Criterio del backlog:
    Hecho cuando: detector pasa test sobre plan plantado, documentado
    en patterns.

Cubre:
- Happy path: Seq Scan con ratio plan/actual ≥10x → dispara.
- Variante: ratio inverso (subestimación) → también dispara.
- Frontera: ratio menor a 10x → no dispara (defensa contra ruido del planner).
- Frontera: EXPLAIN sin ANALYZE (`actual_rows is None`) → no dispara.
- Frontera con D18: el detector NO mira joins (D18 es para joins
  multi-col, no para stats de tabla puras).
- Robustez: `actual_rows=0` con plan grande (overestimación total),
  `relation_name is None`, plan sin scans.
"""

from __future__ import annotations

from typing import Any

import pytest

from motor import detect_stale_statistics, parse_explain

_EMPTY_SNAPSHOT: dict[str, Any] = {"schema": {}, "sizes": {}, "stats": {}}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_dispara_con_overestimacion_10x() -> None:
    """Plan estima 50_000, realidad fue 100 → ratio 500x, dispara."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 1000.0,
            "Plan Rows": 50_000,
            "Plan Width": 100,
            "Actual Startup Time": 0.1,
            "Actual Total Time": 5.0,
            "Actual Rows": 100,
            "Actual Loops": 1,
            "Filter": "(author_id = 42)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is True
    assert detection.confidence == pytest.approx(0.85)
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    match = matches[0]
    assert match["table"] == "posts"
    assert match["plan_rows"] == 50_000
    assert match["actual_rows"] == 100
    assert match["ratio"] == pytest.approx(500.0)
    assert match["direction"] == "overestimated"
    assert match["suggested_sql"] == "ANALYZE posts;"


def test_dispara_con_subestimacion_10x() -> None:
    """Plan estima 10, realidad fue 200_000 → ratio 20_000x, dispara
    como `underestimated` (el caso más peligroso: Postgres pensó "esto
    es chico, hash join cabe en RAM" y leyó una tabla enorme)."""
    raw = {
        "Plan": {
            "Node Type": "Bitmap Heap Scan",
            "Relation Name": "events",
            "Startup Cost": 0.0,
            "Total Cost": 200.0,
            "Plan Rows": 10,
            "Plan Width": 60,
            "Actual Startup Time": 0.5,
            "Actual Total Time": 1200.0,
            "Actual Rows": 200_000,
            "Actual Loops": 1,
            "Recheck Cond": "(user_id = 7)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is True
    match = detection.evidence["matches"][0]
    assert match["direction"] == "underestimated"
    assert match["ratio"] == pytest.approx(20_000.0)
    assert match["node_type"] == "Bitmap Heap Scan"


def test_dispara_en_index_scan_y_index_only_scan() -> None:
    """No solo Seq Scan: stats obsoletas también afectan Index Scan
    (el planner pudo elegir mal el orden de los joins de arriba)."""
    raw = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "comments",
            "Index Name": "idx_comments_post_id",
            "Startup Cost": 0.0,
            "Total Cost": 8.0,
            "Plan Rows": 5,
            "Plan Width": 40,
            "Actual Rows": 90_000,
            "Actual Loops": 1,
            "Index Cond": "(post_id = 1)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is True
    assert detection.evidence["matches"][0]["node_type"] == "Index Scan"


# ---------------------------------------------------------------------------
# Casos negativos
# ---------------------------------------------------------------------------


def test_no_dispara_con_ratio_menor_a_10x() -> None:
    """Ratio 5x — Postgres siempre tiene algo de error, no es stats
    obsoletas. Defensa contra falsos positivos."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 1000.0,
            "Plan Rows": 500,
            "Plan Width": 100,
            "Actual Rows": 100,
            "Actual Loops": 1,
            "Filter": "(active = true)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_actual_rows() -> None:
    """EXPLAIN sin ANALYZE — no podemos comparar contra realidad."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 1000.0,
            "Plan Rows": 50_000,
            "Plan Width": 100,
            "Filter": "(author_id = 42)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is False


def test_no_dispara_en_nodos_join_solo_porque_su_estimacion_es_mala() -> None:
    """Frontera con D18: D2 ignora joins; el error de cardinalidad en
    joins es competencia de D18 (que recomienda CREATE STATISTICS).
    Si en este plan no hay scan con stats obsoletas, D2 calla aunque
    el Hash Join arriba esté mal estimado."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 100.0,
            "Total Cost": 500.0,
            "Plan Rows": 10_000,
            "Plan Width": 100,
            "Actual Rows": 5,  # ratio 2000x pero es un join
            "Actual Loops": 1,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 50,
                    "Actual Rows": 100,  # estimación correcta del scan
                    "Actual Loops": 1,
                },
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Parent Relationship": "Inner",
                    "Startup Cost": 0.0,
                    "Total Cost": 30.0,
                    "Plan Rows": 100,
                    "Plan Width": 50,
                    "Actual Rows": 95,  # estimación correcta del scan
                    "Actual Loops": 1,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is False


def test_no_dispara_sin_scans_en_el_plan() -> None:
    """Plan trivial (Result, Limit, etc.). Nada que comparar."""
    raw = {
        "Plan": {
            "Node Type": "Result",
            "Startup Cost": 0.0,
            "Total Cost": 0.01,
            "Plan Rows": 1,
            "Plan Width": 4,
            "Actual Rows": 1,
            "Actual Loops": 1,
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)
    assert detection.found is False


# ---------------------------------------------------------------------------
# Robustez
# ---------------------------------------------------------------------------


def test_dispara_con_actual_rows_cero_y_overestimacion_total() -> None:
    """Plan esperaba 5000, realidad 0 (filtro super-selectivo no
    capturado en stats). Es el caso más claro de stats obsoletas
    sobre most_common_vals."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "audits",
            "Startup Cost": 0.0,
            "Total Cost": 5000.0,
            "Plan Rows": 5000,
            "Plan Width": 80,
            "Actual Rows": 0,
            "Actual Loops": 1,
            "Filter": "(status = 'deleted'::text)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is True
    match = detection.evidence["matches"][0]
    assert match["direction"] == "overestimated"
    assert match["actual_rows"] == 0


def test_no_dispara_con_actual_rows_cero_y_plan_rows_bajo() -> None:
    """`actual_rows=0` con `plan_rows=3` — Postgres acertó en
    "casi nada", no es stats obsoletas."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "audits",
            "Startup Cost": 0.0,
            "Total Cost": 10.0,
            "Plan Rows": 3,
            "Plan Width": 80,
            "Actual Rows": 0,
            "Actual Loops": 1,
            "Filter": "(status = 'archived'::text)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)
    assert detection.found is False


def test_no_falla_si_relation_name_es_None() -> None:
    """Scans sintéticos (VALUES, function scans envueltos) pueden no
    traer relation_name. Si no podemos recomendar ANALYZE sobre una
    tabla concreta, simplemente no reportamos."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Startup Cost": 0.0,
            "Total Cost": 1000.0,
            "Plan Rows": 50_000,
            "Plan Width": 4,
            "Actual Rows": 1,
            "Actual Loops": 1,
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)
    assert detection.found is False


def test_multiples_scans_problematicos_se_reportan_todos() -> None:
    """Dos scans malos en un mismo plan → dos matches independientes.
    Ejercita la convención `evidence['matches']` en plural."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 100.0,
            "Total Cost": 500.0,
            "Plan Rows": 50,
            "Plan Width": 100,
            "Actual Rows": 50,
            "Actual Loops": 1,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 10_000,
                    "Plan Width": 50,
                    "Actual Rows": 50,  # ratio 200x
                    "Actual Loops": 1,
                    "Filter": "(deleted = false)",
                },
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Parent Relationship": "Inner",
                    "Startup Cost": 0.0,
                    "Total Cost": 30.0,
                    "Plan Rows": 5,
                    "Plan Width": 50,
                    "Actual Rows": 1000,  # ratio 200x
                    "Actual Loops": 1,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is True
    tables = {m["table"] for m in detection.evidence["matches"]}
    assert tables == {"posts", "users"}


# ---------------------------------------------------------------------------
# Frontera: bajo LIMIT el scan se trunca y actual_rows no es comparable
# ---------------------------------------------------------------------------


def test_no_dispara_scan_bajo_limit() -> None:
    """`SELECT … ORDER BY x LIMIT N` trunca el scan: Postgres push-down
    detiene el Index Scan cuando el LIMIT está saciado. `actual_rows`
    refleja el LIMIT, no el universo real de filas; comparar contra
    `plan_rows` produce un overestimate falso.

    Caso S05 de la suite anti-FP: ``SELECT … FROM tags ORDER BY x LIMIT 10``
    donde el Index Scan reportaba plan_rows=6286, actual_rows=10. D2
    debe abstenerse.
    """
    raw = {
        "Plan": {
            "Node Type": "Limit",
            "Plan Rows": 10,
            "Plan Width": 4,
            "Startup Cost": 0.0,
            "Total Cost": 1.0,
            "Actual Startup Time": 0.05,
            "Actual Total Time": 0.10,
            "Actual Rows": 10,
            "Actual Loops": 1,
            "Plans": [
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "tags",
                    "Index Name": "idx_tags_use_count",
                    "Plan Rows": 6286,
                    "Plan Width": 4,
                    "Startup Cost": 0.0,
                    "Total Cost": 200.0,
                    "Actual Startup Time": 0.05,
                    "Actual Total Time": 0.10,
                    "Actual Rows": 10,
                    "Actual Loops": 1,
                }
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_stale_statistics(plan, _EMPTY_SNAPSHOT)

    assert detection.found is False

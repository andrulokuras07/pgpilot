"""Tests del detector D22 — count(*) (o agregación) sobre tabla grande sin WHERE.

Criterio del backlog:
  Hecho cuando: test verde para Q20 (`SELECT count(*) FROM posts`).
  Recomendación incluye `pg_class.reltuples` y/o tabla de contadores.
"""

from __future__ import annotations

from motor import parse_explain
from motor.detectors.count_star_full_table import detect_count_star_full_table

# ---------------------------------------------------------------------------
# Fixtures de snapshot
# ---------------------------------------------------------------------------


def _snapshot_with_large_posts() -> dict:
    """Snapshot con `public.posts` por encima del umbral de tabla grande."""
    return {
        "schema": {"public.posts": {"columns": []}},
        "sizes": {"public.posts": {"estimated_rows": 5_000_000}},
        "stats": {},
    }


def _snapshot_with_small_posts() -> dict:
    """Snapshot con `public.posts` por debajo del umbral."""
    return {
        "schema": {"public.posts": {"columns": []}},
        "sizes": {"public.posts": {"estimated_rows": 1_000}},
        "stats": {},
    }


# ---------------------------------------------------------------------------
# Fixtures de plan
# ---------------------------------------------------------------------------


def _plan_count_star_parallel() -> dict:
    """Forma real que Postgres genera para `SELECT count(*) FROM posts`.

    Con tabla grande, Postgres paraleliza: Aggregate(Plain, Finalize)
    arriba, Gather con Partial Aggregate por debajo, y Seq Scan paralelo
    sobre la tabla.
    """
    return {
        "Plan": {
            "Node Type": "Aggregate",
            "Strategy": "Plain",
            "Partial Mode": "Finalize",
            "Startup Cost": 8492.8,
            "Total Cost": 8492.81,
            "Plan Rows": 1,
            "Plan Width": 8,
            "Plans": [
                {
                    "Node Type": "Gather",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 8492.59,
                    "Total Cost": 8492.8,
                    "Plan Rows": 2,
                    "Plan Width": 8,
                    "Workers Planned": 2,
                    "Plans": [
                        {
                            "Node Type": "Aggregate",
                            "Strategy": "Plain",
                            "Partial Mode": "Partial",
                            "Parent Relationship": "Outer",
                            "Startup Cost": 7492.59,
                            "Total Cost": 7492.6,
                            "Plan Rows": 1,
                            "Plan Width": 8,
                            "Plans": [
                                {
                                    "Node Type": "Seq Scan",
                                    "Relation Name": "posts",
                                    "Parallel Aware": True,
                                    "Parent Relationship": "Outer",
                                    "Startup Cost": 0.0,
                                    "Total Cost": 7000.0,
                                    "Plan Rows": 2_000_000,
                                    "Plan Width": 0,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }


def _plan_count_star_serial() -> dict:
    """Versión serial: Aggregate directo sobre Seq Scan sin Gather."""
    return {
        "Plan": {
            "Node Type": "Aggregate",
            "Strategy": "Plain",
            "Startup Cost": 8000.0,
            "Total Cost": 8000.01,
            "Plan Rows": 1,
            "Plan Width": 8,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 0.0,
                    "Total Cost": 7500.0,
                    "Plan Rows": 5_000_000,
                    "Plan Width": 0,
                }
            ],
        }
    }


def _plan_count_with_where() -> dict:
    """`SELECT count(*) FROM posts WHERE author_id = 1000` — no debe disparar."""
    return {
        "Plan": {
            "Node Type": "Aggregate",
            "Strategy": "Plain",
            "Startup Cost": 100.0,
            "Total Cost": 100.01,
            "Plan Rows": 1,
            "Plan Width": 8,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 99.0,
                    "Plan Rows": 1,
                    "Plan Width": 0,
                    "Filter": "(author_id = 1000)",
                }
            ],
        }
    }


def _plan_count_group_by() -> dict:
    """`SELECT count(*) FROM posts GROUP BY author_id` — strategy=Hashed."""
    return {
        "Plan": {
            "Node Type": "Aggregate",
            "Strategy": "Hashed",
            "Group Key": ["author_id"],
            "Startup Cost": 0.0,
            "Total Cost": 1000.0,
            "Plan Rows": 100,
            "Plan Width": 12,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 500.0,
                    "Plan Rows": 5_000_000,
                    "Plan Width": 4,
                }
            ],
        }
    }


def _plan_count_with_join() -> dict:
    """`SELECT count(*) FROM posts JOIN users ON ...` — descartado por join."""
    return {
        "Plan": {
            "Node Type": "Aggregate",
            "Strategy": "Plain",
            "Startup Cost": 0.0,
            "Total Cost": 10000.0,
            "Plan Rows": 1,
            "Plan Width": 8,
            "Plans": [
                {
                    "Node Type": "Hash Join",
                    "Join Type": "Inner",
                    "Hash Cond": "(p.author_id = u.id)",
                    "Startup Cost": 0.0,
                    "Total Cost": 9000.0,
                    "Plan Rows": 1_000_000,
                    "Plan Width": 0,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "posts",
                            "Startup Cost": 0.0,
                            "Total Cost": 5000.0,
                            "Plan Rows": 5_000_000,
                            "Plan Width": 4,
                        },
                        {
                            "Node Type": "Hash",
                            "Startup Cost": 0.0,
                            "Total Cost": 100.0,
                            "Plan Rows": 100,
                            "Plan Width": 4,
                            "Plans": [
                                {
                                    "Node Type": "Seq Scan",
                                    "Relation Name": "users",
                                    "Startup Cost": 0.0,
                                    "Total Cost": 99.0,
                                    "Plan Rows": 100,
                                    "Plan Width": 4,
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    }


# ---------------------------------------------------------------------------
# Happy path — Q20
# ---------------------------------------------------------------------------


def test_dispara_count_star_paralelo_tabla_grande() -> None:
    """Q20 real: count(*) sobre posts con plan paralelo."""
    plan = parse_explain(_plan_count_star_parallel())
    detection = detect_count_star_full_table(plan, _snapshot_with_large_posts())

    assert detection.found is True
    assert detection.confidence == 0.95
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    m = matches[0]
    assert m["table"] == "public.posts"
    assert m["estimated_rows"] == 5_000_000
    assert m["scan_node_type"] == "Seq Scan"
    # La recomendación menciona pg_class y la tabla de contadores
    alt_text = " ".join(m["suggested_alternatives"])
    assert "pg_class" in alt_text
    assert "contadores" in alt_text.lower()


def test_dispara_count_star_serial() -> None:
    """Aggregate directo sobre Seq Scan (sin Gather) también dispara."""
    plan = parse_explain(_plan_count_star_serial())
    detection = detect_count_star_full_table(plan, _snapshot_with_large_posts())

    assert detection.found is True
    assert detection.evidence["matches"][0]["table"] == "public.posts"


# ---------------------------------------------------------------------------
# Negativos
# ---------------------------------------------------------------------------


def test_no_dispara_count_con_where() -> None:
    """count(*) con filtro WHERE no es el anti-pattern de D22."""
    plan = parse_explain(_plan_count_with_where())
    detection = detect_count_star_full_table(plan, _snapshot_with_large_posts())

    assert detection.found is False


def test_no_dispara_count_con_group_by() -> None:
    """count(*) con GROUP BY no es full-table count (strategy != Plain)."""
    plan = parse_explain(_plan_count_group_by())
    detection = detect_count_star_full_table(plan, _snapshot_with_large_posts())

    assert detection.found is False


def test_no_dispara_count_con_join() -> None:
    """count(*) con JOIN no es el anti-pattern de D22 (la query cruza tablas)."""
    plan = parse_explain(_plan_count_with_join())
    detection = detect_count_star_full_table(plan, _snapshot_with_large_posts())

    assert detection.found is False


def test_no_dispara_tabla_pequena() -> None:
    """count(*) sobre tabla con <100k filas no es un problema serio."""
    plan = parse_explain(_plan_count_star_serial())
    detection = detect_count_star_full_table(plan, _snapshot_with_small_posts())

    assert detection.found is False


def test_no_dispara_sin_aggregate_raiz() -> None:
    """Plan que no es un Aggregate en la raíz no dispara."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 1000.0,
            "Plan Rows": 5_000_000,
            "Plan Width": 100,
        }
    }
    plan = parse_explain(raw)
    detection = detect_count_star_full_table(plan, _snapshot_with_large_posts())

    assert detection.found is False


def test_no_dispara_sin_tabla_en_snapshot() -> None:
    """Si la tabla no aparece en `snapshot["sizes"]`, el detector se abstiene."""
    plan = parse_explain(_plan_count_star_serial())
    snapshot = {"schema": {}, "sizes": {}, "stats": {}}
    detection = detect_count_star_full_table(plan, snapshot)

    assert detection.found is False


# ---------------------------------------------------------------------------
# Frontera: el anti-pattern también aplica a otras agregaciones full-table
# ---------------------------------------------------------------------------


def test_dispara_con_otra_agregacion_full_table() -> None:
    """`SELECT avg(score) FROM posts` es el mismo anti-pattern estructural.

    El detector dispara igual: la forma del plan (Aggregate Plain sobre
    scan sin filter) es idéntica a count(*).
    """
    # Mismo shape de plan; la diferencia es el SELECT clause que el
    # detector no inspecciona — solo mira la estructura del plan.
    plan = parse_explain(_plan_count_star_serial())
    detection = detect_count_star_full_table(plan, _snapshot_with_large_posts())

    assert detection.found is True

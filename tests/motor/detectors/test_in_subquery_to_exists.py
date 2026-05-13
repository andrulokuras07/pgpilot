"""Tests del detector D20 — IN con subquery debería ser EXISTS.

Criterio del backlog:
  Hecho cuando: test verde para Q17
  (`WHERE id IN (SELECT author_id FROM posts ...)`).
  Rewrite propuesto válido (parseable con sqlglot).
"""

from __future__ import annotations

import sqlglot

from motor import parse_explain
from motor.detectors.in_subquery_to_exists import detect_in_subquery_to_exists


# ---------------------------------------------------------------------------
# Helpers de plan
# ---------------------------------------------------------------------------

def _plan_hash_semi_join() -> dict:
    """Plan sintético con Hash Join de tipo Semi — lo que Postgres genera
    para IN (SELECT ...) no correlacionado con tabla grande."""
    return {
        "Plan": {
            "Node Type": "Hash Join",
            "Join Type": "Semi",
            "Hash Cond": "(users.id = posts.author_id)",
            "Startup Cost": 0.0,
            "Total Cost": 15000.0,
            "Plan Rows": 500,
            "Plan Width": 8,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Startup Cost": 0.0,
                    "Total Cost": 5000.0,
                    "Plan Rows": 10000,
                    "Plan Width": 8,
                },
                {
                    "Node Type": "Hash",
                    "Startup Cost": 0.0,
                    "Total Cost": 9000.0,
                    "Plan Rows": 5000,
                    "Plan Width": 4,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "posts",
                            "Startup Cost": 0.0,
                            "Total Cost": 8000.0,
                            "Plan Rows": 5000,
                            "Plan Width": 4,
                            "Filter": "(created_at > (now() - '7 days'::interval))",
                        }
                    ],
                },
            ],
        }
    }


def _plan_nested_loop_semi_join() -> dict:
    """Plan con Nested Loop Semi (alternativa menos común pero válida)."""
    return {
        "Plan": {
            "Node Type": "Nested Loop",
            "Join Type": "Semi",
            "Startup Cost": 0.0,
            "Total Cost": 5000.0,
            "Plan Rows": 100,
            "Plan Width": 8,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Startup Cost": 0.0,
                    "Total Cost": 2000.0,
                    "Plan Rows": 200,
                    "Plan Width": 8,
                },
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 10.0,
                    "Plan Rows": 1,
                    "Plan Width": 4,
                },
            ],
        }
    }


def _plan_seq_scan_only() -> dict:
    """Plan sin Semi Join — para tests negativos."""
    return {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 100,
            "Plan Width": 8,
        }
    }


def _plan_inner_join() -> dict:
    """Plan con Hash Join Inner (no semi) — no debe disparar."""
    return {
        "Plan": {
            "Node Type": "Hash Join",
            "Join Type": "Inner",
            "Hash Cond": "(t1.id = t2.fk)",
            "Startup Cost": 0.0,
            "Total Cost": 1000.0,
            "Plan Rows": 100,
            "Plan Width": 8,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "t1",
                    "Startup Cost": 0.0,
                    "Total Cost": 500.0,
                    "Plan Rows": 100,
                    "Plan Width": 8,
                },
                {
                    "Node Type": "Hash",
                    "Startup Cost": 0.0,
                    "Total Cost": 400.0,
                    "Plan Rows": 100,
                    "Plan Width": 4,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "t2",
                            "Startup Cost": 0.0,
                            "Total Cost": 300.0,
                            "Plan Rows": 100,
                            "Plan Width": 4,
                        }
                    ],
                },
            ],
        }
    }


# ---------------------------------------------------------------------------
# Happy path — Q17
# ---------------------------------------------------------------------------


def test_dispara_q17_in_subquery_con_semi_join() -> None:
    """Q17: IN (SELECT ...) no correlacionado + Hash Semi Join en el plan."""
    sql = (
        "SELECT id FROM users "
        "WHERE id IN ("
        "SELECT author_id FROM posts WHERE created_at > NOW() - INTERVAL '7 days'"
        ")"
    )
    plan = parse_explain(_plan_hash_semi_join())
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    assert detection.found is True
    assert detection.confidence == 0.9
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    m = matches[0]
    assert m["column"] == "id"
    assert m["inner_table"] == "posts"
    assert m["has_semi_join_in_plan"] is True


def test_rewrite_q17_es_parseable_y_usa_exists() -> None:
    """El suggested_rewrite de Q17 es SQL válido con EXISTS."""
    sql = (
        "SELECT id FROM users "
        "WHERE id IN ("
        "SELECT author_id FROM posts WHERE created_at > NOW() - INTERVAL '7 days'"
        ")"
    )
    plan = parse_explain(_plan_hash_semi_join())
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    assert detection.found is True
    rewrite = detection.evidence["matches"][0]["suggested_rewrite"]

    parsed = sqlglot.parse_one(rewrite, dialect="postgres")
    assert parsed is not None

    # Debe contener EXISTS en algún lugar
    assert "EXISTS" in rewrite.upper()

    # No debe contener IN (SELECT ...)
    assert " IN " not in rewrite.upper() or "NOT IN" not in rewrite.upper()


def test_dispara_con_nested_loop_semi_join() -> None:
    """Nested Loop Semi Join también dispara D20."""
    sql = "SELECT id FROM users WHERE id IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_nested_loop_semi_join())
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    assert detection.found is True
    assert detection.evidence["matches"][0]["has_semi_join_in_plan"] is True


# ---------------------------------------------------------------------------
# Negativos — no debe disparar
# ---------------------------------------------------------------------------


def test_no_dispara_sin_sql() -> None:
    """Sin SQL el detector se abstiene."""
    plan = parse_explain(_plan_hash_semi_join())
    detection = detect_in_subquery_to_exists(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_semi_join_en_plan() -> None:
    """SQL tiene IN (SELECT ...) pero el plan no tiene Semi Join → no dispara.

    Sin la señal del plan, D20 prefiere abstenerse (evita FP con IN
    sobre tablas pequeñas que nunca generarían Semi Join)."""
    sql = "SELECT id FROM users WHERE id IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_seq_scan_only())
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    assert detection.found is False


def test_no_dispara_in_con_lista_literal() -> None:
    """IN con lista literal (no subquery) + plan Semi Join no dispara D20."""
    sql = "SELECT id FROM users WHERE id IN (1, 2, 3)"
    plan = parse_explain(_plan_hash_semi_join())
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    assert detection.found is False


def test_no_dispara_inner_join_en_plan() -> None:
    """Hash Join Inner (no Semi) + IN subquery no dispara D20."""
    sql = "SELECT id FROM users WHERE id IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_inner_join())
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    assert detection.found is False


def test_no_dispara_subquery_correlacionada() -> None:
    """Subquery que referencia la tabla outer (correlacionada) → no dispara D20.

    D7 (detect_correlated_subquery) cubre este caso vía SubPlan.
    D20 solo cubre subqueries NO correlacionadas.
    """
    sql = (
        "SELECT id FROM users "
        "WHERE id IN ("
        "SELECT post_id FROM comments WHERE comments.user_id = users.id"
        ")"
    )
    plan = parse_explain(_plan_hash_semi_join())
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    assert detection.found is False


def test_no_dispara_not_in_subquery() -> None:
    """NOT IN (SELECT ...) es un patrón distinto (D21) — D20 no dispara."""
    sql = "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_hash_semi_join())
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    assert detection.found is False


def test_no_dispara_sql_invalido() -> None:
    """SQL no parseable → abstención silenciosa."""
    plan = parse_explain(_plan_hash_semi_join())
    detection = detect_in_subquery_to_exists(plan, {}, sql="NOT VALID SQL !!!")

    assert detection.found is False


# ---------------------------------------------------------------------------
# Frontera con otros detectores
# ---------------------------------------------------------------------------


def test_no_se_solapa_con_d7_subplan() -> None:
    """Plan con SubPlan (de D7 para subqueries correlacionadas) no dispara D20.

    En el plan de un SubPlan correlacionado no hay Hash Join Semi,
    así que D20 siempre se abstiene cuando D7 debe disparar.
    """
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 200.0,
            "Plan Rows": 100,
            "Plan Width": 8,
            "Filter": "(id = (SubPlan 1))",
            "Plans": [
                {
                    "Node Type": "Aggregate",
                    "Strategy": "Plain",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 1,
                    "Plan Width": 4,
                    "Subplan Name": "SubPlan 1",
                    "Parent Relationship": "SubPlan",
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "posts",
                            "Startup Cost": 0.0,
                            "Total Cost": 30.0,
                            "Plan Rows": 10,
                            "Plan Width": 4,
                        }
                    ],
                }
            ],
        }
    }
    plan = parse_explain(raw)
    sql = "SELECT id FROM users WHERE id IN (SELECT author_id FROM posts WHERE post_id = users.id)"
    detection = detect_in_subquery_to_exists(plan, {}, sql=sql)

    # No hay Semi Join → D20 no dispara
    assert detection.found is False

"""Tests del detector D8 — Nested Loop con outer grande.

Criterio del backlog:
  Hecho cuando: detector pasa test sobre plan plantado, documentado.
"""

from __future__ import annotations

from motor import detect_nested_loop_large_outer, parse_explain


def test_dispara_con_outer_grande_marcado_explicitamente() -> None:
    """Nested Loop con hijo Outer >10k filas → dispara."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 5000.0,
            "Plan Rows": 50000,
            "Plan Width": 20,
            "Join Type": "Inner",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 0.0,
                    "Total Cost": 1000.0,
                    "Plan Rows": 50000,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "users",
                    "Parent Relationship": "Inner",
                    "Index Name": "users_pkey",
                    "Startup Cost": 0.0,
                    "Total Cost": 0.1,
                    "Plan Rows": 1,
                    "Plan Width": 10,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_nested_loop_large_outer(plan, {})

    assert detection.found is True
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    assert matches[0]["outer_table"] == "posts"
    assert matches[0]["outer_rows"] == 50_000
    assert matches[0]["join_type"] == "Inner"


def test_no_dispara_con_outer_pequeno() -> None:
    """Nested Loop con outer <10k → no dispara (suele ser óptimo)."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 500,
            "Plan Width": 20,
            "Join Type": "Inner",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "small_table",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 500,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "users",
                    "Parent Relationship": "Inner",
                    "Index Name": "users_pkey",
                    "Startup Cost": 0.0,
                    "Total Cost": 0.1,
                    "Plan Rows": 1,
                    "Plan Width": 10,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_nested_loop_large_outer(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_nested_loop() -> None:
    """Hash Join con outer enorme → no aplica a D8 (el join ya es bueno)."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 0.0,
            "Total Cost": 5000.0,
            "Plan Rows": 50000,
            "Plan Width": 20,
            "Hash Cond": "(t1.id = t2.fk)",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "huge_table",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 0.0,
                    "Total Cost": 1000.0,
                    "Plan Rows": 1_000_000,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "Hash",
                    "Parent Relationship": "Inner",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 10,
                    "Plans": [],
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_nested_loop_large_outer(plan, {})
    assert detection.found is False


def test_usa_actual_rows_cuando_estan_disponibles() -> None:
    """Si el plan trae actual_rows, se usan en lugar de plan_rows."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 5000.0,
            "Plan Rows": 100,  # estimado MAL: 100
            "Plan Width": 20,
            "Actual Rows": 50000,  # real: 50k
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 0.0,
                    "Total Cost": 1000.0,
                    "Plan Rows": 100,  # estimado MAL
                    "Plan Width": 10,
                    "Actual Rows": 50000,  # real grande
                },
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "users",
                    "Parent Relationship": "Inner",
                    "Index Name": "users_pkey",
                    "Startup Cost": 0.0,
                    "Total Cost": 0.1,
                    "Plan Rows": 1,
                    "Plan Width": 10,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_nested_loop_large_outer(plan, {})

    assert detection.found is True
    match = detection.evidence["matches"][0]
    assert match["outer_rows"] == 50_000
    assert match["outer_rows_source"] == "actual"


def test_outer_inferido_como_primer_hijo_si_no_marcado() -> None:
    """Sin Parent Relationship, el primer hijo es el outer por convención."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 5000.0,
            "Plan Rows": 50000,
            "Plan Width": 20,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    # NOTA: sin "Parent Relationship"
                    "Startup Cost": 0.0,
                    "Total Cost": 1000.0,
                    "Plan Rows": 50000,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "users",
                    "Index Name": "users_pkey",
                    "Startup Cost": 0.0,
                    "Total Cost": 0.1,
                    "Plan Rows": 1,
                    "Plan Width": 10,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_nested_loop_large_outer(plan, {})

    assert detection.found is True
    assert detection.evidence["matches"][0]["outer_table"] == "posts"

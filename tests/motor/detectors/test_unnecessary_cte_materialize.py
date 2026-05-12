"""Tests del detector D12 — CTE materializada innecesariamente.

Criterio del backlog:
  Hecho cuando: detector pasa test, documentado.
"""

from __future__ import annotations

import pytest

from motor import parse_explain
from motor.detectors.unnecessary_cte_materialize import (
    detect_unnecessary_cte_materialize,
)

# snapshot vacío: D12 no usa el snapshot (lo recibe por uniformidad)
_EMPTY_SNAP: dict = {}


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_dispara_con_cte_referenciada_una_sola_vez() -> None:
    """CTE Scan sin recursión y referenciada una vez → candidata a NOT MATERIALIZED."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 10.0,
            "Total Cost": 200.0,
            "Plan Rows": 100,
            "Plan Width": 50,
            "Plans": [
                {
                    "Node Type": "CTE Scan",
                    "CTE Name": "recent_posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 10.0,
                    "Plan Rows": 50,
                    "Plan Width": 20,
                },
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Startup Cost": 0.0,
                    "Total Cost": 100.0,
                    "Plan Rows": 200,
                    "Plan Width": 30,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_unnecessary_cte_materialize(plan, _EMPTY_SNAP)

    assert detection.found is True
    assert detection.confidence == pytest.approx(0.85)
    match = detection.evidence["matches"][0]
    assert match["cte_name"] == "recent_posts"
    assert match["reference_count"] == 1


def test_dispara_con_multiples_ctes_distintas_cada_una_una_vez() -> None:
    """Dos CTEs distintas, cada una referenciada una vez → dos matches."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Plans": [
                {
                    "Node Type": "CTE Scan",
                    "CTE Name": "cte_a",
                    "Startup Cost": 0.0,
                    "Total Cost": 20.0,
                    "Plan Rows": 10,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "CTE Scan",
                    "CTE Name": "cte_b",
                    "Startup Cost": 0.0,
                    "Total Cost": 30.0,
                    "Plan Rows": 5,
                    "Plan Width": 10,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_unnecessary_cte_materialize(plan, _EMPTY_SNAP)

    assert detection.found is True
    cte_names = {m["cte_name"] for m in detection.evidence["matches"]}
    assert cte_names == {"cte_a", "cte_b"}


# ---------------------------------------------------------------------------
# Casos negativos
# ---------------------------------------------------------------------------

def test_no_dispara_sin_cte_scan() -> None:
    """Plan sin CTE Scan: no hay CTE materializada."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 500.0,
            "Plan Rows": 1000,
            "Plan Width": 100,
        }
    }
    plan = parse_explain(raw)
    detection = detect_unnecessary_cte_materialize(plan, _EMPTY_SNAP)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_cuando_cte_referenciada_multiple_veces() -> None:
    """CTE referenciada 2 veces: la materialización es útil (evita recalcular)."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Plans": [
                {
                    "Node Type": "CTE Scan",
                    "CTE Name": "expensive_cte",
                    "Startup Cost": 0.0,
                    "Total Cost": 20.0,
                    "Plan Rows": 10,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "CTE Scan",
                    "CTE Name": "expensive_cte",
                    "Startup Cost": 0.0,
                    "Total Cost": 20.0,
                    "Plan Rows": 10,
                    "Plan Width": 10,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_unnecessary_cte_materialize(plan, _EMPTY_SNAP)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_con_recursive_union() -> None:
    """Plan con Recursive Union: CTE recursiva, no recomendar NOT MATERIALIZED."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 10.0,
            "Total Cost": 200.0,
            "Plan Rows": 100,
            "Plan Width": 50,
            "Plans": [
                {
                    "Node Type": "CTE Scan",
                    "CTE Name": "org_tree",
                    "Startup Cost": 0.0,
                    "Total Cost": 10.0,
                    "Plan Rows": 50,
                    "Plan Width": 20,
                },
                {
                    "Node Type": "Recursive Union",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 50,
                    "Plan Width": 20,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "org",
                            "Startup Cost": 0.0,
                            "Total Cost": 10.0,
                            "Plan Rows": 10,
                            "Plan Width": 20,
                        }
                    ],
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_unnecessary_cte_materialize(plan, _EMPTY_SNAP)

    assert detection.found is False


def test_no_dispara_cuando_una_cte_es_buena_y_otra_recursiva() -> None:
    """Cuando hay Recursive Union en el plan, ningún CTE Scan se reporta."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 300.0,
            "Plan Rows": 30,
            "Plan Width": 50,
            "Plans": [
                {
                    "Node Type": "CTE Scan",
                    "CTE Name": "simple_cte",
                    "Startup Cost": 0.0,
                    "Total Cost": 10.0,
                    "Plan Rows": 10,
                    "Plan Width": 20,
                },
                {
                    "Node Type": "Recursive Union",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 20,
                    "Plan Width": 20,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "tree",
                            "Startup Cost": 0.0,
                            "Total Cost": 10.0,
                            "Plan Rows": 5,
                            "Plan Width": 10,
                        }
                    ],
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_unnecessary_cte_materialize(plan, _EMPTY_SNAP)

    # Aunque `simple_cte` se usa solo una vez, el plan tiene Recursive Union
    # y el detector es conservador: no reporta nada.
    assert detection.found is False


# ---------------------------------------------------------------------------
# Robustez
# ---------------------------------------------------------------------------

def test_cte_name_none_no_rompe() -> None:
    """CTE Scan sin CTE Name (edge case del parser) no rompe el detector."""
    raw = {
        "Plan": {
            "Node Type": "CTE Scan",
            "Startup Cost": 0.0,
            "Total Cost": 10.0,
            "Plan Rows": 5,
            "Plan Width": 10,
            # Sin "CTE Name" → node.cte_name = None
        }
    }
    plan = parse_explain(raw)
    # No debe lanzar; el detector maneja cte_name=None como cadena vacía.
    detection = detect_unnecessary_cte_materialize(plan, _EMPTY_SNAP)

    # cte_name="" referenciado una vez sin recursive → dispara
    # (el recomendador luego gestionará el nombre vacío)
    assert isinstance(detection.found, bool)


def test_plan_profundo_con_cte_scan_anidado() -> None:
    """CTE Scan anidado varios niveles: find_nodes lo localiza en DFS."""
    raw = {
        "Plan": {
            "Node Type": "Aggregate",
            "Startup Cost": 0.0,
            "Total Cost": 500.0,
            "Plan Rows": 1,
            "Plan Width": 8,
            "Plans": [
                {
                    "Node Type": "Hash Join",
                    "Startup Cost": 0.0,
                    "Total Cost": 490.0,
                    "Plan Rows": 1000,
                    "Plan Width": 8,
                    "Plans": [
                        {
                            "Node Type": "CTE Scan",
                            "CTE Name": "deep_cte",
                            "Startup Cost": 0.0,
                            "Total Cost": 100.0,
                            "Plan Rows": 500,
                            "Plan Width": 8,
                        },
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "users",
                            "Startup Cost": 0.0,
                            "Total Cost": 200.0,
                            "Plan Rows": 1000,
                            "Plan Width": 8,
                        },
                    ],
                }
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_unnecessary_cte_materialize(plan, _EMPTY_SNAP)

    assert detection.found is True
    assert detection.evidence["matches"][0]["cte_name"] == "deep_cte"

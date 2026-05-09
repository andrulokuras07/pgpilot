"""Tests del parser de EXPLAIN (B7).

Verifica que `parse_explain`:

1. Acepta las tres formas de entrada (str JSON, list, dict).
2. Construye un árbol con la forma correcta para varios planes
   reales de AppDB (criterio de B7: 5+ planes).
3. Extrae correctamente costos, filas estimadas/reales y tiempos.
4. Preserva la jerarquía padre-hijo (children como tupla).
5. Maneja EXPLAIN sin ANALYZE (campos `actual_*` quedan en None).
6. Lanza errores claros sobre input mal formado.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from motor.parser import ExplainResult, PlanNode, parse_explain

# --- entrada en distintas formas -----------------------------------


def test_acepta_dict_directo(plan_index_scan: list[dict[str, Any]]) -> None:
    # plan_index_scan es la lista que devuelve psql
    result = parse_explain(plan_index_scan[0])
    assert isinstance(result, ExplainResult)
    assert result.root.node_type == "Index Scan"


def test_acepta_lista_postgres(plan_index_scan: list[dict[str, Any]]) -> None:
    # forma típica al hacer cur.fetchone()[0]
    result = parse_explain(plan_index_scan)
    assert result.root.node_type == "Index Scan"


def test_acepta_string_json(plan_index_scan: list[dict[str, Any]]) -> None:
    raw = json.dumps(plan_index_scan)
    result = parse_explain(raw)
    assert result.root.node_type == "Index Scan"


# --- ≥5 planes parsean correctamente (criterio de B7) --------------


def test_cinco_o_mas_planes_se_parsean_sin_error(
    all_fixture_paths: list[Path],
) -> None:
    """Hecho cuando: 'un test parsea 5 planes de EXPLAIN distintos y
    la estructura tiene la forma correcta'."""
    assert len(all_fixture_paths) >= 5
    for path in all_fixture_paths:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        result = parse_explain(data)
        # forma correcta: hay raíz, tiene tipo, costos no negativos
        assert isinstance(result.root, PlanNode)
        assert result.root.node_type
        assert result.root.total_cost >= 0
        assert result.root.plan_rows >= 0


# --- extracción de campos comunes ----------------------------------


def test_index_scan_extrae_relacion_y_costo(
    plan_index_scan: list[dict[str, Any]],
) -> None:
    result = parse_explain(plan_index_scan)
    root = result.root
    assert root.node_type == "Index Scan"
    assert root.relation_name == "users"
    assert root.alias == "users"
    assert root.index_name == "idx_users_email"
    assert root.scan_direction == "Forward"
    # costos del fixture (ver 01_index_scan.json)
    assert root.startup_cost == pytest.approx(0.41)
    assert root.total_cost == pytest.approx(8.43)
    assert root.plan_rows == 1
    # ANALYZE devuelve campos actual_*
    assert root.actual_loops == 1
    assert root.actual_rows == 0


def test_planning_y_execution_time_top_level(
    plan_index_scan: list[dict[str, Any]],
) -> None:
    result = parse_explain(plan_index_scan)
    assert result.planning_time_ms == pytest.approx(2.218)
    assert result.execution_time_ms == pytest.approx(0.695)


# --- jerarquía -----------------------------------------------------


def test_hijos_son_tupla_y_preservan_orden(
    plan_limit_nested_loop: list[dict[str, Any]],
) -> None:
    """Plan: Limit > Nested Loop > [Index Scan(users), Gather > Seq Scan(posts)]"""
    result = parse_explain(plan_limit_nested_loop)
    limit = result.root
    assert limit.node_type == "Limit"
    assert isinstance(limit.children, tuple)
    assert len(limit.children) == 1

    nested_loop = limit.children[0]
    assert nested_loop.node_type == "Nested Loop"
    assert len(nested_loop.children) == 2

    outer, inner = nested_loop.children
    assert outer.node_type == "Index Scan"
    assert outer.relation_name == "users"
    assert outer.parent_relationship == "Outer"
    assert inner.node_type == "Gather"
    assert inner.parent_relationship == "Inner"


def test_plan_node_es_inmutable(plan_index_scan: list[dict[str, Any]]) -> None:
    """`frozen=True` debe impedir mutaciones accidentales en los
    detectores."""
    root = parse_explain(plan_index_scan).root
    with pytest.raises(Exception):
        root.node_type = "Seq Scan"  # type: ignore[misc]


# --- EXPLAIN sin ANALYZE -------------------------------------------


def test_explain_sin_analyze_deja_actual_fields_en_none() -> None:
    plan_estatico = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Alias": "users",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 50,
            "Plan Width": 200,
        }
    }
    result = parse_explain(plan_estatico)
    assert result.root.actual_rows is None
    assert result.root.actual_total_time is None
    assert result.planning_time_ms is None
    assert result.execution_time_ms is None


# --- errores claros ------------------------------------------------


def test_input_vacio_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="vacío"):
        parse_explain([])


def test_input_sin_plan_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="'Plan'"):
        parse_explain({"Planning Time": 1.0})


def test_nodo_sin_node_type_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="Node Type"):
        parse_explain({"Plan": {"Total Cost": 0.0}})


def test_input_no_objeto_lanza_value_error() -> None:
    with pytest.raises(ValueError, match="objeto JSON"):
        parse_explain(42)  # type: ignore[arg-type]

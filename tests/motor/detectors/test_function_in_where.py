"""Tests del detector D5 — Función no-immutable en WHERE.

Criterio del backlog:
  Hecho cuando: detector pasa test, documentado.
"""

from __future__ import annotations

from motor import detect_function_in_where, parse_explain


def test_dispara_con_lower_en_filtro() -> None:
    """Filtro `lower(email) = 'x'` — función impide uso de índice btree."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 1,
            "Plan Width": 10,
            "Filter": "(lower((email)::text) = 'test@example.com'::text)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_function_in_where(plan, {})

    assert detection.found is True
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    assert matches[0]["function"] == "lower"
    assert matches[0]["table"] == "users"


def test_dispara_con_upper_en_filtro() -> None:
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 1,
            "Plan Width": 10,
            "Filter": "(upper(title) = 'HELLO')",
        }
    }
    plan = parse_explain(raw)
    detection = detect_function_in_where(plan, {})

    assert detection.found is True
    assert detection.evidence["matches"][0]["function"] == "upper"


def test_dispara_con_date_trunc() -> None:
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "events",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 1,
            "Plan Width": 10,
            "Filter": "(date_trunc('month', created_at) = '2024-01-01')",
        }
    }
    plan = parse_explain(raw)
    detection = detect_function_in_where(plan, {})

    assert detection.found is True
    assert detection.evidence["matches"][0]["function"] == "date_trunc"


def test_no_dispara_sin_funcion() -> None:
    """Filtro simple de igualdad — no hay función."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 1,
            "Plan Width": 10,
            "Filter": "(author_id = 5)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_function_in_where(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_filtro() -> None:
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 1,
            "Plan Width": 10,
        }
    }
    plan = parse_explain(raw)
    detection = detect_function_in_where(plan, {})
    assert detection.found is False


def test_dispara_con_extract_en_filtro() -> None:
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 1,
            "Plan Width": 10,
            "Filter": "(extract(year FROM created_at) = 2024)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_function_in_where(plan, {})

    assert detection.found is True
    assert detection.evidence["matches"][0]["function"] == "extract"


def test_multiples_funciones_en_un_filtro() -> None:
    """Filtro con dos funciones diferentes."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 1,
            "Plan Width": 10,
            "Filter": "((lower(email) = 'x') AND (trim(name) = 'y'))",
        }
    }
    plan = parse_explain(raw)
    detection = detect_function_in_where(plan, {})

    assert detection.found is True
    assert len(detection.evidence["matches"]) == 2
    funcs = {m["function"] for m in detection.evidence["matches"]}
    assert funcs == {"lower", "trim"}

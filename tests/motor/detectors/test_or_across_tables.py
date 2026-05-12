"""Tests del detector D6 — OR sobre columnas de tablas distintas.

Criterio del backlog:
  Hecho cuando: detector pasa test, documentado.
"""

from __future__ import annotations

from motor import detect_or_across_tables, parse_explain


def test_dispara_con_or_cruzando_tablas_en_join() -> None:
    """Filter con OR que referencia columnas de dos tablas distintas."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Hash Cond": "(t1.id = t2.post_id)",
            "Filter": "((t1.status = 1) OR (t2.category = 'news'))",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Alias": "t1",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "Hash",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 10,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "comments",
                            "Alias": "t2",
                            "Startup Cost": 0.0,
                            "Total Cost": 50.0,
                            "Plan Rows": 100,
                            "Plan Width": 10,
                        }
                    ],
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_or_across_tables(plan, {})

    assert detection.found is True
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    assert set(matches[0]["tables"]) == {"t1", "t2"}


def test_no_dispara_con_or_misma_tabla() -> None:
    """OR sobre columnas de la misma tabla — no es el anti-pattern."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Filter": "((users.status = 1) OR (users.role = 'admin'))",
        }
    }
    plan = parse_explain(raw)
    detection = detect_or_across_tables(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_or() -> None:
    """Filtro AND sin OR — no es el anti-pattern."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Hash Cond": "(t1.id = t2.post_id)",
            "Filter": "((t1.status = 1) AND (t2.category = 'news'))",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Alias": "t1",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "Hash",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 10,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "comments",
                            "Alias": "t2",
                            "Startup Cost": 0.0,
                            "Total Cost": 50.0,
                            "Plan Rows": 100,
                            "Plan Width": 10,
                        }
                    ],
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_or_across_tables(plan, {})
    assert detection.found is False


def test_no_dispara_sin_filtro() -> None:
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Hash Cond": "(t1.id = t2.post_id)",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Alias": "t1",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 10,
                },
                {
                    "Node Type": "Hash",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 10,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "comments",
                            "Alias": "t2",
                            "Startup Cost": 0.0,
                            "Total Cost": 50.0,
                            "Plan Rows": 100,
                            "Plan Width": 10,
                        }
                    ],
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_or_across_tables(plan, {})
    assert detection.found is False


def test_no_dispara_con_or_sin_tabla_cualificada() -> None:
    """OR con columnas sin prefijo de tabla — no hay evidencia de cruce."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Filter": "((status = 1) OR (role = 'admin'))",
        }
    }
    plan = parse_explain(raw)
    detection = detect_or_across_tables(plan, {})
    assert detection.found is False

"""Tests del detector D7 — Subquery correlacionada.

Criterio del backlog:
  Hecho cuando: detector pasa test, documentado.
"""

from __future__ import annotations

from motor import detect_correlated_subquery, parse_explain


def test_dispara_con_subplan_correlacionado() -> None:
    """Plan con un SubPlan — indica subquery correlacionada."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 100,
            "Plan Width": 10,
            "Filter": "(salary > (SubPlan 1))",
            "Plans": [
                {
                    "Node Type": "Aggregate",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 1,
                    "Plan Width": 8,
                    "Strategy": "Plain",
                    "Subplan Name": "SubPlan 1",
                    "Parent Relationship": "SubPlan",
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "salaries",
                            "Startup Cost": 0.0,
                            "Total Cost": 30.0,
                            "Plan Rows": 10,
                            "Plan Width": 8,
                            "Filter": "(department_id = users.department_id)",
                        }
                    ],
                }
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_correlated_subquery(plan, {})

    assert detection.found is True
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    assert matches[0]["subplan_name"] == "SubPlan 1"
    assert matches[0]["node_type"] == "Aggregate"


def test_no_dispara_sin_subplan() -> None:
    """Plan simple sin subquery."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 100,
            "Plan Width": 10,
            "Filter": "(status = 1)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_correlated_subquery(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_con_cte_scan() -> None:
    """CTE Scan tiene cte_name pero no subplan_name con 'SubPlan'."""
    raw = {
        "Plan": {
            "Node Type": "CTE Scan",
            "Relation Name": "my_cte",
            "CTE Name": "my_cte",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 10,
            "Plan Width": 10,
        }
    }
    plan = parse_explain(raw)
    detection = detect_correlated_subquery(plan, {})
    assert detection.found is False


def test_dispara_con_multiples_subplans() -> None:
    """Plan con dos SubPlans distintos."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "orders",
            "Startup Cost": 0.0,
            "Total Cost": 200.0,
            "Plan Rows": 100,
            "Plan Width": 10,
            "Filter": "((amount > (SubPlan 1)) AND (qty < (SubPlan 2)))",
            "Plans": [
                {
                    "Node Type": "Aggregate",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 1,
                    "Plan Width": 8,
                    "Strategy": "Plain",
                    "Subplan Name": "SubPlan 1",
                    "Parent Relationship": "SubPlan",
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "avg_amounts",
                            "Startup Cost": 0.0,
                            "Total Cost": 30.0,
                            "Plan Rows": 10,
                            "Plan Width": 8,
                        }
                    ],
                },
                {
                    "Node Type": "Aggregate",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 1,
                    "Plan Width": 8,
                    "Strategy": "Plain",
                    "Subplan Name": "SubPlan 2",
                    "Parent Relationship": "SubPlan",
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "thresholds",
                            "Startup Cost": 0.0,
                            "Total Cost": 30.0,
                            "Plan Rows": 10,
                            "Plan Width": 8,
                        }
                    ],
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_correlated_subquery(plan, {})

    assert detection.found is True
    assert len(detection.evidence["matches"]) == 2
    names = {m["subplan_name"] for m in detection.evidence["matches"]}
    assert names == {"SubPlan 1", "SubPlan 2"}


def test_no_dispara_con_initplan() -> None:
    """InitPlan es subquery no correlacionada — se ejecuta una sola vez.
    No contiene 'SubPlan' en el nombre."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 100,
            "Plan Width": 10,
            "Filter": "(salary > (InitPlan 1))",
            "Plans": [
                {
                    "Node Type": "Aggregate",
                    "Startup Cost": 0.0,
                    "Total Cost": 30.0,
                    "Plan Rows": 1,
                    "Plan Width": 8,
                    "Strategy": "Plain",
                    "Subplan Name": "InitPlan 1",
                    "Parent Relationship": "InitPlan",
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "salaries",
                            "Startup Cost": 0.0,
                            "Total Cost": 20.0,
                            "Plan Rows": 100,
                            "Plan Width": 8,
                        }
                    ],
                }
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_correlated_subquery(plan, {})
    assert detection.found is False

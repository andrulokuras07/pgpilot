"""Tests del detector D18 — Error de cardinalidad en JOIN multi-condición.

Criterio del backlog:
  Hecho cuando: test verde para Q13 (posts JOIN users con AND sobre
  is_verified, is_active, is_deleted). Recomendación incluye nombres
  reales de columnas y tabla.
"""

from __future__ import annotations

from typing import Any

import pytest

from motor import detect_cardinality_misestimate, parse_explain


@pytest.fixture
def snapshot_users_y_posts_con_bools() -> dict[str, Any]:
    """`users` con bools correlacionados (`is_verified`, `is_active`) y
    `posts` con `is_deleted`. Replica el shape de Q13."""
    return {
        "schema": {
            "public.users": {
                "schema": "public",
                "name": "users",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "bigint",
                        "is_nullable": False,
                        "ordinal_position": 1,
                    },
                    {
                        "name": "is_verified",
                        "data_type": "boolean",
                        "is_nullable": False,
                        "ordinal_position": 2,
                    },
                    {
                        "name": "is_active",
                        "data_type": "boolean",
                        "is_nullable": False,
                        "ordinal_position": 3,
                    },
                ],
                "indexes": [],
                "foreign_keys": [],
            },
            "public.posts": {
                "schema": "public",
                "name": "posts",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "bigint",
                        "is_nullable": False,
                        "ordinal_position": 1,
                    },
                    {
                        "name": "author_id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "ordinal_position": 2,
                    },
                    {
                        "name": "is_deleted",
                        "data_type": "boolean",
                        "is_nullable": False,
                        "ordinal_position": 3,
                    },
                ],
                "indexes": [],
                "foreign_keys": [],
            },
        },
        "sizes": {
            "public.users": {
                "estimated_rows": 200_000,
                "total_bytes": 30_000_000,
                "category": "large",
            },
            "public.posts": {
                "estimated_rows": 2_000_000,
                "total_bytes": 200_000_000,
                "category": "large",
            },
        },
        "stats": {},
    }


def test_dispara_q13_hash_join_mal_estimado(
    snapshot_users_y_posts_con_bools,
) -> None:
    """Q13: Hash Join con plan_rows=1 vs actual_rows=50000 (50000x sobre).
    El scan de users tiene `(is_verified AND is_active)`."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 100.0,
            "Total Cost": 5000.0,
            "Plan Rows": 1,
            "Plan Width": 100,
            "Actual Rows": 50_000,
            "Actual Loops": 1,
            "Hash Cond": "(p.author_id = u.id)",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Parent Relationship": "Outer",
                    "Relation Name": "posts",
                    "Alias": "p",
                    "Startup Cost": 0.0,
                    "Total Cost": 1000.0,
                    "Plan Rows": 1_000_000,
                    "Plan Width": 50,
                    "Actual Rows": 1_000_000,
                    "Filter": "(NOT is_deleted)",
                },
                {
                    "Node Type": "Hash",
                    "Parent Relationship": "Inner",
                    "Startup Cost": 50.0,
                    "Total Cost": 100.0,
                    "Plan Rows": 1,
                    "Plan Width": 50,
                    "Actual Rows": 100,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Parent Relationship": "Outer",
                            "Relation Name": "users",
                            "Alias": "u",
                            "Startup Cost": 0.0,
                            "Total Cost": 50.0,
                            "Plan Rows": 1,
                            "Plan Width": 50,
                            "Actual Rows": 100,
                            "Filter": "(is_verified AND is_active)",
                        }
                    ],
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_cardinality_misestimate(plan, snapshot_users_y_posts_con_bools)

    assert detection.found is True
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    m = matches[0]
    assert m["join_node_type"] == "Hash Join"
    assert m["table"] == "public.users"
    assert set(m["columns"]) == {"is_verified", "is_active"}
    assert "CREATE STATISTICS" in m["suggested_sql"]
    assert "FROM public.users" in m["suggested_sql"]


def test_no_dispara_si_ratio_es_bajo(snapshot_users_y_posts_con_bools) -> None:
    """plan_rows=100 vs actual_rows=200 (2x): por debajo del umbral 5x."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 100.0,
            "Total Cost": 5000.0,
            "Plan Rows": 100,
            "Plan Width": 100,
            "Actual Rows": 200,
            "Actual Loops": 1,
            "Hash Cond": "(p.author_id = u.id)",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Parent Relationship": "Inner",
                    "Relation Name": "users",
                    "Alias": "u",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 50,
                    "Actual Rows": 200,
                    "Filter": "(is_verified AND is_active)",
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_cardinality_misestimate(plan, snapshot_users_y_posts_con_bools)
    assert detection.found is False


def test_no_dispara_sin_actual_rows(snapshot_users_y_posts_con_bools) -> None:
    """EXPLAIN sin ANALYZE: no hay `Actual Rows` para comparar."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 100.0,
            "Total Cost": 5000.0,
            "Plan Rows": 1,
            "Plan Width": 100,
            "Hash Cond": "(p.author_id = u.id)",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Parent Relationship": "Inner",
                    "Relation Name": "users",
                    "Alias": "u",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 1,
                    "Plan Width": 50,
                    "Filter": "(is_verified AND is_active)",
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_cardinality_misestimate(plan, snapshot_users_y_posts_con_bools)
    assert detection.found is False


def test_no_dispara_con_filter_de_una_sola_columna(
    snapshot_users_y_posts_con_bools,
) -> None:
    """Mal estimado pero el filter referencia solo una columna: no es
    un caso de CREATE STATISTICS multi-columna."""
    raw = {
        "Plan": {
            "Node Type": "Hash Join",
            "Startup Cost": 100.0,
            "Total Cost": 5000.0,
            "Plan Rows": 1,
            "Plan Width": 100,
            "Actual Rows": 50_000,
            "Hash Cond": "(p.author_id = u.id)",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Parent Relationship": "Inner",
                    "Relation Name": "users",
                    "Alias": "u",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 1,
                    "Plan Width": 50,
                    "Actual Rows": 100,
                    "Filter": "(is_verified)",
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_cardinality_misestimate(plan, snapshot_users_y_posts_con_bools)
    assert detection.found is False


def test_no_dispara_sobre_simple_seq_scan_sin_join(
    snapshot_users_y_posts_con_bools,
) -> None:
    """Sin un Hash/Merge/Nested Loop arriba, D18 no aplica. Otros detectores
    (D17 si hay bool, D16 si falta índice) deben cubrir esos casos."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 1,
            "Plan Width": 50,
            "Actual Rows": 100,
            "Filter": "(is_verified AND is_active)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_cardinality_misestimate(plan, snapshot_users_y_posts_con_bools)
    assert detection.found is False

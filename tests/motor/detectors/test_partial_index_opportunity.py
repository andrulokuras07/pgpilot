"""Tests del detector D17 — Oportunidad de índice parcial.

Criterio del backlog:
  Hecho cuando: test verde para Q11 (notifications.user_id + read=false).
  El recomendador emite SQL con cláusula `WHERE`.
"""

from __future__ import annotations

from typing import Any

import pytest

from motor import detect_partial_index_opportunity, parse_explain


@pytest.fixture
def snapshot_notifications() -> dict[str, Any]:
    """`notifications(user_id INT, read BOOL)` con índice btree solo
    sobre `user_id`. Replica el shape de AppDB v1."""
    return {
        "schema": {
            "public.notifications": {
                "schema": "public",
                "name": "notifications",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "bigint",
                        "is_nullable": False,
                        "ordinal_position": 1,
                    },
                    {
                        "name": "user_id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "ordinal_position": 2,
                    },
                    {
                        "name": "read",
                        "data_type": "boolean",
                        "is_nullable": False,
                        "ordinal_position": 3,
                    },
                ],
                "indexes": [
                    {
                        "name": "idx_notifications_user_id",
                        "columns": ["user_id"],
                        "method": "btree",
                        "is_unique": False,
                        "is_primary": False,
                    }
                ],
                "foreign_keys": [],
            },
        },
        "sizes": {
            "public.notifications": {
                "estimated_rows": 500_000,
                "total_bytes": 80_000_000,
                "category": "large",
            },
        },
        "stats": {},
    }


def test_dispara_q11_bitmap_heap_scan_con_filter_bool(snapshot_notifications) -> None:
    """Q11 real: Postgres emite `(NOT read)` en el Filter del Bitmap Heap
    Scan cuando el SQL del usuario dice `read = false`."""
    raw = {
        "Plan": {
            "Node Type": "Bitmap Heap Scan",
            "Relation Name": "notifications",
            "Startup Cost": 4.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 24,
            "Recheck Cond": "(user_id = 1000)",
            "Filter": "(NOT read)",
            "Plans": [
                {
                    "Node Type": "Bitmap Index Scan",
                    "Parent Relationship": "Outer",
                    "Index Name": "idx_notifications_user_id",
                    "Startup Cost": 0.0,
                    "Total Cost": 4.0,
                    "Plan Rows": 50,
                    "Plan Width": 0,
                    "Index Cond": "(user_id = 1000)",
                }
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_partial_index_opportunity(plan, snapshot_notifications)

    assert detection.found is True
    matches = detection.evidence["matches"]
    # 2 matches esperados: el Bitmap Heap Scan (con bool en Filter) y el
    # Bitmap Index Scan (con user_id ∧ read referenciados via texto). En
    # la práctica, el Index Scan no tiene `read` así que solo dispara el
    # Heap Scan. Verificamos al menos uno con la firma correcta:
    bitmap_heap = next(m for m in matches if m["node_type"] == "Bitmap Heap Scan")
    assert bitmap_heap["table"] == "public.notifications"
    assert bitmap_heap["column"] == "user_id"
    assert bitmap_heap["bool_column"] == "read"
    assert bitmap_heap["bool_value"] == "false"
    assert "WHERE read = false" in bitmap_heap["suggested_sql"]
    assert "CREATE INDEX idx_notifications_user_id_partial" in bitmap_heap["suggested_sql"]


def test_dispara_con_read_equal_true(snapshot_notifications) -> None:
    """Variante: el filtro viene como `(read = true)` explícito."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "notifications",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 24,
            "Filter": "((user_id = 1000) AND (read = true))",
        }
    }
    plan = parse_explain(raw)
    detection = detect_partial_index_opportunity(plan, snapshot_notifications)

    assert detection.found is True
    m = detection.evidence["matches"][0]
    assert m["bool_value"] == "true"
    assert "WHERE read = true" in m["suggested_sql"]


def test_dispara_con_read_is_false(snapshot_notifications) -> None:
    """Variante: `read IS FALSE` (Postgres a veces lo emite así)."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "notifications",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 24,
            "Filter": "((user_id = 1000) AND (read IS FALSE))",
        }
    }
    plan = parse_explain(raw)
    detection = detect_partial_index_opportunity(plan, snapshot_notifications)
    assert detection.found is True
    assert detection.evidence["matches"][0]["bool_value"] == "false"


def test_no_dispara_sin_columna_booleana_en_schema(
    snapshot_posts_con_indice_en_author_id,
) -> None:
    """Tabla sin bool: el detector no aplica aunque haya AND en el filter."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 24,
            "Filter": "((author_id = 5000) AND (id > 100))",
        }
    }
    plan = parse_explain(raw)
    detection = detect_partial_index_opportunity(plan, snapshot_posts_con_indice_en_author_id)
    assert detection.found is False


def test_no_dispara_si_solo_hay_bool(snapshot_notifications) -> None:
    """Filtro solo sobre `read`: no hay otra columna que indexar."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "notifications",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 24,
            "Filter": "(NOT read)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_partial_index_opportunity(plan, snapshot_notifications)
    assert detection.found is False


def test_no_dispara_sobre_tabla_desconocida(snapshot_notifications) -> None:
    """Relation Name fuera del snapshot: abstención."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "unknown_table",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 24,
            "Filter": "((user_id = 1000) AND (NOT read))",
        }
    }
    plan = parse_explain(raw)
    detection = detect_partial_index_opportunity(plan, snapshot_notifications)
    assert detection.found is False

"""Tests del detector D10 — Falta de índice cubriente.

Criterio del backlog:
  Hecho cuando: detector pasa test, documentado.
"""

from __future__ import annotations

from motor import detect_missing_covering_index, parse_explain


def test_dispara_con_index_scan() -> None:
    """Index Scan implica heap fetch → oportunidad de Index Only."""
    raw = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "posts",
            "Index Name": "idx_posts_author_id",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 100,
            "Plan Width": 200,
            "Index Cond": "(author_id = 5)",
        }
    }
    snapshot = {
        "schema": {
            "public.posts": {
                "indexes": [
                    {
                        "name": "idx_posts_author_id",
                        "method": "btree",
                        "columns": ["author_id"],
                    }
                ]
            }
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_covering_index(plan, snapshot)

    assert detection.found is True
    match = detection.evidence["matches"][0]
    assert match["table"] == "public.posts"
    assert match["index_name"] == "idx_posts_author_id"
    assert match["indexed_columns"] == ["author_id"]


def test_no_dispara_con_index_only_scan() -> None:
    """Index Only Scan ya resuelve sin heap → no aplica D10."""
    raw = {
        "Plan": {
            "Node Type": "Index Only Scan",
            "Relation Name": "posts",
            "Index Name": "idx_posts_author_id",
            "Startup Cost": 0.0,
            "Total Cost": 5.0,
            "Plan Rows": 100,
            "Plan Width": 8,
            "Index Cond": "(author_id = 5)",
            "Heap Fetches": 0,
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_covering_index(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_con_seq_scan() -> None:
    """Seq Scan no es oportunidad de cubriente (no usa índice)."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 500.0,
            "Plan Rows": 100,
            "Plan Width": 200,
            "Filter": "(author_id = 5)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_covering_index(plan, {})

    assert detection.found is False


def test_dispara_aunque_no_haya_snapshot() -> None:
    """Sin snapshot el detector sigue disparando con info reducida."""
    raw = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "orders",
            "Index Name": "idx_orders_user_id",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 100,
            "Plan Width": 200,
            "Index Cond": "(user_id = 5)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_covering_index(plan, {})

    assert detection.found is True
    match = detection.evidence["matches"][0]
    assert match["table"] == "orders"
    assert match["indexed_columns"] is None


def test_multiples_index_scans_en_un_plan() -> None:
    """Cada Index Scan con suficientes filas se reporta independiente."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Plans": [
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "posts",
                    "Index Name": "idx_posts_author_id",
                    "Index Cond": "(author_id = 5)",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 100,
                    "Plan Width": 200,
                },
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "orders",
                    "Index Name": "idx_orders_status",
                    "Index Cond": "(status = 'pending')",
                    "Startup Cost": 0.0,
                    "Total Cost": 20.0,
                    "Plan Rows": 200,
                    "Plan Width": 100,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_covering_index(plan, {})

    assert detection.found is True
    assert len(detection.evidence["matches"]) == 2
    tables = {m["table"] for m in detection.evidence["matches"]}
    assert tables == {"posts", "orders"}


def test_no_dispara_con_index_scan_pocas_filas() -> None:
    """Index Scan que devuelve <50 filas: el heap fetch es despreciable."""
    raw = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "users",
            "Index Name": "users_pkey",
            "Index Cond": "(id = 5)",
            "Startup Cost": 0.0,
            "Total Cost": 0.1,
            "Plan Rows": 1,
            "Plan Width": 100,
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_covering_index(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_usa_actual_rows_cuando_estan_disponibles() -> None:
    """Si actual_rows está, se usa para el umbral (no plan_rows mal estimado)."""
    raw_under_threshold = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "users",
            "Index Name": "idx_users_email",
            "Index Cond": "(email = 'x')",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 5000,  # estimación inflada
            "Plan Width": 100,
            "Actual Rows": 3,  # realidad: 3 filas
        }
    }
    plan = parse_explain(raw_under_threshold)
    detection = detect_missing_covering_index(plan, {})

    assert detection.found is False, "Estimación 5000 pero real 3: no debería disparar"

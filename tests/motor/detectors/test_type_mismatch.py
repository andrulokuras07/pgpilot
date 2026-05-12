"""Tests del detector D11 — Índice no usado por mismatch de tipo.

Criterio del backlog:
  Hecho cuando: detector pasa test, documentado.

Convenciones de test del módulo motor:
  - Unit (no requiere AppDB corriendo).
  - Happy path + caso negativo + frontera + robustez.
  - Fixtures sintéticos inline (más legibles para este detector).
"""

from __future__ import annotations

import pytest

from motor import parse_explain
from motor.detectors.type_mismatch import detect_type_mismatch


# ---------------------------------------------------------------------------
# Helpers de snapshot
# ---------------------------------------------------------------------------

def _snap_with_btree(col: str = "status", table: str = "public.posts") -> dict:
    """Snapshot con un índice btree sobre `col` en `table`."""
    short = table.split(".")[-1]
    return {
        "schema": {
            table: {
                "schema": table.split(".")[0],
                "name": short,
                "columns": [{"name": col, "data_type": "varchar(20)", "is_nullable": False}],
                "indexes": [
                    {
                        "name": f"idx_{short}_{col}",
                        "columns": [col],
                        "method": "btree",
                        "is_unique": False,
                        "is_primary": False,
                    }
                ],
                "foreign_keys": [],
            }
        },
        "sizes": {},
        "stats": {},
    }


def _snap_without_index(col: str = "status") -> dict:
    """Snapshot sin ningún índice en `col`."""
    return {
        "schema": {
            "public.posts": {
                "schema": "public",
                "name": "posts",
                "columns": [{"name": col, "data_type": "varchar(20)", "is_nullable": False}],
                "indexes": [],
                "foreign_keys": [],
            }
        },
        "sizes": {},
        "stats": {},
    }


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_dispara_con_cast_en_columna_y_indice_existente() -> None:
    """Seq Scan con cast ((status)::integer y índice btree en status → found."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 450.0,
            "Plan Rows": 500,
            "Plan Width": 100,
            "Filter": "((status)::integer = 1)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_type_mismatch(plan, _snap_with_btree("status"))

    assert detection.found is True
    assert detection.confidence == pytest.approx(0.9)
    match = detection.evidence["matches"][0]
    assert match["column"] == "status"
    assert match["cast_type"] == "integer"
    assert match["table"] == "public.posts"
    assert match["index_name"] == "idx_posts_status"


def test_dispara_con_cast_author_id_a_text() -> None:
    """Cast ((author_id)::text) sobre columna con índice btree."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "orders",
            "Startup Cost": 0.0,
            "Total Cost": 200.0,
            "Plan Rows": 100,
            "Plan Width": 50,
            "Filter": "((author_id)::text = '42'::text)",
        }
    }
    plan = parse_explain(raw)
    snap = _snap_with_btree("author_id", "public.orders")
    detection = detect_type_mismatch(plan, snap)

    assert detection.found is True
    match = detection.evidence["matches"][0]
    assert match["column"] == "author_id"
    assert match["cast_type"] == "text"


def test_multiples_casts_en_mismo_filtro() -> None:
    """Dos columnas con cast en el mismo nodo → dos matches."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "items",
            "Startup Cost": 0.0,
            "Total Cost": 300.0,
            "Plan Rows": 200,
            "Plan Width": 80,
            # Dos casts en el mismo filtro:
            "Filter": "((price)::integer > 100) AND ((status)::integer = 1)",
        }
    }
    plan = parse_explain(raw)
    snap: dict = {
        "schema": {
            "public.items": {
                "schema": "public",
                "name": "items",
                "columns": [],
                "indexes": [
                    {"name": "idx_items_price", "columns": ["price"], "method": "btree"},
                    {"name": "idx_items_status", "columns": ["status"], "method": "btree"},
                ],
                "foreign_keys": [],
            }
        },
        "sizes": {},
        "stats": {},
    }
    detection = detect_type_mismatch(plan, snap)

    assert detection.found is True
    cols = {m["column"] for m in detection.evidence["matches"]}
    assert cols == {"price", "status"}


# ---------------------------------------------------------------------------
# Casos negativos
# ---------------------------------------------------------------------------

def test_no_dispara_sin_indice_en_columna_con_cast() -> None:
    """Cast presente pero sin índice → no es D11 (podría ser D16)."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 450.0,
            "Plan Rows": 500,
            "Plan Width": 100,
            "Filter": "((status)::integer = 1)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_type_mismatch(plan, _snap_without_index("status"))

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_cast_en_filtro() -> None:
    """Filtro normal sin cast → no hay mismatch de tipo."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 450.0,
            "Plan Rows": 500,
            "Plan Width": 100,
            "Filter": "(author_id = 5)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_type_mismatch(plan, _snap_with_btree("author_id"))

    assert detection.found is False


def test_no_dispara_con_cast_sobre_literal_no_columna() -> None:
    """Cast '5'::integer es sobre el literal, no la columna → índice sigue usable."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 450.0,
            "Plan Rows": 500,
            "Plan Width": 100,
            # El cast está en el literal, no en la columna: status = '5'::integer
            # El regex _CAST_ON_COLUMN_RE busca ((col)::tipo y no matchea esto.
            "Filter": "(status = '5'::integer)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_type_mismatch(plan, _snap_with_btree("status"))

    assert detection.found is False


def test_no_dispara_con_index_scan() -> None:
    """Index Scan: el índice ya se está usando, no hay pérdida."""
    raw = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "posts",
            "Index Name": "idx_posts_status",
            "Index Cond": "(status = 1)",
            "Startup Cost": 0.0,
            "Total Cost": 5.0,
            "Plan Rows": 10,
            "Plan Width": 100,
        }
    }
    plan = parse_explain(raw)
    detection = detect_type_mismatch(plan, _snap_with_btree("status"))

    assert detection.found is False


# ---------------------------------------------------------------------------
# Robustez
# ---------------------------------------------------------------------------

def test_no_dispara_con_filter_none() -> None:
    """Nodo sin filtro: nada que inspeccionar."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 450.0,
            "Plan Rows": 500,
            "Plan Width": 100,
        }
    }
    plan = parse_explain(raw)
    detection = detect_type_mismatch(plan, _snap_with_btree("status"))

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_snapshot_vacio_no_dispara() -> None:
    """Sin snapshot no hay información de índices → not found (evitar FP)."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 450.0,
            "Plan Rows": 500,
            "Plan Width": 100,
            "Filter": "((status)::integer = 1)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_type_mismatch(plan, {})

    assert detection.found is False


def test_acepta_kwarg_sql_sin_efecto() -> None:
    """La firma extendida acepta sql= sin cambiar el resultado estructural."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 450.0,
            "Plan Rows": 500,
            "Plan Width": 100,
            "Filter": "((status)::integer = 1)",
        }
    }
    plan = parse_explain(raw)
    snap = _snap_with_btree("status")

    det_sin_sql = detect_type_mismatch(plan, snap)
    det_con_sql = detect_type_mismatch(plan, snap, sql="SELECT * FROM posts WHERE status::int = 1")

    assert det_sin_sql.found == det_con_sql.found
    assert det_sin_sql.evidence == det_con_sql.evidence


def test_no_confunde_con_d5_funcion_en_where() -> None:
    """Función en filtro es D5, no D11. El regex de D11 no captura funciones."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 200.0,
            "Plan Rows": 100,
            "Plan Width": 50,
            # D5 pattern: lower(status) = ... — no matchea ((col)::tipo
            "Filter": "(lower(status) = 'active'::text)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_type_mismatch(plan, _snap_with_btree("status", "public.users"))

    assert detection.found is False

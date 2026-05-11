"""Tests del detector C1 — Seq Scan en tabla grande con índice.

Criterios del backlog:

  Hecho cuando: test verde con un plan de seq scan sobre tabla
  grande con índice disponible (devuelve found=true) y otro con
  seq scan sobre tabla pequeña (devuelve found=false).

Cubrimos esos dos + un tercer caso (tabla grande SIN índice → False)
para defender la frontera entre C1 y el futuro C2.
"""

from __future__ import annotations

from typing import Any

from motor import detect_seq_scan_on_large_table, parse_explain

# --- caso positivo (criterio explícito del backlog) ----------------


def test_dispara_sobre_seq_scan_en_tabla_grande_con_indice(
    plan_limit_nested_loop: Any,
    snapshot_posts_con_indice_en_author_id: dict[str, Any],
) -> None:
    """Plan 03: Seq Scan sobre `posts` con `Filter: (author_id = 5)`.
    Snapshot: posts tiene 500k filas e índice btree en author_id.
    Esperado: found=True con un match que apunta a posts.author_id."""
    plan = parse_explain(plan_limit_nested_loop)
    detection = detect_seq_scan_on_large_table(plan, snapshot_posts_con_indice_en_author_id)

    assert detection.found is True
    assert detection.confidence == 1.0

    matches = detection.evidence["matches"]
    assert len(matches) == 1
    match = matches[0]
    assert match["table"] == "public.posts"
    assert match["column"] == "author_id"
    assert match["estimated_rows"] == 500_000
    assert match["index_name"] == "idx_posts_author_id"
    # Sanidad: el filter crudo del nodo viaja a evidence para que C2
    # lo pueda mostrar al usuario sin re-parsear el árbol.
    assert match["filter"] == "(author_id = 5)"


# --- caso negativo (criterio explícito del backlog) ----------------


def test_no_dispara_sobre_seq_scan_en_tabla_pequena(
    plan_aggregate_seq_scan: Any,
    snapshot_tags_tabla_pequena: dict[str, Any],
) -> None:
    """Plan 02: Seq Scan sobre `tags` con filtro LIKE. Snapshot: tags
    tiene 6k filas. Tabla pequeña → no es C1 aunque haya Seq Scan."""
    plan = parse_explain(plan_aggregate_seq_scan)
    detection = detect_seq_scan_on_large_table(plan, snapshot_tags_tabla_pequena)

    assert detection.found is False
    assert detection.confidence == 0.0
    assert detection.evidence == {}


# --- caso negativo extra (frontera con C2) -------------------------


def test_no_dispara_si_tabla_grande_pero_sin_indice(
    plan_limit_nested_loop: Any,
    snapshot_posts_sin_indice_en_author_id: dict[str, Any],
) -> None:
    """Mismo plan que el caso positivo, pero el snapshot reporta que
    NO existe índice en author_id. Esto es Q01 puro (falta de
    índice), lo cubre C2 al recomendar crearlo. C1 debe abstenerse."""
    plan = parse_explain(plan_limit_nested_loop)
    detection = detect_seq_scan_on_large_table(plan, snapshot_posts_sin_indice_en_author_id)

    assert detection.found is False


# --- robustez ------------------------------------------------------


def test_no_falla_si_relation_name_es_None() -> None:
    """Algunos Seq Scan sintéticos pueden no traer Relation Name
    (ej. Seq Scan sobre VALUES). El detector debe ignorarlos en
    lugar de crashear."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Startup Cost": 0.0,
            "Total Cost": 1.0,
            "Plan Rows": 1,
            "Plan Width": 1,
            "Filter": "(x = 1)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_seq_scan_on_large_table(plan, {"schema": {}, "sizes": {}})
    assert detection.found is False


def test_no_falla_si_filter_es_None() -> None:
    """Seq Scan sin filtro (full table scan). No hay nada que indexar."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 1.0,
            "Plan Rows": 500000,
            "Plan Width": 1,
        }
    }
    plan = parse_explain(raw)
    snapshot = {
        "schema": {"public.posts": {"indexes": []}},
        "sizes": {
            "public.posts": {"estimated_rows": 500_000, "total_bytes": 1, "category": "large"}
        },
    }
    detection = detect_seq_scan_on_large_table(plan, snapshot)
    assert detection.found is False

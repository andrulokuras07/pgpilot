"""Tests del detector D16 — Seq Scan sobre tabla grande sin índice.

Criterio del backlog:
  Hecho cuando: test verde para Q01 (posts.author_id sin índice →
  create_index), Q06 (BETWEEN), Q08 (con ORDER BY), Q09 (subquery
  correlacionada outer). El detector dispara en los 4 casos.
"""

from __future__ import annotations

from motor import detect_missing_index, parse_explain


def _plan_with_seq_scan(filter_expr: str) -> dict:
    return {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 12000.0,
            "Plan Rows": 1,
            "Plan Width": 100,
            "Filter": filter_expr,
            "Rows Removed by Filter": 500_000,
        }
    }


def test_dispara_q01_author_id_sin_indice(
    snapshot_posts_sin_indice_en_author_id,
) -> None:
    """Q01: posts.author_id sin índice → D16 dispara con create_index."""
    plan = parse_explain(_plan_with_seq_scan("(author_id = 5000)"))
    detection = detect_missing_index(plan, snapshot_posts_sin_indice_en_author_id)

    assert detection.found is True
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    m = matches[0]
    assert m["table"] == "public.posts"
    assert m["column"] == "author_id"
    assert m["suggested_index_name"] == "idx_posts_author_id"
    assert "CREATE INDEX idx_posts_author_id" in m["suggested_sql"]
    assert "ON public.posts (author_id)" in m["suggested_sql"]


def test_dispara_q06_between_es_mismo_caso(
    snapshot_posts_sin_indice_en_author_id,
) -> None:
    """Q06 usa BETWEEN sobre author_id. Postgres lo emite como (col >= X)
    AND (col <= Y) — la primera columna se infiere igual."""
    plan = parse_explain(_plan_with_seq_scan("((author_id >= 1) AND (author_id <= 100))"))
    detection = detect_missing_index(plan, snapshot_posts_sin_indice_en_author_id)

    assert detection.found is True
    assert detection.evidence["matches"][0]["column"] == "author_id"


def test_no_dispara_con_indice_existente(
    snapshot_posts_con_indice_en_author_id,
) -> None:
    """Frontera con C1: si hay btree apuntable, D16 se calla.
    Ese caso es responsabilidad de C1 con recomendación ANALYZE."""
    plan = parse_explain(_plan_with_seq_scan("(author_id = 5000)"))
    detection = detect_missing_index(plan, snapshot_posts_con_indice_en_author_id)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_en_tabla_pequena(snapshot_tags_tabla_pequena) -> None:
    """Tabla <100k filas: D16 nunca recomienda índice (Seq Scan es óptimo)."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "tags",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 100,
            "Plan Width": 10,
            "Filter": "(use_count > 100)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_index(plan, snapshot_tags_tabla_pequena)
    assert detection.found is False


def test_no_dispara_sin_filtro(snapshot_posts_sin_indice_en_author_id) -> None:
    """Seq Scan sin Filter (ej. `SELECT count(*) FROM posts`): D22 lo
    cubre, no D16. La ausencia de columna inferible debe abstener."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 12000.0,
            "Plan Rows": 500_000,
            "Plan Width": 4,
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_index(plan, snapshot_posts_sin_indice_en_author_id)
    assert detection.found is False


def test_dispara_dentro_de_gather(snapshot_posts_sin_indice_en_author_id) -> None:
    """Postgres a menudo envuelve Seq Scan en Gather para paralelismo
    (Q01/Q06 reales). El detector recorre todo el árbol vía find_nodes."""
    raw = {
        "Plan": {
            "Node Type": "Gather",
            "Startup Cost": 1000.0,
            "Total Cost": 13000.0,
            "Plan Rows": 1,
            "Plan Width": 100,
            "Workers Planned": 2,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Parent Relationship": "Outer",
                    "Relation Name": "posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 12000.0,
                    "Plan Rows": 1,
                    "Plan Width": 100,
                    "Filter": "(author_id = 5000)",
                }
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_index(plan, snapshot_posts_sin_indice_en_author_id)
    assert detection.found is True
    assert detection.evidence["matches"][0]["column"] == "author_id"


def test_dispara_bajo_limit(snapshot_posts_sin_indice_en_author_id) -> None:
    """Q08: `SELECT ... WHERE author_id = X ORDER BY created_at LIMIT 20`.
    El top node suele ser Limit; el Seq Scan vive abajo."""
    raw = {
        "Plan": {
            "Node Type": "Limit",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 20,
            "Plan Width": 100,
            "Plans": [
                {
                    "Node Type": "Sort",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 0.0,
                    "Total Cost": 90.0,
                    "Plan Rows": 1,
                    "Plan Width": 100,
                    "Sort Key": ["created_at DESC"],
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Parent Relationship": "Outer",
                            "Relation Name": "posts",
                            "Startup Cost": 0.0,
                            "Total Cost": 80.0,
                            "Plan Rows": 1,
                            "Plan Width": 100,
                            "Filter": "(author_id = 5000)",
                        }
                    ],
                }
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_missing_index(plan, snapshot_posts_sin_indice_en_author_id)
    assert detection.found is True


def test_no_dispara_sobre_tabla_desconocida() -> None:
    """Relation Name que no está en el snapshot: detector se abstiene
    (no inventa recomendaciones sobre tablas que no conoce)."""
    plan = parse_explain(_plan_with_seq_scan("(author_id = 5000)"))
    detection = detect_missing_index(plan, {"schema": {}, "sizes": {}})
    assert detection.found is False

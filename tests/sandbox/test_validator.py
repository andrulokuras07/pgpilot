"""Tests del validador C3.

Dos capas:

1. **Unit tests** sobre `verdict_from_plans` con planes sintéticos.
   Cubren la lógica de veredicto sin depender del sandbox real. Son
   rápidos y deterministas.
2. **Integration tests** (`@pytest.mark.integration`) sobre
   `validate_index_recommendation` end-to-end: monta sandbox, aplica
   el índice, EXPLAIN antes/después, dropea. Requieren contenedores
   levantados.
"""

from __future__ import annotations

from typing import Any

import pytest

from motor import Recommendation, parse_explain
from sandbox import (
    ValidationResult,
    validate_index_recommendation,
    verdict_from_plans,
)

# --- helpers para construir planes sintéticos ----------------------


def _plan_with_scan(node_type: str, relation: str, total_cost: float = 100.0) -> Any:
    """Construye un plan EXPLAIN sintético con un solo nodo de scan
    sobre la relación indicada. Suficiente para ejercer la lógica de
    veredicto sin tener que correr Postgres."""
    return parse_explain(
        {
            "Plan": {
                "Node Type": node_type,
                "Relation Name": relation,
                "Startup Cost": 0.0,
                "Total Cost": total_cost,
                "Plan Rows": 1,
                "Plan Width": 1,
            }
        }
    )


# --- veredicto puro ------------------------------------------------


def test_verdict_validated_cuando_seq_scan_pasa_a_index_scan() -> None:
    """Caso feliz: el planner cambió de Seq Scan a Index Scan tras crear
    el índice. La recomendación se valida."""
    before = _plan_with_scan("Seq Scan", "posts", total_cost=1000.0)
    after = _plan_with_scan("Index Scan", "posts", total_cost=10.0)

    result = verdict_from_plans(before, after, "public.posts")

    assert result.verdict == "validated"
    assert result.node_type_before == "Seq Scan"
    assert result.node_type_after == "Index Scan"
    assert result.cost_before == 1000.0
    assert result.cost_after == 10.0
    assert "Index Scan" in result.reason


def test_verdict_validated_para_bitmap_heap_scan() -> None:
    """Bitmap Heap Scan también cuenta como uso de índice (familia de
    Bitmap es válida para acceso por índice con muchas filas)."""
    before = _plan_with_scan("Seq Scan", "posts")
    after = _plan_with_scan("Bitmap Heap Scan", "posts")

    result = verdict_from_plans(before, after, "public.posts")

    assert result.verdict == "validated"


def test_verdict_discarded_cuando_mismo_seq_scan() -> None:
    """Sin cambio de tipo de nodo: el planner sigue ignorando el índice.
    La recomendación se descarta con motivo."""
    before = _plan_with_scan("Seq Scan", "posts")
    after = _plan_with_scan("Seq Scan", "posts")

    result = verdict_from_plans(before, after, "public.posts")

    assert result.verdict == "discarded"
    assert "Seq Scan" in result.reason


def test_verdict_discarded_cuando_query_no_toca_la_tabla() -> None:
    """Edge: la query no contiene scan sobre la tabla recomendada
    (cambio de tabla en query, etc.). Se descarta sin tipos detectados."""
    before = _plan_with_scan("Seq Scan", "users")
    after = _plan_with_scan("Index Scan", "users")

    result = verdict_from_plans(before, after, "public.posts")

    assert result.verdict == "discarded"
    assert result.node_type_before is None
    assert result.node_type_after is None


def test_verdict_discarded_si_cambio_a_tipo_inesperado() -> None:
    """Cambio de nodo pero a algo que no es Index/Bitmap: descarte por
    precaución (no se sabe interpretar)."""
    before = _plan_with_scan("Seq Scan", "posts")
    # `Tid Scan` no está en la lista de tipos de índice esperados.
    after = _plan_with_scan("Tid Scan", "posts")

    result = verdict_from_plans(before, after, "public.posts")

    assert result.verdict == "discarded"


def test_validation_result_es_inmutable() -> None:
    """`ValidationResult` es frozen — defensa contra mutaciones."""
    result = ValidationResult(
        verdict="validated",
        reason="ok",
        node_type_before="Seq Scan",
        node_type_after="Index Scan",
        cost_before=10.0,
        cost_after=1.0,
    )
    with pytest.raises(Exception):
        result.verdict = "discarded"  # type: ignore[misc]


# --- short-circuit para kind="analyze" -----------------------------


def test_validate_recommendation_analyze_skipped_sin_tocar_sandbox() -> None:
    """Recomendaciones de tipo ANALYZE no se validan en sandbox (tablas
    vacías → ANALYZE no produce señal). El validador devuelve
    `skipped_no_sandbox_signal` sin abrir conexión al pool.

    Como NO toca el pool, este test no necesita `@pytest.mark.integration`:
    le pasamos `pool=None` y verificamos el short-circuit.
    """
    rec = Recommendation(
        kind="analyze",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id_existing",
        create_index_sql="ANALYZE public.posts;",
        justification="...",
        expected_impact="...",
        selectivity=0.0002,
    )
    # pool=None: si el código intenta usarlo, falla con AttributeError —
    # la prueba defiende justo eso (que el short-circuit suceda antes).
    result = validate_index_recommendation(
        pool=None,  # type: ignore[arg-type]
        snapshot={"schema": {}, "sizes": {}, "stats": {}},  # type: ignore[arg-type]
        query="SELECT 1",
        recommendation=rec,
    )

    assert result.verdict == "skipped_no_sandbox_signal"
    assert result.cost_before is None
    assert result.cost_after is None
    assert "ANALYZE" in result.reason


# --- end-to-end con sandbox real -----------------------------------


@pytest.mark.integration
def test_validate_create_index_real_en_sandbox(
    sandbox_pool: Any,
    synthetic_snapshot: Any,
) -> None:
    """Camino feliz end-to-end: snapshot con `posts.author_id` sin
    índice (igual a Q01 de AppDB). El validador monta el sandbox,
    EXPLAIN antes (Seq Scan), CREATE INDEX, EXPLAIN después → debe
    quedar Index/Bitmap. Verdict = validated."""
    rec = Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id",
        create_index_sql='CREATE INDEX "idx_posts_author_id" ON "public"."posts" ("author_id");',
        justification="...",
        expected_impact="...",
        selectivity=0.0002,
    )
    result = validate_index_recommendation(
        sandbox_pool,
        synthetic_snapshot,
        "SELECT * FROM posts WHERE author_id = 5",
        rec,
    )

    assert result.verdict == "validated"
    assert result.node_type_before == "Seq Scan"
    assert result.node_type_after in {
        "Index Scan",
        "Index Only Scan",
        "Bitmap Heap Scan",
    }


@pytest.mark.integration
def test_validate_index_irrelevante_se_descarta(
    sandbox_pool: Any,
    synthetic_snapshot: Any,
) -> None:
    """Si la recomendación es un índice irrelevante al filtro, el
    planner sigue eligiendo Seq Scan y el validador descarta. Aquí
    recomendamos un índice sobre `content` cuando la query filtra por
    `author_id`."""
    rec = Recommendation(
        kind="create_index",
        table="public.posts",
        column="content",
        index_method="btree",
        index_name="idx_posts_content_irrelevante",
        create_index_sql=(
            'CREATE INDEX "idx_posts_content_irrelevante" ON "public"."posts" ("content");'
        ),
        justification="...",
        expected_impact="...",
        selectivity=None,
    )
    result = validate_index_recommendation(
        sandbox_pool,
        synthetic_snapshot,
        "SELECT * FROM posts WHERE author_id = 5",
        rec,
    )

    assert result.verdict == "discarded"
    assert result.node_type_before == "Seq Scan"
    # Después de crear índice irrelevante, sigue siendo Seq Scan.
    assert result.node_type_after == "Seq Scan"

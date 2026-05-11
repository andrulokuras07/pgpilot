"""Tests del recomendador C2.

Criterio del backlog:
  Hecho cuando: dada una detección de seq scan, devuelve un objeto con
  SQL CREATE INDEX válido y justificación textual.

Cubrimos: caso "create_index" (no hay índice), caso "analyze" (índice
ya existe — el escenario natural cuando C1 dispara con índice presente),
detección vacía → lista vacía, múltiples matches → múltiples
recomendaciones, fallback sin stats, índice parcial implícito por null_frac.
"""

from __future__ import annotations

from typing import Any

import pytest

from motor import (
    Detection,
    Recommendation,
    recommend_for_seq_scan_on_large_table,
)


def _snapshot(
    *,
    has_index: bool,
    n_distinct: float | None = None,
    null_frac: float | None = 0.0,
    estimated_rows: int = 500_000,
    column: str = "author_id",
    table_name: str = "posts",
) -> dict[str, Any]:
    """Helper para armar snapshots sintéticos compactos.

    Mantiene la forma exacta de `SchemaSnapshot` del conector pero
    omite los campos que el recomendador no lee.
    """
    indexes = []
    if has_index:
        indexes.append(
            {
                "name": f"idx_{table_name}_{column}",
                "columns": [column],
                "method": "btree",
                "is_unique": False,
                "is_primary": False,
            }
        )
    stats: dict[str, Any] = {}
    if n_distinct is not None or null_frac is not None:
        stats[f"public.{table_name}"] = {
            column: {
                "has_stats": True,
                "n_distinct": n_distinct,
                "null_frac": null_frac,
                "most_common_vals": None,
                "correlation": None,
            }
        }
    return {
        "schema": {
            f"public.{table_name}": {
                "schema": "public",
                "name": table_name,
                "columns": [
                    {
                        "name": column,
                        "data_type": "integer",
                        "is_nullable": False,
                        "ordinal_position": 1,
                    }
                ],
                "indexes": indexes,
                "foreign_keys": [],
            }
        },
        "sizes": {
            f"public.{table_name}": {
                "estimated_rows": estimated_rows,
                "total_bytes": 1,
                "category": "large",
            }
        },
        "stats": stats,
    }


def _detection(
    *,
    table: str = "public.posts",
    column: str = "author_id",
    estimated_rows: int = 500_000,
    index_name: str | None = "idx_posts_author_id",
) -> Detection:
    return Detection(
        found=True,
        confidence=1.0,
        evidence={
            "matches": [
                {
                    "table": table,
                    "column": column,
                    "estimated_rows": estimated_rows,
                    "rows_removed_by_filter": estimated_rows - 100,
                    "index_name": index_name,
                    "filter": f"({column} = 5)",
                }
            ]
        },
    )


# --- happy path (criterio del backlog) -----------------------------


def test_recomendacion_create_index_cuando_no_existe_indice() -> None:
    """Caso "falta de índice": el detector dispara sobre tabla grande
    sin índice utilizable. La recomendación es CREATE INDEX con SQL
    válido y justificación derivada de stats."""
    detection = _detection()
    # snapshot SIN índice — escenario donde C2 emite CREATE INDEX.
    snapshot = _snapshot(has_index=False, n_distinct=5000.0, estimated_rows=500_000)

    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.kind == "create_index"
    assert rec.table == "public.posts"
    assert rec.column == "author_id"
    assert rec.index_method == "btree"
    assert rec.index_name == "idx_posts_author_id"
    # SQL válido: incluye CREATE INDEX, schema.table y la columna.
    assert "CREATE INDEX" in rec.create_index_sql
    assert '"public"."posts"' in rec.create_index_sql
    assert '"author_id"' in rec.create_index_sql
    # Selectividad: 1/5000 = 0.0002
    assert rec.selectivity == pytest.approx(1 / 5000)
    # Justificación textual: no vacía, menciona la tabla y selectividad.
    assert rec.table in rec.justification
    assert "0.02" in rec.justification  # 0.02% selectividad


def test_recomendacion_analyze_cuando_indice_ya_existe() -> None:
    """C1 actual dispara cuando el índice EXISTE y el planner lo ignora.
    En ese caso CREATE INDEX no aplica: C2 emite ANALYZE para refrescar
    stats antes de medidas más drásticas."""
    detection = _detection()
    snapshot = _snapshot(has_index=True, n_distinct=5000.0)

    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.kind == "analyze"
    assert rec.create_index_sql.startswith("ANALYZE")
    assert '"public"."posts"' in rec.create_index_sql
    # `index_name` apunta al índice existente para que la prosa lo refiera.
    assert rec.index_name == "idx_posts_author_id"
    assert "idx_posts_author_id" in rec.justification


# --- robustez ------------------------------------------------------


def test_deteccion_negativa_devuelve_lista_vacia() -> None:
    """Si `detection.found is False`, no hay recomendaciones que generar."""
    detection = Detection(found=False, confidence=0.0, evidence={"matches": []})
    recs = recommend_for_seq_scan_on_large_table(detection, _snapshot(has_index=False))
    assert recs == []


def test_n_matches_producen_n_recomendaciones() -> None:
    """Una detección con varios matches genera una recomendación por match,
    en el mismo orden."""
    detection = Detection(
        found=True,
        confidence=1.0,
        evidence={
            "matches": [
                {
                    "table": "public.posts",
                    "column": "author_id",
                    "estimated_rows": 500_000,
                    "rows_removed_by_filter": 1000,
                    "index_name": None,
                    "filter": "(author_id = 5)",
                },
                {
                    "table": "public.comments",
                    "column": "post_id",
                    "estimated_rows": 2_000_000,
                    "rows_removed_by_filter": 5000,
                    "index_name": None,
                    "filter": "(post_id = 7)",
                },
            ]
        },
    )
    snapshot = {
        "schema": {
            "public.posts": {"indexes": []},
            "public.comments": {"indexes": []},
        },
        "sizes": {
            "public.posts": {"estimated_rows": 500_000, "total_bytes": 1, "category": "large"},
            "public.comments": {
                "estimated_rows": 2_000_000,
                "total_bytes": 1,
                "category": "large",
            },
        },
        "stats": {},
    }

    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)

    assert len(recs) == 2
    assert [r.table for r in recs] == ["public.posts", "public.comments"]
    assert all(r.kind == "create_index" for r in recs)


def test_fallback_sin_stats_funciona() -> None:
    """Tabla sin ANALYZE: el recomendador no rompe; emite CREATE INDEX con
    selectividad=None y la justificación lo declara explícito."""
    detection = _detection()
    snapshot = _snapshot(has_index=False, n_distinct=None, null_frac=None)

    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.kind == "create_index"
    assert rec.selectivity is None
    assert "ANALYZE" in rec.justification  # menciona que falta ANALYZE


def test_null_frac_alto_sugiere_indice_parcial() -> None:
    """Si la columna tiene >50% NULLs, la justificación debe sugerir
    un índice parcial. El SQL del CREATE INDEX se queda básico — la
    decisión de cambiarlo a parcial es del usuario; C2 lo flaggea."""
    detection = _detection()
    snapshot = _snapshot(has_index=False, n_distinct=5000.0, null_frac=0.8)

    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)

    assert len(recs) == 1
    assert "parcial" in recs[0].justification.lower()


def test_recommendation_es_inmutable() -> None:
    """`Recommendation` es `frozen=True`: mutar atributos debe fallar.
    Garantiza que la recomendación viaja al validador (C3) y al prompt
    (C4) sin riesgo de mutación accidental."""
    detection = _detection()
    snapshot = _snapshot(has_index=False, n_distinct=5000.0)
    rec = recommend_for_seq_scan_on_large_table(detection, snapshot)[0]
    with pytest.raises(Exception):  # FrozenInstanceError
        rec.table = "other"  # type: ignore[misc]


def test_selectividad_con_n_distinct_negativo() -> None:
    """Postgres reporta n_distinct < 0 como ratio. `-0.5` significa "50%
    de filas son distintas". Para 500k filas → 250k distintos →
    selectividad ≈ 1/250k."""
    detection = _detection()
    snapshot = _snapshot(has_index=False, n_distinct=-0.5, estimated_rows=500_000)
    rec = recommend_for_seq_scan_on_large_table(detection, snapshot)[0]
    assert rec.selectivity == pytest.approx(1 / 250_000)


def test_isinstance_recommendation() -> None:
    """Sanity check del re-export: `Recommendation` se obtiene desde
    `motor` y los objetos devueltos son instancias."""
    detection = _detection()
    snapshot = _snapshot(has_index=False, n_distinct=5000.0)
    rec = recommend_for_seq_scan_on_large_table(detection, snapshot)[0]
    assert isinstance(rec, Recommendation)

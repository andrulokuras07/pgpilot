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


# --- D13: filtro de selectividad ----------------------------------


def test_d13_descarta_create_index_si_selectividad_baja() -> None:
    """Backlog D13: si la columna tiene 3 valores distintos en una tabla
    grande, NO recomendar índice. El recomendador devuelve un marker
    `skipped_low_selectivity` para que el log/JSONL lo conserve."""
    from motor import recommend_for_seq_scan_on_large_table

    detection = _detection()
    # 3 valores distintos en 10M filas → selectividad ≈ 0.33 (> umbral 0.2).
    snapshot = _snapshot(has_index=False, n_distinct=3.0, estimated_rows=10_000_000)

    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)

    assert len(recs) == 1
    assert recs[0].kind == "skipped_low_selectivity"
    assert recs[0].create_index_sql == ""
    assert "selectividad" in recs[0].justification.lower()


def test_d13_mantiene_create_index_si_selectividad_alta() -> None:
    """Selectividad alta (1/5000 = 0.02%) → la recomendación pasa el filtro."""
    from motor import recommend_for_seq_scan_on_large_table

    detection = _detection()
    snapshot = _snapshot(has_index=False, n_distinct=5000.0, estimated_rows=500_000)
    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)
    assert recs[0].kind == "create_index"


def test_d13_no_filtra_analyze() -> None:
    """`ANALYZE` no se filtra por selectividad: es barato y útil aunque
    la columna tenga pocos valores distintos."""
    from motor import recommend_for_seq_scan_on_large_table

    detection = _detection()
    # n_distinct = 3 → selectividad ~0.33 (sería filtrada para create_index)
    snapshot = _snapshot(has_index=True, n_distinct=3.0, estimated_rows=10_000_000)
    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)
    assert recs[0].kind == "analyze"


def test_d13_min_selectivity_configurable() -> None:
    """El umbral se puede sobrescribir por keyword (útil para experiments)."""
    from motor import recommend_for_seq_scan_on_large_table

    detection = _detection()
    snapshot = _snapshot(has_index=False, n_distinct=10.0, estimated_rows=1_000_000)
    # selectividad = 0.1; umbral default 0.2 → pasa.
    assert recommend_for_seq_scan_on_large_table(detection, snapshot)[0].kind == "create_index"
    # Con umbral 0.05 → ahora se descarta.
    recs_strict = recommend_for_seq_scan_on_large_table(detection, snapshot, min_selectivity=0.05)
    assert recs_strict[0].kind == "skipped_low_selectivity"


def test_d13_sin_stats_no_se_filtra() -> None:
    """Sin stats el recomendador no se atreve a descartar: deja la
    decisión al sandbox (C3)."""
    from motor import recommend_for_seq_scan_on_large_table

    detection = _detection()
    snapshot = _snapshot(has_index=False, n_distinct=None, null_frac=None)
    recs = recommend_for_seq_scan_on_large_table(detection, snapshot)
    assert recs[0].kind == "create_index"
    assert recs[0].selectivity is None


# --- D13: recomendador para D16 (missing_index) -------------------


def _detection_d16(
    *,
    table: str = "public.posts",
    column: str = "author_id",
    estimated_rows: int = 500_000,
) -> Detection:
    return Detection(
        found=True,
        confidence=0.95,
        evidence={
            "matches": [
                {
                    "table": table,
                    "column": column,
                    "estimated_rows": estimated_rows,
                    "rows_removed_by_filter": estimated_rows - 100,
                    "filter": f"({column} = 5)",
                    "suggested_index_name": f"idx_{table.split('.')[-1]}_{column}",
                    "suggested_sql": (
                        f"CREATE INDEX idx_{table.split('.')[-1]}_{column} "
                        f"ON {table} ({column});"
                    ),
                }
            ]
        },
    )


def test_recommend_for_missing_index_pasa_filtro() -> None:
    """D16 emite CREATE INDEX cuando la columna es selectiva."""
    from motor import recommend_for_missing_index

    detection = _detection_d16()
    snapshot = _snapshot(has_index=False, n_distinct=5000.0)
    recs = recommend_for_missing_index(detection, snapshot)
    assert len(recs) == 1
    assert recs[0].kind == "create_index"
    assert recs[0].create_index_sql.startswith("CREATE INDEX")
    assert recs[0].selectivity == pytest.approx(1 / 5000)


def test_recommend_for_missing_index_descarta_si_baja_selectividad() -> None:
    """D16 + D13: columna con 3 valores distintos en 10M filas → skip."""
    from motor import recommend_for_missing_index

    detection = _detection_d16(estimated_rows=10_000_000)
    snapshot = _snapshot(has_index=False, n_distinct=3.0, estimated_rows=10_000_000)
    recs = recommend_for_missing_index(detection, snapshot)
    assert recs[0].kind == "skipped_low_selectivity"


def test_recommend_for_missing_index_deteccion_vacia() -> None:
    from motor import recommend_for_missing_index

    empty = Detection(found=False, confidence=0.0, evidence={"matches": []})
    assert recommend_for_missing_index(empty, _snapshot(has_index=False)) == []


# --- D13: recomendador para D17 (partial index) -------------------


def test_recommend_for_partial_index_emite_create_partial_index() -> None:
    from motor import recommend_for_partial_index_opportunity

    detection = Detection(
        found=True,
        confidence=0.8,
        evidence={
            "matches": [
                {
                    "table": "public.notifications",
                    "column": "user_id",
                    "bool_column": "read",
                    "bool_value": "false",
                    "node_type": "Bitmap Heap Scan",
                    "filter": "(user_id = 1000) AND (NOT read)",
                    "suggested_index_name": "idx_notifications_user_id_partial",
                    "suggested_sql": (
                        "CREATE INDEX idx_notifications_user_id_partial "
                        "ON public.notifications (user_id) WHERE read = false;"
                    ),
                    "plan_rows": 50,
                }
            ]
        },
    )
    snapshot = _snapshot(
        has_index=False,
        n_distinct=5000.0,
        table_name="notifications",
        column="user_id",
    )

    recs = recommend_for_partial_index_opportunity(detection, snapshot)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.kind == "create_partial_index"
    assert rec.partial_predicate == "read = false"
    assert "WHERE read = false" in rec.create_index_sql
    # D13 NO se aplica aquí: aunque la selectividad de user_id solo fuera
    # mala, la utilidad del índice depende del predicado bool.
    assert rec.create_index_sql != ""


def test_partial_index_no_filtra_por_selectividad_baja() -> None:
    """Un user_id con pocos valores distintos no debe matar la
    recomendación de índice parcial — su selectividad efectiva depende
    del bool, no de la columna sola."""
    from motor import recommend_for_partial_index_opportunity

    detection = Detection(
        found=True,
        confidence=0.8,
        evidence={
            "matches": [
                {
                    "table": "public.notifications",
                    "column": "user_id",
                    "bool_column": "read",
                    "bool_value": "false",
                    "node_type": "Seq Scan",
                    "filter": "(user_id = 1) AND (NOT read)",
                    "plan_rows": 100,
                }
            ]
        },
    )
    snapshot = _snapshot(
        has_index=False,
        n_distinct=3.0,
        table_name="notifications",
        column="user_id",
    )
    recs = recommend_for_partial_index_opportunity(detection, snapshot)
    assert recs[0].kind == "create_partial_index"


# --- D13: recomendador para D18 (CREATE STATISTICS) ---------------


def test_recommend_for_cardinality_misestimate_emite_create_statistics() -> None:
    from motor import recommend_for_cardinality_misestimate

    detection = Detection(
        found=True,
        confidence=0.85,
        evidence={
            "matches": [
                {
                    "join_node_type": "Hash Join",
                    "plan_rows": 1948,
                    "actual_rows": 0,
                    "table": "public.users",
                    "columns": ["is_verified", "is_active"],
                    "filter": "(is_verified AND is_active)",
                    "scan_node_type": "Seq Scan",
                    "suggested_statistics_name": "stats_users_is_verified_is_active",
                    "suggested_sql": (
                        "CREATE STATISTICS stats_users_is_verified_is_active "
                        "ON is_verified, is_active FROM public.users;"
                    ),
                }
            ]
        },
    )
    snapshot = {
        "schema": {"public.users": {"indexes": []}},
        "sizes": {"public.users": {"estimated_rows": 50_000}},
        "stats": {
            "public.users": {
                "is_verified": {"has_stats": True, "n_distinct": 2.0, "null_frac": 0.0},
                "is_active": {"has_stats": True, "n_distinct": 2.0, "null_frac": 0.0},
            }
        },
    }

    recs = recommend_for_cardinality_misestimate(detection, snapshot)

    assert len(recs) == 1
    rec = recs[0]
    assert rec.kind == "create_statistics"
    assert rec.statistics_columns is not None
    assert set(rec.statistics_columns) == {"is_verified", "is_active"}
    assert "CREATE STATISTICS" in rec.create_index_sql
    # D18 no se filtra por D13 — son stats, no índice.
    assert rec.selectivity is None


# --- D13: orquestador `recommend(detections, snapshot)` -----------


def test_recommend_orquesta_todas_las_detecciones() -> None:
    """Recibe `dict[str, Detection]` y combina las recomendaciones de
    C1, D16, D17, D18 en una sola lista determinista."""
    from motor import recommend

    snapshot = _snapshot(has_index=False, n_distinct=5000.0)
    snapshot["stats"]["public.notifications"] = {
        "user_id": {"has_stats": True, "n_distinct": 5000.0, "null_frac": 0.0}
    }
    snapshot["schema"]["public.notifications"] = {"indexes": []}
    snapshot["sizes"]["public.notifications"] = {"estimated_rows": 200_000}

    detections = {
        "C1": Detection(found=False, confidence=0.0, evidence={"matches": []}),
        "D16": _detection_d16(),
        "D17": Detection(
            found=True,
            confidence=0.8,
            evidence={
                "matches": [
                    {
                        "table": "public.notifications",
                        "column": "user_id",
                        "bool_column": "read",
                        "bool_value": "false",
                        "node_type": "Bitmap Heap Scan",
                        "filter": "(user_id = 1) AND (NOT read)",
                        "plan_rows": 100,
                    }
                ]
            },
        ),
        "D18": Detection(found=False, confidence=0.0, evidence={"matches": []}),
    }

    recs = recommend(detections, snapshot)
    kinds = [r.kind for r in recs]
    assert "create_index" in kinds  # D16
    assert "create_partial_index" in kinds  # D17


def test_recommend_ignora_detecciones_no_registradas() -> None:
    """Detectores sin recomendador (D4-D12) no producen recomendaciones —
    su salida la consume el LLM/template como prosa."""
    from motor import recommend

    detections = {
        "D4": Detection(found=True, confidence=0.9, evidence={"matches": [{"foo": "bar"}]}),
        "D7": Detection(found=True, confidence=0.95, evidence={"matches": [{"foo": "bar"}]}),
    }
    snapshot = _snapshot(has_index=False)
    assert recommend(detections, snapshot) == []


# --- D13: helpers públicos ----------------------------------------


def test_compute_selectivity_es_publica() -> None:
    from motor import compute_selectivity

    stats = {"has_stats": True, "n_distinct": 100.0}
    assert compute_selectivity(stats, 1_000_000) == pytest.approx(1 / 100)
    assert compute_selectivity(None, 1_000_000) is None


def test_order_columns_by_selectivity() -> None:
    """Más selectiva primero. Sin stats al final preservando orden."""
    from motor import order_columns_by_selectivity

    snapshot = {
        "schema": {"public.t": {}},
        "sizes": {"public.t": {"estimated_rows": 1_000_000}},
        "stats": {
            "public.t": {
                "a": {"has_stats": True, "n_distinct": 100.0},  # 0.01
                "b": {"has_stats": True, "n_distinct": 5.0},  # 0.2
                "c": {"has_stats": True, "n_distinct": 10_000.0},  # 0.0001
                "d": {"has_stats": False, "n_distinct": None},  # sin stats
            }
        },
    }
    assert order_columns_by_selectivity(snapshot, "public.t", ["a", "b", "c", "d"]) == [
        "c",
        "a",
        "b",
        "d",
    ]


def test_d18_ordena_columnas_por_selectividad() -> None:
    """D18: `CREATE STATISTICS` lista las columnas con la más selectiva
    primero (sirve a la prosa del recomendador y al LLM)."""
    from motor import recommend_for_cardinality_misestimate

    detection = Detection(
        found=True,
        confidence=0.85,
        evidence={
            "matches": [
                {
                    "join_node_type": "Hash Join",
                    "plan_rows": 1948,
                    "actual_rows": 0,
                    "table": "public.users",
                    "columns": ["is_active", "tier"],  # tier es más selectiva
                    "filter": "(is_active AND tier = 'gold')",
                    "scan_node_type": "Seq Scan",
                }
            ]
        },
    )
    snapshot = {
        "schema": {"public.users": {"indexes": []}},
        "sizes": {"public.users": {"estimated_rows": 1_000_000}},
        "stats": {
            "public.users": {
                "is_active": {"has_stats": True, "n_distinct": 2.0},  # 0.5
                "tier": {"has_stats": True, "n_distinct": 5.0},  # 0.2
            }
        },
    }

    rec = recommend_for_cardinality_misestimate(detection, snapshot)[0]
    # tier (0.2) más selectiva que is_active (0.5) — debe ir primero.
    assert rec.statistics_columns == ("tier", "is_active")
    assert "tier, is_active" in rec.create_index_sql

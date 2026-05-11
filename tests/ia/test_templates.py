"""Tests del modo plantilla (LLM apagado) — C7.

Criterio "hecho cuando" del backlog:
> con el toggle apagado, el sistema devuelve recomendación con
> explicación legible (aunque más seca) sin llamar al LLM.

Esos dos requisitos se cubren acá (legibilidad + sin llamar al LLM) y
en `test_explain.py` (integración real del toggle vía orquestador).
"""

from __future__ import annotations

import pytest

from ia import Explanation, explain_from_template
from motor import Detection, Recommendation


@pytest.fixture
def detection_seq_scan() -> Detection:
    return Detection(
        found=True,
        confidence=1.0,
        evidence={
            "matches": [
                {
                    "table": "public.posts",
                    "column": "author_id",
                    "estimated_rows": 500_000,
                    "index_name": None,
                    "filter": "(author_id = 42)",
                }
            ]
        },
    )


@pytest.fixture
def recommendation_create_index() -> Recommendation:
    return Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id",
        create_index_sql='CREATE INDEX "idx_posts_author_id" ON "public"."posts" ("author_id");',
        justification="Tabla de 500,000 filas con filtro de igualdad sobre 'author_id'.",
        expected_impact="Seq Scan (500,000 filas) → Index Scan (~1,000 filas).",
        selectivity=0.002,
    )


@pytest.fixture
def recommendation_analyze() -> Recommendation:
    return Recommendation(
        kind="analyze",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id",
        create_index_sql='ANALYZE "public"."posts";',
        justification="Existe el índice btree pero el planner eligió Seq Scan.",
        expected_impact="Refresco de stats; planner reevalúa el costo del Index Scan.",
        selectivity=0.002,
    )


def test_explain_from_template_create_index_devuelve_explanation(
    detection_seq_scan: Detection, recommendation_create_index: Recommendation
) -> None:
    """Happy path: plantilla para CREATE INDEX produce una `Explanation`
    con source="template", confianza válida, prosa no vacía."""
    explanation = explain_from_template(detection_seq_scan, recommendation_create_index)

    assert isinstance(explanation, Explanation)
    assert explanation.source == "template"
    assert explanation.suggested_rewrite is None
    assert 0.0 <= explanation.confidence <= 1.0
    assert len(explanation.explanation) > 50  # legible, no es 1 línea


def test_explain_from_template_menciona_tabla_y_columna(
    detection_seq_scan: Detection, recommendation_create_index: Recommendation
) -> None:
    """La plantilla incluye los nombres reales del snapshot (R14: nada
    hardcodeado)."""
    explanation = explain_from_template(detection_seq_scan, recommendation_create_index)
    assert "public.posts" in explanation.explanation
    assert "author_id" in explanation.explanation


def test_explain_from_template_incluye_sql_sugerido(
    detection_seq_scan: Detection, recommendation_create_index: Recommendation
) -> None:
    """Aunque `suggested_rewrite` queda en None (la plantilla no
    inventa rewrites), el SQL del CREATE INDEX se incluye en la prosa
    para que el usuario lo pueda copiar."""
    explanation = explain_from_template(detection_seq_scan, recommendation_create_index)
    assert "CREATE INDEX" in explanation.explanation
    assert "idx_posts_author_id" in explanation.explanation


def test_explain_from_template_analyze_usa_plantilla_distinta(
    detection_seq_scan: Detection, recommendation_analyze: Recommendation
) -> None:
    """Para `kind="analyze"` la plantilla menciona ANALYZE y stats
    desactualizadas — no recomienda crear un índice nuevo."""
    explanation = explain_from_template(detection_seq_scan, recommendation_analyze)
    assert "ANALYZE" in explanation.explanation
    assert "estad" in explanation.explanation.lower()  # "estadísticas"
    # No debe sugerir crear un índice nuevo (ya existe).
    assert "CREATE INDEX" not in explanation.explanation


def test_explain_from_template_confianza_baja_sin_selectividad(
    detection_seq_scan: Detection,
) -> None:
    """Sin selectividad (tabla sin ANALYZE), la plantilla baja la
    confianza — somos honestos sobre cuánto sabemos."""
    rec_sin_stats = Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id",
        create_index_sql="CREATE INDEX ...",
        justification="x",
        expected_impact="y",
        selectivity=None,
    )
    explanation = explain_from_template(detection_seq_scan, rec_sin_stats)
    assert explanation.confidence < 0.8

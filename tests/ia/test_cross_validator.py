"""Tests de validación cruzada — C6.

Criterio "hecho cuando" del backlog:
> test plantando una respuesta del LLM con un índice que ya existe
> verifica que se descarta.

Ese caso se cubre en `test_cross_validate_rechaza_create_index_duplicado`.
También cubrimos: columnas inexistentes, SQL no parseable, recomendación
con columna inválida, suggested_rewrite vacío (passing case).

La verificación opcional con sandbox tiene un test separado con
`monkeypatch` que mockea la llamada — los tests unitarios no requieren
Docker.
"""

from __future__ import annotations

from typing import Any

import pytest

from ia import CrossValidationResult, LLMResponseSchema, cross_validate
from motor import Recommendation


@pytest.fixture
def snapshot_posts() -> dict[str, Any]:
    """Snapshot mínimo con una tabla `posts` con columnas y un índice."""
    return {
        "schema": {
            "public.posts": {
                "schema": "public",
                "name": "posts",
                "columns": [
                    {"name": "id", "data_type": "bigint", "is_nullable": False},
                    {"name": "author_id", "data_type": "integer", "is_nullable": False},
                    {"name": "title", "data_type": "text", "is_nullable": True},
                ],
                "indexes": [
                    {
                        "name": "posts_pkey",
                        "columns": ["id"],
                        "method": "btree",
                        "is_unique": True,
                        "is_primary": True,
                    },
                    {
                        "name": "idx_posts_existente",
                        "columns": ["author_id"],
                        "method": "btree",
                        "is_unique": False,
                        "is_primary": False,
                    },
                ],
                "foreign_keys": [],
            }
        },
        "sizes": {},
        "stats": {},
    }


@pytest.fixture
def rec_create_index_valido() -> Recommendation:
    return Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id_nuevo",  # nombre nuevo, no duplicado
        create_index_sql="CREATE INDEX idx_posts_author_id_nuevo ON public.posts (author_id);",
        justification="x",
        expected_impact="y",
        selectivity=0.01,
    )


def _response(
    explanation: str = "ok",
    suggested_rewrite: str | None = None,
    confidence: float = 0.8,
) -> LLMResponseSchema:
    return LLMResponseSchema(
        explanation=explanation,
        suggested_rewrite=suggested_rewrite,
        confidence=confidence,
    )


# --- happy path ----------------------------------------------------


def test_cross_validate_happy_path_sin_rewrite(
    snapshot_posts: dict[str, Any], rec_create_index_valido: Recommendation
) -> None:
    """Recomendación válida + respuesta sin rewrite → pasa."""
    result = cross_validate(_response(), rec_create_index_valido, snapshot_posts)
    assert isinstance(result, CrossValidationResult)
    assert result.passed is True
    assert result.reasons == []
    assert result.sandbox_verdict is None  # no se pasó sandbox_pool


def test_cross_validate_happy_path_con_rewrite_valido(
    snapshot_posts: dict[str, Any], rec_create_index_valido: Recommendation
) -> None:
    rewrite = "SELECT id, title FROM posts WHERE author_id = 42"
    result = cross_validate(
        _response(suggested_rewrite=rewrite),
        rec_create_index_valido,
        snapshot_posts,
    )
    assert result.passed is True


# --- rechazos clave ------------------------------------------------


def test_cross_validate_rechaza_create_index_duplicado(
    snapshot_posts: dict[str, Any], rec_create_index_valido: Recommendation
) -> None:
    """**Criterio "hecho cuando" de C6**: si el LLM propone un CREATE INDEX
    con un nombre que ya existe en el schema, la sugerencia se descarta.
    """
    rewrite = "CREATE INDEX idx_posts_existente ON posts (author_id);"
    result = cross_validate(
        _response(suggested_rewrite=rewrite),
        rec_create_index_valido,
        snapshot_posts,
    )
    assert result.passed is False
    assert any("idx_posts_existente" in r for r in result.reasons)


def test_cross_validate_rechaza_columna_inexistente_en_rewrite(
    snapshot_posts: dict[str, Any], rec_create_index_valido: Recommendation
) -> None:
    """LLM inventa una columna que no existe → R14, descarte."""
    rewrite = "SELECT columna_fantasma FROM posts WHERE author_id = 1"
    result = cross_validate(
        _response(suggested_rewrite=rewrite),
        rec_create_index_valido,
        snapshot_posts,
    )
    assert result.passed is False
    assert any("columna_fantasma" in r for r in result.reasons)


def test_cross_validate_rechaza_rewrite_no_parseable(
    snapshot_posts: dict[str, Any], rec_create_index_valido: Recommendation
) -> None:
    """SQL que no parsea con sqlglot → descarte (R3 explicit del backlog)."""
    rewrite = "SELECT SELECT FROM WHERE)))"
    result = cross_validate(
        _response(suggested_rewrite=rewrite),
        rec_create_index_valido,
        snapshot_posts,
    )
    assert result.passed is False
    assert any("parsea" in r.lower() or "sqlglot" in r.lower() for r in result.reasons)


def test_cross_validate_rechaza_recommendation_con_columna_inexistente(
    snapshot_posts: dict[str, Any],
) -> None:
    """Defensa en profundidad: si llegara una `Recommendation` cuya
    columna no está en el snapshot, descartamos (no debería pasar,
    pero protege ante bugs upstream)."""
    rec_invalida = Recommendation(
        kind="create_index",
        table="public.posts",
        column="columna_que_no_existe",
        index_method="btree",
        index_name="idx_invalido",
        create_index_sql="...",
        justification="x",
        expected_impact="y",
        selectivity=None,
    )
    result = cross_validate(_response(), rec_invalida, snapshot_posts)
    assert result.passed is False
    assert any("columna_que_no_existe" in r for r in result.reasons)


def test_cross_validate_rechaza_recommendation_index_duplicado(
    snapshot_posts: dict[str, Any],
) -> None:
    """Si la `Recommendation` misma (no el rewrite) propone un nombre
    de índice que ya existe en la tabla, descartamos."""
    rec = Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_existente",  # ya existe en el snapshot
        create_index_sql="CREATE INDEX idx_posts_existente ON public.posts (author_id);",
        justification="x",
        expected_impact="y",
        selectivity=None,
    )
    result = cross_validate(_response(), rec, snapshot_posts)
    assert result.passed is False
    assert any("idx_posts_existente" in r for r in result.reasons)


# --- caso analyze (kind="analyze" no chequea duplicado de índice) -


def test_cross_validate_analyze_no_chequea_indice_duplicado(
    snapshot_posts: dict[str, Any],
) -> None:
    """`kind="analyze"` referencia un índice existente *a propósito*
    (es el sentido del verdict). No debe disparar el chequeo de
    duplicado."""
    rec = Recommendation(
        kind="analyze",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_existente",  # existe — eso es lo que C2 reporta
        create_index_sql="ANALYZE public.posts;",
        justification="x",
        expected_impact="y",
        selectivity=0.01,
    )
    result = cross_validate(_response(), rec, snapshot_posts)
    assert result.passed is True


# --- sandbox opcional ----------------------------------------------


def test_cross_validate_sandbox_pool_validated_no_agrega_razones(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_posts: dict[str, Any],
    rec_create_index_valido: Recommendation,
) -> None:
    """Si sandbox devuelve verdict="validated", la validación cruzada
    pasa sin agregar razones. Mockeamos la llamada para no necesitar Docker."""

    class _FakeResult:
        verdict = "validated"

    monkeypatch.setattr(
        "ia.cross_validator.validate_index_recommendation",
        lambda *a, **kw: _FakeResult(),
        raising=False,
    )
    # El import vive adentro de `_sandbox_verdict`; parchamos el path real.
    import sandbox

    monkeypatch.setattr(sandbox, "validate_index_recommendation", lambda *a, **kw: _FakeResult())

    fake_pool = object()
    result = cross_validate(
        _response(),
        rec_create_index_valido,
        snapshot_posts,
        sandbox_pool=fake_pool,
        original_sql="SELECT 1 FROM posts WHERE author_id = 5000",
    )
    assert result.passed is True
    assert result.sandbox_verdict == "validated"


def test_cross_validate_sandbox_pool_discarded_descarta(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_posts: dict[str, Any],
    rec_create_index_valido: Recommendation,
) -> None:
    """Si sandbox devuelve verdict="discarded", la sugerencia se rechaza."""

    class _FakeResult:
        verdict = "discarded"

    import sandbox

    monkeypatch.setattr(sandbox, "validate_index_recommendation", lambda *a, **kw: _FakeResult())

    fake_pool = object()
    result = cross_validate(
        _response(),
        rec_create_index_valido,
        snapshot_posts,
        sandbox_pool=fake_pool,
        original_sql="SELECT 1 FROM posts WHERE author_id = 5000",
    )
    assert result.passed is False
    assert result.sandbox_verdict == "discarded"
    assert any("sandbox" in r.lower() for r in result.reasons)

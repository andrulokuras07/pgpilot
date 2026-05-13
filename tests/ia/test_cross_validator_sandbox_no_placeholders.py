"""Regresión para Bug 1 — el sandbox debe recibir SQL ejecutable.

Antes del fix, `cross_validate` le pasaba al sandbox la SQL sanitizada
(con `$LITERAL_X_Y`), y Postgres respondía con `SyntaxError: syntax error
at or near "$"` al ejecutar el EXPLAIN. La sanitización solo aplica a las
salidas hacia el LLM (R4); el sandbox es infraestructura local de PgPilot
y necesita SQL ejecutable.

Este test monkeypatchea `sandbox.validate_index_recommendation` y verifica
que la SQL recibida no contiene placeholders.
"""

from __future__ import annotations

from typing import Any

import pytest

from ia import LLMResponseSchema, cross_validate
from motor import Recommendation


@pytest.fixture
def snapshot_posts() -> dict[str, Any]:
    return {
        "schema": {
            "public.posts": {
                "columns": [
                    {"name": "id"},
                    {"name": "author_id"},
                ],
                "indexes": [],
                "foreign_keys": [],
            }
        },
        "sizes": {},
        "stats": {},
    }


@pytest.fixture
def rec() -> Recommendation:
    return Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id_nuevo",
        create_index_sql="CREATE INDEX idx_posts_author_id_nuevo ON public.posts (author_id);",
        justification="x",
        expected_impact="y",
        selectivity=0.01,
    )


def test_cross_validate_pasa_sql_sin_placeholders_al_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_posts: dict[str, Any],
    rec: Recommendation,
) -> None:
    """La SQL que llega a `validate_index_recommendation` NO debe contener
    placeholders del sanitizador. Es ejecutable contra Postgres."""

    captured: dict[str, Any] = {}

    class _FakeResult:
        verdict = "validated"

    def fake_validate(pool: Any, snapshot: Any, query: str, recommendation: Any) -> Any:
        captured["query"] = query
        return _FakeResult()

    import sandbox

    monkeypatch.setattr(sandbox, "validate_index_recommendation", fake_validate)

    response = LLMResponseSchema(explanation="ok", suggested_rewrite=None, confidence=0.9)
    original = "SELECT * FROM posts WHERE author_id = 5000"
    cross_validate(
        response,
        rec,
        snapshot_posts,
        sandbox_pool=object(),
        original_sql=original,
    )

    assert "query" in captured, "El sandbox debió ser invocado"
    sql_recibida = captured["query"]
    assert "$LITERAL" not in sql_recibida, (
        f"El sandbox recibió SQL con placeholders del sanitizador: {sql_recibida!r}. "
        "Bug 1: la sanitización es solo para el LLM (R4); el sandbox necesita SQL ejecutable."
    )
    assert sql_recibida == original

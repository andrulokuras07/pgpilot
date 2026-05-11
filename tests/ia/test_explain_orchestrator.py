"""Tests del orquestador `explain_recommendation` — integración C5+C6+C7.

Acá probamos el flujo end-to-end de la capa de explicación con
`monkeypatch` sobre el cliente LLM. Los criterios "hecho cuando" de
C5 y C7 viven acá en su forma más fuerte:

- **C5 hecho-cuando**: respuesta JSON malformada → sistema cae a
  plantilla sin crashear → `Explanation.source == "template"`.
- **C7 hecho-cuando**: `LLM_ENABLED=false` → no se llama al LLM →
  `Explanation.source == "template"`, prosa legible con SQL incluido.

C6 hecho-cuando (índice duplicado) vive en `test_cross_validator.py`;
acá se verifica que el orquestador honra la decisión de C6 (descartar
LLM → caer a plantilla).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ia import (
    Explanation,
    LLMPrompt,
    SanitizedQuery,
    explain_recommendation,
    sanitize,
)
from motor import Detection, Recommendation, parse_explain

# --- fixtures comunes ---------------------------------------------


@pytest.fixture
def detection() -> Detection:
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
def plan() -> Any:
    return parse_explain(
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "posts",
                "Startup Cost": 0.0,
                "Total Cost": 12345.0,
                "Plan Rows": 5000,
                "Plan Width": 50,
                "Filter": "(author_id = 42)",
            }
        }
    )


@pytest.fixture
def recommendation() -> Recommendation:
    return Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id_nuevo",
        create_index_sql="CREATE INDEX idx_posts_author_id_nuevo ON public.posts (author_id);",
        justification="Tabla 500k filas, filtro de igualdad sobre author_id sin índice utilizable.",
        expected_impact="Seq Scan → Index Scan (~1,000 filas visitadas).",
        selectivity=0.002,
    )


@pytest.fixture
def sanitized_query() -> SanitizedQuery:
    return sanitize("SELECT * FROM posts WHERE author_id = 42")


@pytest.fixture
def snapshot() -> dict[str, Any]:
    return {
        "schema": {
            "public.posts": {
                "columns": [
                    {"name": "id"},
                    {"name": "author_id"},
                    {"name": "title"},
                ],
                "indexes": [
                    {
                        "name": "posts_pkey",
                        "columns": ["id"],
                        "method": "btree",
                    }
                ],
            }
        },
        "sizes": {},
        "stats": {},
    }


# --- helpers para simular el LLM ----------------------------------


def _http_response_with(payload: dict[str, Any]) -> httpx.Response:
    body = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    return httpx.Response(200, json=body)


def _http_response_raw(text: str) -> httpx.Response:
    body = {"content": [{"type": "text", "text": text}]}
    return httpx.Response(200, json=body)


# --- camino oro: LLM válido ---------------------------------------


def test_explain_recommendation_happy_path_llm(
    monkeypatch: pytest.MonkeyPatch,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    """LLM devuelve JSON válido + cross-validation pasa → source="llm"."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return _http_response_with(
            {
                "explanation": "Explicación válida del LLM",
                "suggested_rewrite": None,
                "confidence": 0.91,
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = explain_recommendation(
        detection, plan, recommendation, sanitized_query, snapshot=snapshot
    )
    assert isinstance(result, Explanation)
    assert result.source == "llm"
    assert result.explanation == "Explicación válida del LLM"
    assert result.confidence == 0.91


# --- C5 hecho-cuando: malformed → fallback a plantilla ------------


def test_explain_recommendation_llm_malformado_cae_a_plantilla(
    monkeypatch: pytest.MonkeyPatch,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    """**Backlog C5 hecho-cuando**: respuesta JSON malformada del LLM
    → el sistema NO crashea, devuelve plantilla determinística."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        # SIEMPRE responde basura (agotamos el reintento)
        return _http_response_raw("{ esto no es json válido ")

    monkeypatch.setattr(httpx, "post", fake_post)

    result = explain_recommendation(
        detection, plan, recommendation, sanitized_query, snapshot=snapshot
    )
    assert result.source == "template"
    assert "public.posts" in result.explanation
    assert "author_id" in result.explanation


# --- C7 hecho-cuando: LLM apagado → plantilla ----------------------


def test_explain_recommendation_llm_apagado_no_llama_llm(
    monkeypatch: pytest.MonkeyPatch,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    """**Backlog C7 hecho-cuando**: con `LLM_ENABLED=false`, el sistema
    devuelve recomendación con explicación legible sin llamar al LLM."""
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

    httpx_called = {"count": 0}

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        httpx_called["count"] += 1
        raise AssertionError("no se debió llamar a httpx.post con LLM_ENABLED=false")

    monkeypatch.setattr(httpx, "post", fake_post)

    result = explain_recommendation(
        detection, plan, recommendation, sanitized_query, snapshot=snapshot
    )
    assert result.source == "template"
    assert httpx_called["count"] == 0
    assert len(result.explanation) > 50
    assert "CREATE INDEX" in result.explanation


def test_explain_recommendation_sin_api_key_cae_a_plantilla(
    monkeypatch: pytest.MonkeyPatch,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    """Sin `ANTHROPIC_API_KEY` el cliente C4 levanta `LLMDisabledError`
    — el orquestador lo atrapa y cae a plantilla. Esto es la rama
    "operación sin LLM" del deployment."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    result = explain_recommendation(
        detection, plan, recommendation, sanitized_query, snapshot=snapshot
    )
    assert result.source == "template"


# --- C6 honrado por el orquestador --------------------------------


def test_explain_recommendation_cross_validation_falla_cae_a_plantilla(
    monkeypatch: pytest.MonkeyPatch,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    """LLM devuelve JSON válido (C5 pasa) PERO referencia una columna
    inexistente (C6 falla) → orquestador cae a plantilla, no muestra
    la respuesta del LLM al usuario."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return _http_response_with(
            {
                "explanation": "Voy a inventar una columna inexistente.",
                "suggested_rewrite": "SELECT esta_columna_no_existe FROM posts WHERE author_id = 1",
                "confidence": 0.99,
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = explain_recommendation(
        detection, plan, recommendation, sanitized_query, snapshot=snapshot
    )
    assert result.source == "template"  # NO la prosa del LLM
    # La plantilla NUNCA usa la prosa del LLM, así que no debe colarse:
    assert "esta_columna_no_existe" not in result.explanation


# --- robustez ------------------------------------------------------


def test_explain_recommendation_red_caida_cae_a_plantilla(
    monkeypatch: pytest.MonkeyPatch,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    """Si el endpoint de Anthropic está caído, el orquestador no
    propaga la excepción al backend — degrada elegante a plantilla.
    Esto cubre la garantía "el producto funciona sin LLM" para casos
    transitorios además del toggle explícito (R5)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def boom(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", boom)

    result = explain_recommendation(
        detection, plan, recommendation, sanitized_query, snapshot=snapshot
    )
    assert result.source == "template"

"""Tests del validador Pydantic — C5.

Dos capas:

1. **Unit (función pura)**: `parse_llm_response` se valida con strings
   conocidos (válidos, malformados, fuera de rango). Sin red.
2. **Reintentos**: `request_validated_explanation` se prueba con
   `monkeypatch` sobre `call_llm` para simular un LLM que devuelve
   basura una vez y luego JSON válido.

El criterio "hecho cuando" del backlog C5 es:
> un test mete una respuesta JSON malformada y el sistema cae al modo
> plantilla sin crashear.

Esa caída completa (a plantilla) se prueba acá indirectamente
(`LLMResponseInvalid` se levanta) y directamente en `test_explain.py`
(orquestador que conecta C5 con C7).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ia import (
    LLMPrompt,
    LLMResponseInvalid,
    LLMResponseSchema,
)
from ia import llm as ia_llm
from ia import (
    parse_llm_response,
    request_validated_explanation,
)


def _dummy_prompt() -> LLMPrompt:
    """LLMPrompt sintético: el contenido no importa porque `call_llm`
    está monkeypatched en los tests que lo usan."""
    return LLMPrompt(
        system="", messages=[{"role": "user", "content": "x"}], expected_output_schema={}
    )


# --- parse_llm_response: forma del JSON ---------------------------


def test_parse_llm_response_happy_path() -> None:
    raw = json.dumps({"explanation": "Seq Scan...", "suggested_rewrite": None, "confidence": 0.9})
    parsed = parse_llm_response(raw)
    assert isinstance(parsed, LLMResponseSchema)
    assert parsed.explanation == "Seq Scan..."
    assert parsed.suggested_rewrite is None
    assert parsed.confidence == 0.9


def test_parse_llm_response_acepta_suggested_rewrite_string() -> None:
    raw = json.dumps(
        {
            "explanation": "explicación",
            "suggested_rewrite": "SELECT 1",
            "confidence": 0.5,
        }
    )
    parsed = parse_llm_response(raw)
    assert parsed.suggested_rewrite == "SELECT 1"


def test_parse_llm_response_ignora_campos_extra() -> None:
    """Pydantic v2 default: campos extra no rompen — los ignora. Esto
    nos protege ante cambios menores del modelo (ej. Anthropic suma un
    `model_id` propio en futuras versiones)."""
    raw = json.dumps(
        {
            "explanation": "x",
            "suggested_rewrite": None,
            "confidence": 1.0,
            "extra_field": "ignorame",
        }
    )
    parsed = parse_llm_response(raw)
    assert parsed.explanation == "x"


# --- parse_llm_response: rechazos ---------------------------------


def test_parse_llm_response_rechaza_json_malformado() -> None:
    """Backlog C5 hecho-cuando: respuesta inválida no crashea."""
    with pytest.raises(LLMResponseInvalid) as exc_info:
        parse_llm_response("esto no es JSON {{{")
    assert "no es JSON" in exc_info.value.reason or "schema" in exc_info.value.reason
    assert exc_info.value.raw.startswith("esto no es JSON")


def test_parse_llm_response_rechaza_explanation_vacio() -> None:
    raw = json.dumps({"explanation": "", "suggested_rewrite": None, "confidence": 0.5})
    with pytest.raises(LLMResponseInvalid):
        parse_llm_response(raw)


def test_parse_llm_response_rechaza_confidence_fuera_de_rango() -> None:
    raw = json.dumps({"explanation": "x", "suggested_rewrite": None, "confidence": 1.5})
    with pytest.raises(LLMResponseInvalid):
        parse_llm_response(raw)


def test_parse_llm_response_rechaza_falta_explanation() -> None:
    raw = json.dumps({"suggested_rewrite": None, "confidence": 0.5})
    with pytest.raises(LLMResponseInvalid):
        parse_llm_response(raw)


def test_parse_llm_response_rechaza_confidence_string() -> None:
    """Pydantic coerce strings numéricos a float por default. Validamos
    que un confidence fuera del rango aun siendo numérico se rechaza."""
    raw = json.dumps({"explanation": "x", "suggested_rewrite": None, "confidence": -0.1})
    with pytest.raises(LLMResponseInvalid):
        parse_llm_response(raw)


# --- request_validated_explanation: reintentos -------------------


def test_request_validated_explanation_reintenta_una_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backlog C5: si el LLM devuelve mal formado, reintentar una vez.
    Simulamos: primer call → basura; segundo call → JSON válido.
    """
    calls: list[int] = []

    def fake_call(prompt: LLMPrompt, **kwargs: Any) -> str:
        calls.append(1)
        if len(calls) == 1:
            return "{{ no es JSON"
        return json.dumps({"explanation": "ok", "suggested_rewrite": None, "confidence": 0.7})

    monkeypatch.setattr(ia_llm, "call_llm", fake_call)
    # parche también el binding importado en validator
    monkeypatch.setattr("ia.validator.call_llm", fake_call)

    parsed = request_validated_explanation(_dummy_prompt(), max_retries=1)
    assert parsed.explanation == "ok"
    assert len(calls) == 2  # 1 fallo + 1 éxito


def test_request_validated_explanation_falla_tras_reintentos_agotados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el LLM sigue devolviendo basura tras el reintento, levantamos
    `LLMResponseInvalid`. El orquestador (C7) atrapa esta excepción y
    cae a plantilla — eso se prueba en test_explain.py.
    """
    calls: list[int] = []

    def fake_call(prompt: LLMPrompt, **kwargs: Any) -> str:
        calls.append(1)
        return "basura permanente"

    monkeypatch.setattr("ia.validator.call_llm", fake_call)

    with pytest.raises(LLMResponseInvalid):
        request_validated_explanation(_dummy_prompt(), max_retries=1)
    assert len(calls) == 2  # intento inicial + 1 reintento


def test_request_validated_explanation_max_retries_cero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con `max_retries=0` no hay reintentos: una sola llamada y, si
    falla, levanta. Útil para el modo "perfil rápido" del backend."""
    calls: list[int] = []

    def fake_call(prompt: LLMPrompt, **kwargs: Any) -> str:
        calls.append(1)
        return "no es json"

    monkeypatch.setattr("ia.validator.call_llm", fake_call)

    with pytest.raises(LLMResponseInvalid):
        request_validated_explanation(_dummy_prompt(), max_retries=0)
    assert len(calls) == 1

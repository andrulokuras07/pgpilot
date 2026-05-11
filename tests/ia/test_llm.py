"""Tests del cliente LLM C4.

Dos capas:

1. **Unit tests**: cubren la rama R5 ("LLM apagado") y el parseo del
   payload de respuesta. No hacen red — usan `monkeypatch` para
   simular el response de Anthropic o para variar variables de entorno.
2. **Integration test** (`@pytest.mark.llm`): manda un prompt real al
   LLM y verifica que devuelve JSON parseable con los campos esperados.
   Skip automático si no hay `ANTHROPIC_API_KEY`. Este es el "hecho
   cuando" del backlog para C4.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

from ia import (
    LLMDisabledError,
    LLMError,
    LLMPrompt,
    build_explanation_prompt,
    call_llm,
    sanitize,
)
from ia.llm import _extract_text
from motor import Detection, Recommendation, parse_explain


def _prompt() -> LLMPrompt:
    return build_explanation_prompt(
        Detection(found=True, confidence=1.0, evidence={"matches": []}),
        parse_explain(
            {
                "Plan": {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 1.0,
                    "Plan Rows": 1,
                    "Plan Width": 1,
                }
            }
        ),
        Recommendation(
            kind="create_index",
            table="public.posts",
            column="author_id",
            index_method="btree",
            index_name="idx_posts_author_id",
            create_index_sql="CREATE INDEX ...",
            justification="...",
            expected_impact="...",
            selectivity=None,
        ),
        sanitize("SELECT * FROM posts WHERE author_id = 5"),
    )


# --- R5: LLM apagado o sin API key ---------------------------------


def test_llm_disabled_levanta_LLMDisabledError(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cumple R5: con `LLM_ENABLED=false`, el cliente levanta una
    excepción específica que la capa C7 puede atrapar para caer a
    plantillas locales."""
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    with pytest.raises(LLMDisabledError):
        call_llm(_prompt())


def test_falta_api_key_levanta_LLMDisabledError(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin `ANTHROPIC_API_KEY` y sin `api_key` explícito, no se llama al
    servicio. El error es del mismo tipo que LLM_ENABLED=false para
    que C7 los maneje con una sola rama."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_ENABLED", raising=False)
    with pytest.raises(LLMDisabledError):
        call_llm(_prompt())


# --- parseo de la respuesta -----------------------------------------


def test_extract_text_junta_bloques() -> None:
    """Anthropic puede devolver varios bloques `text`. El extractor los
    concatena y descarta blocks de otros tipos (tool_use, etc.)."""
    payload = {
        "content": [
            {"type": "text", "text": '{"explanation": "hola",'},
            {"type": "text", "text": ' "suggested_rewrite": null, "confidence": 0.9}'},
            {"type": "tool_use", "name": "ignorado"},
        ]
    }
    text = _extract_text(payload)
    parsed = json.loads(text)
    assert parsed == {"explanation": "hola", "suggested_rewrite": None, "confidence": 0.9}


def test_extract_text_levanta_si_no_hay_text() -> None:
    """Respuesta sin bloques de texto: el cliente lo trata como error
    del servicio (no como JSON vacío)."""
    with pytest.raises(LLMError):
        _extract_text({"content": [{"type": "tool_use"}]})


def test_extract_text_strip_fences_markdown_json() -> None:
    """Quirk conocido de Claude (verificado empíricamente con sonnet-4-6,
    2026-05-11): aun con prompt prohibiendo markdown, suele envolver el
    JSON en ` ```json ... ``` `. El extractor las quita."""
    payload = {
        "content": [
            {
                "type": "text",
                "text": '```json\n{"explanation": "x", "suggested_rewrite": null, "confidence": 0.9}\n```',
            }
        ]
    }
    text = _extract_text(payload)
    parsed = json.loads(text)
    assert parsed["confidence"] == 0.9


def test_extract_text_strip_fences_sin_lenguaje() -> None:
    """Fences sin etiqueta de lenguaje (` ``` ... ``` `) también se quitan."""
    payload = {"content": [{"type": "text", "text": '```\n{"k": 1}\n```'}]}
    assert json.loads(_extract_text(payload)) == {"k": 1}


def test_extract_text_no_toca_fences_embebidas() -> None:
    """Si el texto no es UN solo bloque envuelto en fences, no toca nada.
    Una respuesta que contiene fences embebidas (ej. ejemplo de código
    dentro de prosa) debe preservarlas tal cual."""
    raw = "aquí va una explicación con ejemplo:\n```sql\nSELECT 1\n```\nlisto"
    payload = {"content": [{"type": "text", "text": raw}]}
    assert _extract_text(payload) == raw


def test_extract_text_levanta_si_payload_malformado() -> None:
    with pytest.raises(LLMError):
        _extract_text({"no_content": "x"})


# --- error de transporte / status ----------------------------------


def test_call_llm_mapea_status_no_2xx_a_LLMError(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si Anthropic responde con 4xx/5xx, levantamos `LLMError` con el
    status y un fragmento del body para que el caller logue (C8)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(429, text="rate limit hit")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(LLMError, match="429"):
        call_llm(_prompt())


def test_call_llm_red_caida_levanta_LLMError(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network error de httpx se envuelve en `LLMError` para que C8
    pueda logearlo sin que la excepción de transporte cruda fugue."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def boom(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("conn refused")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(LLMError, match="red"):
        call_llm(_prompt())


def test_call_llm_happy_path_simulado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Camino feliz sin red real: simulamos un 200 con un payload de
    Anthropic válido y verificamos que el cliente devuelve el texto."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    fake_body = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"explanation": "Seq Scan...", "suggested_rewrite": None, "confidence": 0.85}
                ),
            }
        ]
    }

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json=fake_body)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = call_llm(_prompt())
    parsed = json.loads(result)
    assert parsed["confidence"] == 0.85


# --- integration con LLM real (hecho-cuando de C4) -----------------


@pytest.mark.llm
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="Sin ANTHROPIC_API_KEY: el test LLM real se omite.",
)
def test_llm_responde_json_parseable_para_deteccion_seq_scan() -> None:
    """Criterio "hecho cuando" del backlog C4: para una detección real
    de Seq Scan + recomendación del motor, el LLM responde un JSON
    parseable con los tres campos esperados.

    No validamos la calidad de la explicación (eso es para QA manual);
    solo que la forma del output respete el schema acordado.
    """
    result = call_llm(_prompt())
    parsed = json.loads(result)
    assert "explanation" in parsed
    assert "suggested_rewrite" in parsed
    assert "confidence" in parsed
    assert isinstance(parsed["explanation"], str)
    assert parsed["suggested_rewrite"] is None or isinstance(parsed["suggested_rewrite"], str)
    assert 0.0 <= float(parsed["confidence"]) <= 1.0

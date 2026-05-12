"""Orquestador de la capa de explicación — C5 + C6 + C7 + C8.

Tie de los tres tickets de explicación en una sola función:
`explain_recommendation`. El backend (C9) llama esto pasándole los
hechos del motor y obtiene una `Explanation` lista para devolver al
frontend, sin saber si la prosa vino del LLM o de plantilla.

Flujo:

1. Si `LLM_ENABLED=false` o no hay `ANTHROPIC_API_KEY`: salta el LLM
   y va directo a plantilla (R5).
2. Caso normal: arma prompt (C4), llama al LLM, valida con Pydantic
   (C5, reintentos incluidos), valida cruzado contra snapshot (C6).
3. Si cualquiera de las dos validaciones falla, cae a plantilla (C7)
   sin propagar la excepción al backend.
4. Errores HTTP/red del LLM también caen a plantilla — el producto
   no debe romperse porque Anthropic no respondió (R5).
5. **C8**: cada uno de los caminos anteriores deja un registro JSON
   en el archivo de logs (`ia/logs.py`). El registro incluye la
   detección, recomendación, query sanitizada, raw response del LLM
   (truncado), validaciones que pasaron/fallaron, y la prosa final
   mostrada al usuario.

El campo `Explanation.source` distingue cuál fue. El backend lo expone
al frontend para que, ante `source="template"`, una etiqueta sutil
indique "explicación generada sin IA".

Cumple R1+R3+R5: el LLM nunca tiene la palabra final; toda salida
se valida; la pipeline degrada elegante; todo queda registrado.
"""

from __future__ import annotations

from typing import Any

from ia.cross_validator import cross_validate
from ia.llm import LLMDisabledError, LLMError
from ia.logs import (
    build_base_record,
    final_shown_payload,
    llm_payload,
    log_llm_interaction,
    response_to_text,
)
from ia.prompt import build_explanation_prompt
from ia.sanitizer import SanitizedQuery
from ia.templates import Explanation, explain_from_template
from ia.validator import LLMResponseInvalid, request_validated_explanation
from motor import Detection, ExplainResult, Recommendation


def explain_recommendation(
    detection: Detection,
    plan: ExplainResult,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    *,
    snapshot: dict[str, Any],
    sandbox_pool: Any | None = None,
    max_retries: int = 1,
    request_id: str | None = None,
) -> Explanation:
    """Devuelve la `Explanation` final para una recomendación del motor.

    `sandbox_pool` opcional: si se pasa, C6 corre también la validación
    estructural contra el sandbox (B16). Si es `None` se omite esa parte
    (tests unit, modo offline, perfil "rápido" del backend).

    `request_id` opcional: identificador propagado al log estructurado
    de C8 para correlacionar con la request HTTP del backend. Si no se
    pasa, `ia.logs` genera uno propio.

    Garantía: nunca propaga `LLMDisabledError`, `LLMError` ni
    `LLMResponseInvalid`. Esos casos caen silenciosamente a plantilla.
    Cualquier otra excepción (bug interno, snapshot corrupto) sí se
    propaga — el caller decide qué hacer.
    """
    base = build_base_record(detection, recommendation, sanitized_query, request_id=request_id)

    # --- Camino 1: el LLM no se llama o falla antes de devolver algo válido
    try:
        prompt = build_explanation_prompt(detection, plan, recommendation, sanitized_query)
        response = request_validated_explanation(prompt, max_retries=max_retries)
    except LLMDisabledError as exc:
        # R5: LLM apagado o sin API key → plantilla directa.
        explanation = explain_from_template(detection, recommendation)
        log_llm_interaction(
            {
                **base,
                "outcome": "llm_disabled",
                "llm": llm_payload(called=False, error=str(exc)),
                "final_shown": final_shown_payload(explanation),
            }
        )
        return explanation
    except LLMError as exc:
        # Red caída, status no-2xx — no rompemos el producto, plantilla.
        explanation = explain_from_template(detection, recommendation)
        log_llm_interaction(
            {
                **base,
                "outcome": "llm_error",
                "llm": llm_payload(called=True, error=str(exc)),
                "final_shown": final_shown_payload(explanation),
            }
        )
        return explanation
    except LLMResponseInvalid as exc:
        # El LLM respondió pero su JSON nunca se pudo validar tras
        # los reintentos. R3: descartamos y caemos a plantilla.
        explanation = explain_from_template(detection, recommendation)
        log_llm_interaction(
            {
                **base,
                "outcome": "llm_invalid_response",
                "llm": llm_payload(
                    called=True,
                    raw_response=exc.raw,
                    pydantic_passed=False,
                    error=exc.reason,
                ),
                "final_shown": final_shown_payload(explanation),
            }
        )
        return explanation

    # --- Camino 2: el LLM dio JSON válido. Falta cross-validation.
    cross = cross_validate(
        response,
        recommendation,
        snapshot,
        sandbox_pool=sandbox_pool,
        sanitized_sql=sanitized_query.sql if sandbox_pool is not None else None,
    )
    raw_text = response_to_text(response)

    if not cross.passed:
        # R1 + R3: el LLM contradice al motor o referencia cosas
        # inexistentes → gana el motor, plantilla.
        explanation = explain_from_template(detection, recommendation)
        log_llm_interaction(
            {
                **base,
                "outcome": "cross_validation_failed",
                "llm": llm_payload(
                    called=True,
                    raw_response=raw_text,
                    pydantic_passed=True,
                    cross=cross,
                ),
                "final_shown": final_shown_payload(explanation),
            }
        )
        return explanation

    # --- Camino 3: feliz. LLM gana, prosa va al usuario.
    explanation = Explanation(
        explanation=response.explanation,
        suggested_rewrite=response.suggested_rewrite,
        confidence=response.confidence,
        source="llm",
    )
    log_llm_interaction(
        {
            **base,
            "outcome": "llm_ok",
            "llm": llm_payload(
                called=True,
                raw_response=raw_text,
                pydantic_passed=True,
                cross=cross,
            ),
            "final_shown": final_shown_payload(explanation),
        }
    )
    return explanation

"""Orquestador de la capa de explicación — C5 + C6 + C7.

Tie de los tres tickets en una sola función: `explain_recommendation`.
El backend (C9) llamará a esto pasándole los hechos del motor y
obtendrá una `Explanation` lista para devolver al frontend, sin
saber si la prosa vino del LLM o de plantilla.

Flujo:

1. Si `LLM_ENABLED=false` o no hay `ANTHROPIC_API_KEY`: salta el LLM
   y va directo a plantilla (R5).
2. Caso normal: arma prompt (C4), llama al LLM, valida con Pydantic
   (C5, reintentos incluidos), valida cruzado contra snapshot (C6).
3. Si cualquiera de las dos validaciones falla, cae a plantilla (C7)
   sin propagar la excepción al backend.
4. Errores HTTP/red del LLM también caen a plantilla — el producto
   no debe romperse porque Anthropic no respondió (R5).

El campo `Explanation.source` distingue cuál fue. El backend lo expone
al frontend para que, ante `source="template"`, una etiqueta sutil
indique "explicación generada sin IA" (defensa en pitch del Demo Day:
"funciona sin LLM").

Cumple R1+R3+R5: el LLM nunca tiene la palabra final; toda salida
se valida; la pipeline degrada elegante.
"""

from __future__ import annotations

from typing import Any

from ia.cross_validator import cross_validate
from ia.llm import LLMDisabledError, LLMError
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
) -> Explanation:
    """Devuelve la `Explanation` final para una recomendación del motor.

    `sandbox_pool` opcional: si se pasa, C6 corre también la validación
    estructural contra el sandbox (B16). Si es `None` se omite esa parte
    (tests unit, modo offline, perfil "rápido" del backend).

    Garantía: nunca propaga `LLMDisabledError`, `LLMError` ni
    `LLMResponseInvalid`. Esos casos caen silenciosamente a plantilla.
    Cualquier otra excepción (bug interno, snapshot corrupto) sí se
    propaga — el caller decide qué hacer.
    """
    try:
        prompt = build_explanation_prompt(detection, plan, recommendation, sanitized_query)
        response = request_validated_explanation(prompt, max_retries=max_retries)
    except (LLMDisabledError, LLMError, LLMResponseInvalid):
        # R5: el LLM no es prerequisito. Si está apagado, sin key,
        # devolvió status no-2xx, red caída, o el output siguió siendo
        # inválido tras el reintento — caemos a plantilla.
        return explain_from_template(detection, recommendation)

    cross = cross_validate(
        response,
        recommendation,
        snapshot,
        sandbox_pool=sandbox_pool,
        sanitized_sql=sanitized_query.sql if sandbox_pool is not None else None,
    )
    if not cross.passed:
        # R1 + R3: si el LLM contradice al motor o referencia cosas
        # inexistentes, gana el motor. Cae a plantilla.
        # (C8 loggeará `cross.reasons` cuando aterrice — por ahora se
        # descarta silenciosamente; los tests verifican la rama.)
        return explain_from_template(detection, recommendation)

    return Explanation(
        explanation=response.explanation,
        suggested_rewrite=response.suggested_rewrite,
        confidence=response.confidence,
        source="llm",
    )

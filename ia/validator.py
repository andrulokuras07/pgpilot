"""Validación de la respuesta del LLM — C5.

El LLM devuelve texto crudo. Antes de mostrarlo al usuario o pasarlo a
C6 (validación cruzada), aquí se valida que respete el schema acordado
en el system-prompt de C4: `{explanation, suggested_rewrite, confidence}`.

Reglas vivas:

- **R3**: toda salida del LLM se valida antes de mostrarse. Esta es la
  primera capa de validación; C6 hace la segunda (cruzando con schema
  y sandbox).
- **R5**: si la validación falla repetidamente, la pipeline cae a
  plantilla determinística (C7). Acá no se cae solo: se levanta
  `LLMResponseInvalid` para que el orquestador (`explain.py`) decida.

Diseño:

- `LLMResponseSchema`: Pydantic v2 BaseModel con constraints. La
  validación es la garantía: si `model_validate_json` no falla, los
  campos son del tipo correcto y `confidence ∈ [0, 1]`.
- `parse_llm_response(raw)`: wrapper que envuelve `ValidationError`
  y `JSONDecodeError` en una sola excepción para que callers no tengan
  que distinguir.
- `request_validated_explanation(prompt, *, max_retries=1)`: pide al
  LLM, valida, y reintenta hasta `max_retries` veces si el output es
  inválido. Tras agotarlos, levanta `LLMResponseInvalid` con el último
  raw para diagnóstico.

Cumple R8 (type hints), R9 (la parte pura — `parse_llm_response` — no
hace I/O; la orquestación con red es explícita en
`request_validated_explanation`).
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from ia.llm import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, call_llm
from ia.prompt import LLMPrompt


class LLMResponseSchema(BaseModel):
    """Schema esperado de la respuesta del LLM (acordado en el system-prompt de C4).

    `model_config` se queda en default (Pydantic v2): permite extras,
    pero no los expone como atributos. Si el LLM agrega campos nuevos
    los ignoramos en vez de fallar — defensa en profundidad contra
    cambios menores del modelo sin romper la pipeline.
    """

    explanation: str = Field(min_length=1)
    suggested_rewrite: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


class LLMResponseInvalid(Exception):
    """La respuesta del LLM no respeta el schema esperado.

    Atributos extra:
    - `raw`: el texto bruto del LLM (útil para logs C8).
    - `reason`: prosa corta (qué falló).
    """

    def __init__(self, reason: str, raw: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw = raw


def parse_llm_response(raw: str) -> LLMResponseSchema:
    """Valida y parsea el JSON del LLM. **Función pura** — no hace red.

    Lanza `LLMResponseInvalid` si:
    - El string no es JSON parseable.
    - El JSON no respeta el schema (falta `explanation`, `confidence`
      fuera de [0, 1], etc.).

    El caller (`request_validated_explanation` o el orquestador) decide
    si reintenta o cae a plantilla.
    """
    try:
        return LLMResponseSchema.model_validate_json(raw)
    except ValidationError as exc:
        raise LLMResponseInvalid(
            reason=f"respuesta del LLM no respeta el schema: {exc.errors(include_url=False)[:3]}",
            raw=raw,
        ) from exc
    except json.JSONDecodeError as exc:
        # Pydantic v2 `model_validate_json` ya devuelve ValidationError
        # ante JSON inválido, pero atrapamos por si alguien llama con un
        # pre-parser que falle distinto. Defensa en profundidad.
        raise LLMResponseInvalid(
            reason=f"respuesta del LLM no es JSON válido: {exc.msg}",
            raw=raw,
        ) from exc


def request_validated_explanation(
    prompt: LLMPrompt,
    *,
    max_retries: int = 1,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    api_key: str | None = None,
) -> LLMResponseSchema:
    """Pide al LLM y valida con Pydantic, reintentando si el output es inválido.

    `max_retries=1` (default por backlog C5): un reintento adicional
    tras el primer fallo. Si tras `max_retries + 1` intentos el output
    sigue inválido, levanta `LLMResponseInvalid` con el último raw.

    No atrapa `LLMDisabledError`/`LLMError` — el orquestador
    (`explain.py`) los maneja para caer a plantilla (R5).
    """
    last_error: LLMResponseInvalid | None = None
    for _ in range(max_retries + 1):
        raw = call_llm(
            prompt,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
            api_key=api_key,
        )
        try:
            return parse_llm_response(raw)
        except LLMResponseInvalid as exc:
            last_error = exc
    assert last_error is not None  # garantizado por el rango ≥ 1
    raise last_error

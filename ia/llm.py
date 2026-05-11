"""Cliente al LLM — C4.

Encapsula la llamada HTTP a la Messages API de Anthropic. Mantenemos
la dependencia mínima: no agregamos `anthropic` SDK al stack — usamos
`httpx` (ya presente para FastAPI/tests) que es suficiente para POST
JSON con timeout y retry simple.

Reglas vivas en este archivo:

- **R5: el producto debe funcionar sin LLM.** Si la variable de entorno
  `LLM_ENABLED=false` (o `ANTHROPIC_API_KEY` no está seteada), las
  llamadas lanzan `LLMDisabledError` con mensaje claro. El backend
  (C7+) cachea esta excepción y cae a plantillas locales.
- **R4: el LLM nunca recibe SQL crudo.** El builder de prompts ya
  defiende esto vía `SanitizedQuery`. Aquí, defensivo extra: si
  alguien arma un `LLMPrompt` a mano y mete strings sin sanitizar, ya
  es problema suyo — este módulo confía en que el prompt llegó limpio.
- **R3: validación de la salida** es responsabilidad de C5
  (Pydantic). Aquí solo devolvemos el string crudo de la respuesta;
  no parseamos ni validamos schema.

Cumple R8 (type hints), R9 (función con I/O explícito y aislado del
resto).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from ia.prompt import LLMPrompt

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

# Modelo por default. Se puede sobrescribir per-call.
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_SECONDS = 30.0


class LLMError(Exception):
    """Error genérico del cliente LLM (transporte, status no-2xx, etc.)."""


class LLMDisabledError(LLMError):
    """`LLM_ENABLED=false` o falta `ANTHROPIC_API_KEY`. R5: la cadena
    aguas arriba debe atrapar este error y caer a plantillas locales."""


def call_llm(
    prompt: LLMPrompt,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    api_key: str | None = None,
) -> str:
    """Manda el prompt al LLM y devuelve la respuesta TEXTUAL CRUDA.

    No parsea el JSON: eso es C5. Si el LLM devuelve texto que no es
    JSON válido, la falla emerge en la capa de validación, no aquí
    (separación de responsabilidades).

    Lanza:
    - `LLMDisabledError` si `LLM_ENABLED=false` o falta API key
      (R5: el producto sigue funcionando, cae a plantilla en C7).
    - `LLMError` si el endpoint responde non-2xx o la red falla.
    """
    if os.getenv("LLM_ENABLED", "true").strip().lower() == "false":
        raise LLMDisabledError(
            "LLM_ENABLED=false. El producto debe operar con plantillas locales (R5)."
        )

    resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not resolved_key:
        raise LLMDisabledError(
            "Falta ANTHROPIC_API_KEY en el entorno. El producto debe operar con "
            "plantillas locales (R5)."
        )

    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": prompt.system,
        "messages": prompt.messages,
    }
    headers = {
        "x-api-key": resolved_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    try:
        response = httpx.post(
            ANTHROPIC_API_URL,
            headers=headers,
            content=json.dumps(body),
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"Error de red llamando al LLM: {exc!r}") from exc

    if response.status_code >= 400:
        raise LLMError(f"LLM respondió {response.status_code}: {response.text[:500]}")

    payload = response.json()
    return _extract_text(payload)


# Patrón para detectar fences de código markdown (` ```json ... ``` ` o
# ` ``` ... ``` `) que Claude envuelve alrededor del JSON aun cuando el
# system-prompt lo prohíbe. Verificado empíricamente con sonnet-4-6
# (2026-05-11): el modelo respeta el contenido pero tiende a envolver
# en fences. El strip es defensa en profundidad para que el caller
# reciba texto utilizable.
_CODE_FENCE_RE = re.compile(r"\A```(?:json)?\s*\n?(.*?)\n?```\Z", re.DOTALL)


def _extract_text(payload: dict[str, Any]) -> str:
    """Saca el texto del primer bloque `text` de la respuesta de
    Anthropic. Formato esperado:

        {
          "content": [{"type": "text", "text": "..."}],
          ...
        }

    Si vienen varios bloques de texto, los concatena. Si no hay ninguno,
    levanta `LLMError` (respuesta inesperada del servicio).

    Adicionalmente, si el texto completo viene envuelto en una sola
    fence de código markdown (caso típico de Claude devolviendo
    ` ```json {...} ``` ` pese al prompt), la quita. Solo aplica
    cuando la fence envuelve TODO el output — fences embebidas dentro
    del texto se preservan.
    """
    content = payload.get("content")
    if not isinstance(content, list):
        raise LLMError(f"Respuesta sin campo `content` válido: {payload!r}")
    texts = [block.get("text", "") for block in content if block.get("type") == "text"]
    joined = "".join(texts).strip()
    if not joined:
        raise LLMError(f"Respuesta sin bloque `text`: {payload!r}")
    fence_match = _CODE_FENCE_RE.match(joined)
    if fence_match:
        return fence_match.group(1).strip()
    return joined

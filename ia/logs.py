"""Logs estructurados de interacciones con el LLM — C8.

Cada llamada de la pipeline `explain_recommendation` (incluso cuando
el LLM se salta por R5) deja un registro JSON en un archivo de logs.
Sirve para:

- **Debugging**: cuando una recomendación se ve rara, abrir el log
  permite ver qué dijo el LLM crudo, qué validación falló, y qué se
  terminó mostrando al usuario.
- **Q&A del Demo Day**: poder mostrar evidencia real de los caminos
  "LLM apagado", "LLM inválido descartado", "cross-validation
  rechazó la sugerencia". El profesor pregunta y el archivo responde.
- **Cumplimiento de R3**: el sistema descarta output del LLM cuando
  algo no cuadra, pero "no se silencia" — queda en el log.

Reglas vivas:

- **R4**: lo que se loggea ya viene sanitizado (la pipeline solo conoce
  el `SanitizedQuery`, no el SQL original). Defensa en profundidad: si
  el caller mete por error el SQL crudo en `sanitized_sql`, el log lo
  guarda — pero la pipeline no permite ese flujo en producción
  (`build_explanation_prompt` rechaza str con TypeError).
- **R5**: si el log falla por disco lleno o permisos, NO debe romper
  la pipeline. Toda escritura va dentro de un try/except que silencia
  OSError y devuelve None.
- Cumple R8 (type hints), R9 (la única I/O explícita es el append al
  archivo; el resto del módulo es puro).

Configuración por entorno:

- `PGPILOT_LLM_LOG_PATH`: ruta del archivo. Default: `logs/llm_interactions.jsonl`.
- `PGPILOT_LLM_LOG_DISABLED=true`: apaga el logger (útil en CI o cuando
  el operador no quiere persistencia).

Formato: JSON Lines (un objeto JSON por línea, sin coma entre líneas).
Esto permite append sin reparsear el archivo y consumo con `jq` /
`grep` / `pandas.read_json(lines=True)`.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ia.cross_validator import CrossValidationResult
from ia.sanitizer import SanitizedQuery
from ia.templates import Explanation
from ia.validator import LLMResponseSchema
from motor import Detection, Recommendation

DEFAULT_LOG_PATH = "logs/llm_interactions.jsonl"
_RAW_RESPONSE_TRUNCATE = 4000
_EXPLANATION_TRUNCATE = 200
_LOG_LOCK = threading.Lock()

LLMOutcome = Literal[
    "llm_ok",
    "llm_disabled",
    "llm_error",
    "llm_invalid_response",
    "cross_validation_failed",
]


def is_logging_enabled() -> bool:
    """True si el logger debe escribir. Refleja el estado actual del
    entorno (no se cachea — habilitar/deshabilitar en runtime aplica
    a la siguiente llamada)."""
    flag = os.getenv("PGPILOT_LLM_LOG_DISABLED", "").strip().lower()
    return flag != "true"


def resolve_log_path() -> Path:
    """Devuelve la ruta del archivo de logs según el entorno."""
    return Path(os.getenv("PGPILOT_LLM_LOG_PATH", DEFAULT_LOG_PATH))


def build_base_record(
    detection: Detection,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Arma la parte del registro común a cualquier outcome.

    Llamada al inicio de `explain_recommendation` para tener un esqueleto
    que se enriquece según qué rama se tomó.
    """
    matches = list(detection.evidence.get("matches", []))
    return {
        "request_id": request_id or uuid.uuid4().hex,
        "detection": {
            "found": detection.found,
            "confidence": detection.confidence,
            "matches_count": len(matches),
            "first_match_table": matches[0].get("table") if matches else None,
            "first_match_column": matches[0].get("column") if matches else None,
        },
        "recommendation": {
            "kind": recommendation.kind,
            "table": recommendation.table,
            "column": recommendation.column,
            "index_name": recommendation.index_name,
            "selectivity": recommendation.selectivity,
        },
        "sanitized_sql": sanitized_query.sql,
        "placeholders_count": len(sanitized_query.literals),
    }


def llm_payload(
    *,
    called: bool,
    raw_response: str | None = None,
    pydantic_passed: bool | None = None,
    cross: CrossValidationResult | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Construye el sub-objeto `llm` del registro a partir de lo que pasó."""
    payload: dict[str, Any] = {"called": called, "error": error}
    if raw_response is not None:
        payload["raw_response_excerpt"] = raw_response[:_RAW_RESPONSE_TRUNCATE]
        payload["raw_response_length"] = len(raw_response)
    if pydantic_passed is not None:
        payload["pydantic_passed"] = pydantic_passed
    if cross is not None:
        payload["cross_validation_passed"] = cross.passed
        payload["cross_reasons"] = list(cross.reasons)
        payload["sandbox_verdict"] = cross.sandbox_verdict
    return payload


def final_shown_payload(explanation: Explanation) -> dict[str, Any]:
    """Sub-objeto `final_shown` con la prosa que el usuario terminó viendo.

    El excerpt se trunca para mantener los logs manejables; los logs son
    para auditoría, no para reconstruir el output.
    """
    return {
        "source": explanation.source,
        "confidence": explanation.confidence,
        "has_suggested_rewrite": explanation.suggested_rewrite is not None,
        "explanation_excerpt": explanation.explanation[:_EXPLANATION_TRUNCATE],
    }


def response_to_text(response: LLMResponseSchema) -> str:
    """Re-serializa el `LLMResponseSchema` a JSON para loggearlo igual
    que el raw del modo `llm_invalid_response`. Mantiene paridad de
    formato entre todos los outcomes que sí llamaron al LLM."""
    return response.model_dump_json()


def log_llm_interaction(record: dict[str, Any]) -> Path | None:
    """Append una entrada al archivo JSONL de logs. Devuelve la ruta usada
    o `None` si el logger está deshabilitado o si la escritura falló.

    Falla siempre silenciosamente: el log es side-effect, no debe romper
    la pipeline. Escribimos con lock para no intercalar líneas si hay
    múltiples requests concurrentes.

    No mutamos el `record` que el caller pasa; agregamos `timestamp` en
    una copia local.
    """
    if not is_logging_enabled():
        return None

    timestamped = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **record,
    }
    path = resolve_log_path()

    try:
        with _LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(timestamped, ensure_ascii=False, default=str))
                fh.write("\n")
        return path
    except OSError:
        return None


__all__ = [
    "DEFAULT_LOG_PATH",
    "LLMOutcome",
    "build_base_record",
    "final_shown_payload",
    "is_logging_enabled",
    "llm_payload",
    "log_llm_interaction",
    "resolve_log_path",
    "response_to_text",
]

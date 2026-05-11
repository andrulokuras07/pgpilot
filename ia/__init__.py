"""Capa de IA: sanitización, prompts, validación de respuestas del LLM.

API pública del módulo:

    from ia import sanitize, restore, SanitizedQuery
"""

from ia.cross_validator import CrossValidationResult, cross_validate
from ia.explain import explain_recommendation
from ia.llm import LLMDisabledError, LLMError, call_llm
from ia.prompt import LLMPrompt, build_explanation_prompt
from ia.sanitizer import SanitizedQuery, restore, sanitize
from ia.templates import Explanation, explain_from_template
from ia.validator import (
    LLMResponseInvalid,
    LLMResponseSchema,
    parse_llm_response,
    request_validated_explanation,
)

__all__ = [
    # B10/B11 — sanitizador
    "SanitizedQuery",
    "sanitize",
    "restore",
    # C4 — prompt + cliente
    "LLMPrompt",
    "build_explanation_prompt",
    "call_llm",
    "LLMError",
    "LLMDisabledError",
    # C5 — validación Pydantic
    "LLMResponseSchema",
    "LLMResponseInvalid",
    "parse_llm_response",
    "request_validated_explanation",
    # C6 — validación cruzada
    "CrossValidationResult",
    "cross_validate",
    # C7 — plantillas
    "Explanation",
    "explain_from_template",
    # Orquestador C5+C6+C7
    "explain_recommendation",
]

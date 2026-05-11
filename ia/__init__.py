"""Capa de IA: sanitización, prompts, validación de respuestas del LLM.

API pública del módulo:

    from ia import sanitize, restore, SanitizedQuery
"""

from ia.llm import LLMDisabledError, LLMError, call_llm
from ia.prompt import LLMPrompt, build_explanation_prompt
from ia.sanitizer import SanitizedQuery, restore, sanitize

__all__ = [
    "SanitizedQuery",
    "sanitize",
    "restore",
    "LLMPrompt",
    "build_explanation_prompt",
    "call_llm",
    "LLMError",
    "LLMDisabledError",
]

"""Capa de IA: sanitización, prompts, validación de respuestas del LLM.

API pública del módulo:

    from ia import sanitize, restore, SanitizedQuery
"""

from ia.sanitizer import SanitizedQuery, restore, sanitize

__all__ = ["SanitizedQuery", "sanitize", "restore"]

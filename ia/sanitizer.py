"""Sanitizador de literales SQL.

Reemplaza datos sensibles (strings, números, fechas, UUIDs, emails) por
placeholders antes de mandar la query al LLM. Devuelve también un mapa
para reconstruir la query original (solo debug local, nunca al LLM).

Ver ia/CLAUDE.md para detalles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

LiteralType = Literal["string", "email", "uuid", "date", "number"]

# Sufijo del placeholder por tipo, según el backlog B10.
_TYPE_SUFFIX: dict[LiteralType, int] = {
    "string": 1,
    "number": 2,
    "date": 3,
    "uuid": 4,
    "email": 5,
}


@dataclass(frozen=True)
class SanitizedQuery:
    """Resultado de sanitize(): la query con placeholders y el mapa para reconstruir."""

    sql: str
    literals: dict[str, dict[str, str]]


# Orden importa: del más específico al más general. Si los números van
# primero, rompen UUIDs y fechas. Strings van al inicio para tragarse todo
# lo que esté entre comillas como un bloque.
_PATTERNS: list[tuple[LiteralType, re.Pattern[str]]] = [
    # Strings con comillas simples. SQL escapa con '' duplicada, no con \'.
    ("string", re.compile(r"'(?:[^']|'')*'")),
    # Strings con comillas dobles (identificadores en Postgres).
    ("string", re.compile(r'"(?:[^"]|"")*"')),
    # Emails. No es RFC perfecto, pero cubre lo que se escribe en la vida real.
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # UUIDs canónicos (8-4-4-4-12).
    (
        "uuid",
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-" r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
    ),
    # Fechas ISO: 2026-05-09 con hora opcional.
    (
        "date",
        re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\b"),
    ),
    # Números. Al final porque es el más permisivo.
    ("number", re.compile(r"\b\d+(?:\.\d+)?\b")),
]


def sanitize(sql: str) -> SanitizedQuery:
    """Reemplaza literales del SQL por placeholders $LITERAL_<tipo>_<i>."""
    # Juntamos todos los matches con su posición y tipo.
    matches: list[tuple[int, int, LiteralType, str]] = []
    for literal_type, pattern in _PATTERNS:
        for m in pattern.finditer(sql):
            matches.append((m.start(), m.end(), literal_type, m.group()))

    # Orden por posición; si dos empiezan en el mismo lugar, gana el más largo.
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    literals: dict[str, dict[str, str]] = {}
    pieces: list[str] = []
    counters: dict[LiteralType, int] = {t: 0 for t in _TYPE_SUFFIX}
    consumed_until = 0
    last_end = 0

    for start, end, literal_type, original in matches:
        # Si este match cae dentro de uno que ya consumimos, lo saltamos
        # (ej: un número dentro de un string).
        if start < consumed_until:
            continue
        pieces.append(sql[last_end:start])
        counters[literal_type] += 1
        suffix = _TYPE_SUFFIX[literal_type]
        index = counters[literal_type]
        placeholder_key = f"LITERAL_{suffix}_{index}"
        literals[placeholder_key] = {"type": literal_type, "original": original}
        pieces.append(f"${placeholder_key}")
        last_end = end
        consumed_until = end

    pieces.append(sql[last_end:])
    return SanitizedQuery(sql="".join(pieces), literals=literals)


def restore(sanitized: SanitizedQuery) -> str:
    """Reconstruye el SQL original. Solo para debug local, NUNCA al LLM."""
    out = sanitized.sql
    # Reemplazamos los placeholders más largos primero para que $LITERAL_1_1
    # no se confunda con $LITERAL_1_10.
    for placeholder_key in sorted(sanitized.literals.keys(), key=len, reverse=True):
        original = sanitized.literals[placeholder_key]["original"]
        out = out.replace(f"${placeholder_key}", original)
    return out

"""Construcción del prompt al LLM — C4.

Función pura: arma `(system, messages)` a partir de
`{detection, plan, recommendation, sanitized_query}` y los devuelve
listos para `ia.llm.call_llm`. No hace I/O.

**Reglas vivas en este archivo:**
- **R1:** el LLM no decide si hay un anti-pattern; el motor ya lo
  detectó. El prompt se lo dice explícitamente y le pide *explicar*
  y *proponer rewrite alternativo* — nunca contradecir.
- **R4:** el SQL que viaja al LLM es la versión sanitizada
  (`SanitizedQuery.sql`). Los literales originales NUNCA aparecen en
  los mensajes. El builder rechaza si el caller intenta pasar un
  string crudo en vez de un `SanitizedQuery`.
- **R3 + R5 (preparación):** se le pide al LLM JSON estricto con el
  schema de C5 (explanation, suggested_rewrite, confidence). La
  validación con Pydantic vive en C5. Aquí solo se le pide la forma.

Cumple R9 (función pura).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ia.sanitizer import SanitizedQuery
from motor import Detection, ExplainResult, Recommendation


@dataclass(frozen=True)
class LLMPrompt:
    """Prompt listo para mandar al LLM.

    - `system`: instrucciones de rol y guardrails (R1).
    - `messages`: lista de turnos al estilo Anthropic Messages API.
      El user-turn final contiene los hechos del motor (detección +
      recomendación + plan + query sanitizada) en JSON compacto.
    - `expected_output_schema`: descripción del JSON que esperamos.
      No se manda en el prompt directamente — vive aquí para que C5
      (validador Pydantic) y los logs sepan qué validar.
    """

    system: str
    messages: list[dict[str, Any]]
    expected_output_schema: dict[str, Any]


_SYSTEM_PROMPT = """\
Eres un asistente experto en performance de Postgres. Tu rol es
PEDAGÓGICO: el motor determinístico de PgPilot ya detectó el problema y
ya generó una recomendación. Tu trabajo es:

1. EXPLICAR el anti-pattern detectado en lenguaje claro para developers
   de nivel intermedio (qué pasa, por qué es lento, qué hace el planner).
2. PROPONER opcionalmente una reescritura alternativa de la query si
   crees que hay una mejora válida más allá del índice. Si no se te
   ocurre una clara, deja `suggested_rewrite` en null — no inventes.
3. DAR un nivel de confianza (0..1) sobre tu propia explicación.

REGLAS INVIOLABLES:

- NO contradigas al motor. Si el motor dice que hay Seq Scan sobre tabla
  grande, hay Seq Scan sobre tabla grande. No estás aquí para
  re-detectar.
- NO inventes nombres de tablas, columnas o índices. Usa exactamente los
  que aparecen en el contexto del usuario.
- NO uses los literales originales si la query trae placeholders
  `$LITERAL_<i>_<j>`. Esos placeholders son a propósito y deben
  conservarse en la respuesta.
- Output ESTRICTO en JSON con este schema (sin texto fuera del JSON):

  {
    "explanation": "string — explicación del problema en español",
    "suggested_rewrite": "string | null — SQL alternativo con placeholders",
    "confidence": "float entre 0 y 1"
  }

Nada de markdown, nada de prosa antes o después del JSON.
"""


_EXPECTED_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["explanation", "suggested_rewrite", "confidence"],
    "properties": {
        "explanation": {"type": "string"},
        "suggested_rewrite": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


def build_explanation_prompt(
    detection: Detection,
    plan: ExplainResult,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
) -> LLMPrompt:
    """Arma el prompt al LLM para una detección + recomendación del motor.

    `sanitized_query` DEBE ser un `SanitizedQuery` (no un string). Esto
    es defensa en profundidad para R4: el type-check evita que un
    caller mande un SQL crudo por error. Si los literales originales
    aparecieran aquí, viajarían al LLM y violarían la regla de privacidad.
    """
    if not isinstance(sanitized_query, SanitizedQuery):
        raise TypeError(
            "sanitized_query debe ser un ia.SanitizedQuery, no str. "
            "El LLM jamás recibe SQL crudo (R4)."
        )

    user_payload = {
        "detection": _detection_payload(detection),
        "recommendation": _recommendation_payload(recommendation),
        "plan_summary": _plan_summary(plan),
        "sanitized_query": sanitized_query.sql,
        "literal_placeholders": _placeholder_index(sanitized_query),
    }
    user_message = (
        "Aquí están los hechos del motor para esta query. Devolveme el JSON con la explicación, "
        "rewrite opcional y confianza.\n\n"
        f"```json\n{_json_compact(user_payload)}\n```"
    )

    return LLMPrompt(
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        expected_output_schema=_EXPECTED_OUTPUT_SCHEMA,
    )


# --- helpers de payload --------------------------------------------


def _detection_payload(detection: Detection) -> dict[str, Any]:
    """Reduce la Detection a un dict serializable. `matches` viaja
    completo: el LLM se beneficia de saber cuántas ocurrencias y sus
    detalles para explicar bien."""
    return {
        "found": detection.found,
        "confidence": detection.confidence,
        "matches": list(detection.evidence.get("matches", [])),
    }


def _recommendation_payload(recommendation: Recommendation) -> dict[str, Any]:
    """Reduce la Recommendation a un dict serializable. Incluye TODOS los
    campos relevantes porque el LLM tiene que repetirlos en su
    explicación (R14 evita que invente nombres)."""
    return {
        "kind": recommendation.kind,
        "table": recommendation.table,
        "column": recommendation.column,
        "index_method": recommendation.index_method,
        "index_name": recommendation.index_name,
        "create_index_sql": recommendation.create_index_sql,
        "selectivity": recommendation.selectivity,
        "expected_impact": recommendation.expected_impact,
        "justification": recommendation.justification,
    }


def _plan_summary(plan: ExplainResult) -> dict[str, Any]:
    """Resumen del plan: solo los nodos relevantes (Seq Scan, Index Scan,
    Joins) con sus campos clave. Evitamos mandar el árbol crudo: ocupa
    contexto y la mayoría de campos no aportan a la explicación.

    Caminamos el árbol nosotros (sin `find_nodes`) para incluir
    cualquier tipo de scan/join sin lista cerrada — el LLM se beneficia
    de ver toda la estructura macro.
    """
    nodes: list[dict[str, Any]] = []

    def _walk(node: Any, depth: int = 0) -> None:
        nodes.append(
            {
                "depth": depth,
                "node_type": node.node_type,
                "relation": node.relation_name,
                "total_cost": node.total_cost,
                "plan_rows": node.plan_rows,
                "filter": node.filter,
                "index_cond": node.index_cond,
                "index_name": node.index_name,
                "join_type": node.join_type,
            }
        )
        for child in node.children:
            _walk(child, depth + 1)

    _walk(plan.root)
    return {
        "execution_time_ms": plan.execution_time_ms,
        "planning_time_ms": plan.planning_time_ms,
        "nodes": nodes,
    }


def _placeholder_index(sanitized_query: SanitizedQuery) -> dict[str, str]:
    """Mapa `placeholder → tipo` (no el valor original) para que el LLM
    sepa que `$LITERAL_2_1` es un número, etc. R4: el campo `original`
    NUNCA se incluye."""
    return {f"${key}": meta["type"] for key, meta in sanitized_query.literals.items()}


def _json_compact(payload: dict[str, Any]) -> str:
    """JSON estable y compacto para el user-turn. Usamos `json.dumps`
    nativo con `ensure_ascii=False` para preservar acentos y
    `sort_keys=True` para que el prompt sea reproducible (útil para
    cache de Anthropic y para tests con golden snapshot futuros)."""
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

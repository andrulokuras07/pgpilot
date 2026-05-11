"""Plantillas de explicación sin LLM — C7.

Cuando el LLM está apagado (`LLM_ENABLED=false` o sin API key) o
cuando la respuesta del LLM se descarta (mal formada en C5 o inválida
en C6), el sistema sigue funcionando con prosa generada por
plantillas a partir de los hechos del motor.

Reglas vivas:

- **R5**: el producto debe funcionar sin LLM. Esta es la rama "LLM
  apagado". Su criterio de éxito es: devolver una explicación legible
  con datos reales de la detección, sin crashear, sin llamar a la API.
- **R1**: el motor decide. Las plantillas re-empaquetan lo que el
  motor ya razonó (campos de `Detection` y `Recommendation`); nunca
  agregan información nueva.
- **R14**: nada hardcodeado de AppDB. Toda referencia a tablas y
  columnas sale de los argumentos.

Diseño:

- `Explanation` es el tipo común de salida tanto para el camino LLM
  como para el de plantilla. El campo `source` permite al frontend
  marcar visualmente cuál de los dos generó la prosa (Q&A: "¿sigue
  funcionando sin IA?" → mostrar tarjetas con `source="template"`).
- Plantillas distintas según `recommendation.kind`: la prosa de
  "crear índice" no aplica al caso "ya existe, refrescá stats".
- La explicación se construye con f-strings simples sobre los campos
  de `Recommendation` (que el motor ya armó en C2). Ni un literal de
  tabla/columna en el código.

Cumple R8 (type hints), R9 (función pura — no hace I/O).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from motor import Detection, Recommendation


@dataclass(frozen=True)
class Explanation:
    """Resultado final de la capa de explicación, listo para el frontend.

    Mismo shape para los dos caminos (LLM y plantilla) para que el
    backend (C9) no tenga que ramificar el tipo. `source` distingue
    cuál fue.
    """

    explanation: str
    suggested_rewrite: str | None
    confidence: float
    source: Literal["llm", "template"]


def explain_from_template(
    detection: Detection,
    recommendation: Recommendation,
) -> Explanation:
    """Genera una explicación sin LLM a partir de los hechos del motor.

    `detection` se usa para confirmar que hay algo que explicar; si
    `detection.found is False`, igual devolvemos una `Explanation`
    pero el caller normalmente no debería llegar acá (el motor no
    emite recomendación sin detección). No levantamos: defensa en
    profundidad.
    """
    if recommendation.kind == "create_index":
        body = _create_index_template(recommendation)
    else:
        body = _analyze_template(recommendation)

    return Explanation(
        explanation=body,
        suggested_rewrite=None,
        confidence=_confidence_from_recommendation(recommendation),
        source="template",
    )


def _create_index_template(rec: Recommendation) -> str:
    """Plantilla para el caso `kind="create_index"`.

    Estructura: contexto → causa → recomendación → impacto → SQL.
    """
    lines = [
        f"PgPilot detectó un Seq Scan sobre la tabla {rec.table} con un filtro "
        f"de igualdad sobre la columna {rec.column!r}, y no existe un índice "
        f"btree utilizable para esa columna.",
        "",
        "Por qué importa: sin un índice, Postgres lee todas las filas de la "
        "tabla y descarta las que no cumplen el filtro. En tablas grandes "
        "eso es costoso y crece linealmente con el tamaño.",
        "",
        f"Recomendación del motor: {rec.justification}",
        "",
        f"Impacto esperado: {rec.expected_impact}",
        "",
        "SQL sugerido:",
        f"    {rec.create_index_sql}",
    ]
    return "\n".join(lines)


def _analyze_template(rec: Recommendation) -> str:
    """Plantilla para el caso `kind="analyze"` (el índice existe y el
    planner lo ignora — típicamente stats desactualizadas).
    """
    lines = [
        f"PgPilot detectó un Seq Scan sobre la tabla {rec.table} con filtro "
        f"sobre {rec.column!r}, pero ya existe el índice {rec.index_name!r} "
        "sobre esa columna. El planner lo está ignorando.",
        "",
        "Por qué importa: cuando Postgres tiene un índice utilizable y aun "
        "así elige Seq Scan, la causa más probable es que las estadísticas "
        "de la tabla estén desactualizadas y el planner no estime bien la "
        "selectividad del filtro.",
        "",
        f"Recomendación del motor: {rec.justification}",
        "",
        f"Impacto esperado: {rec.expected_impact}",
        "",
        "SQL sugerido:",
        f"    {rec.create_index_sql}",
    ]
    return "\n".join(lines)


def _confidence_from_recommendation(rec: Recommendation) -> float:
    """Confianza de la plantilla.

    Sin selectividad estimada (tabla sin `ANALYZE`), bajamos un poco:
    la recomendación sigue siendo válida estructuralmente pero
    perdemos la pieza cuantitativa. Con selectividad: 0.8 fijo —
    determinístico, sin pretender más de lo que el motor puede afirmar.
    """
    if rec.selectivity is None:
        return 0.6
    return 0.8

"""Tipo de retorno común a todos los detectores del motor.

Cada detector es una función pura (R9) que devuelve una `Detection`.
El campo `evidence` es un dict abierto porque cada detector reporta
hechos distintos (tabla, columna, filas, nombre del índice candidato,
etc.); el recomendador (C2) y la capa de prosa (C4) leen de ahí.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Detection:
    """Resultado de correr un detector sobre un plan + schema.

    - `found`: True si el anti-pattern se detectó al menos una vez.
    - `confidence`: float en [0, 1]. Para C1 usamos 1.0 cuando todas
      las condiciones estructurales se cumplen (es una detección
      determinística, no probabilística); detectores futuros con
      heurísticas más blandas usarán valores intermedios.
    - `evidence`: dict con los hechos crudos que sustentan la
      detección. Convención: una entrada por ocurrencia bajo la
      clave `matches: list[dict]`. Esto permite que una misma query
      reporte N seq scans problemáticos.
    """

    found: bool
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)

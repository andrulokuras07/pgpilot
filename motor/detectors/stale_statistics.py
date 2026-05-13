"""Detector D2 — Mismatch entre `rows estimated` y `rows actual` en scans.

Detecta nodos de scan donde la estimación del planner (`plan_rows`)
difiere de la realidad medida con EXPLAIN ANALYZE (`actual_rows`) por
un factor ≥10x en cualquier dirección (sobre o subestimación). Esa
brecha es la firma clásica de **estadísticas obsoletas en la tabla**:
el planner razona con `pg_class.reltuples` y `pg_statistic` que ya no
reflejan la distribución real de datos, y termina eligiendo planes
malos (joins en orden incorrecto, Seq Scan en lugar de Index Scan,
sorts dimensionados mal, etc.).

Recomendación: ejecutar `ANALYZE <tabla>;` (o `VACUUM ANALYZE` si la
tabla tiene mucho churn). El recomendador final puede sugerir además
revisar `autovacuum_analyze_scale_factor` para esa tabla.

Frontera con detectores hermanos:

- **D18 (`cardinality_misestimate`)**: opera sobre nodos *join* mal
  estimados causados por correlación entre columnas (filtro AND
  multi-col en un scan descendiente). Recomienda `CREATE STATISTICS`
  multi-columna, no `ANALYZE`. D2 y D18 pueden disparar a la vez en
  el mismo plan (uno en el scan, otro en el join); ambos son hechos
  correctos, y la prosa del LLM elige cuál explicar.
- **C1 / D16**: anti-patterns de índice, no de stats. Pueden coexistir
  con D2 cuando además de no usar índice, el planner estimó mal.

Cumple R1 (motor decide), R2 (estructura del plan, no SQL crudo),
R9 (función pura), R14 (sin literales hardcoded de AppDB).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from motor.detection import Detection
from motor.parser import ExplainResult, PlanNode

# Ratio mínimo plan_rows/actual_rows (en cualquier dirección) para
# considerar las estadísticas "obsoletas". 10x es el umbral del
# backlog D2 — Postgres siempre tiene algo de error, pero un orden
# de magnitud es la frontera clásica que la literatura (Tom Lane,
# Hironobu Suzuki, depesz) usa para flaggear stats podridas.
STALE_STATS_RATIO = 10.0

# Tipos de scan que cuentan como "lectura primaria de tabla". El
# error de cardinalidad en un join (D18) o en un Sort/Aggregate
# normalmente se hereda del scan de abajo — no de stats de tabla
# propias del join. Por eso D2 dispara únicamente en los scans:
# así la recomendación `ANALYZE <tabla>` siempre apunta a una tabla
# real, no a un nodo derivado.
_SCAN_TYPES = frozenset(
    {
        "Seq Scan",
        "Index Scan",
        "Index Only Scan",
        "Bitmap Heap Scan",
    }
)


def detect_stale_statistics(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra scans con plan_rows/actual_rows muy desviado.

    Args:
        plan: árbol del plan parseado por `motor.parse_explain`. Debe
            venir de un EXPLAIN ejecutado con `ANALYZE`; sin `actual_*`
            el detector no tiene nada que comparar y devuelve
            `found=False`.
        snapshot: SchemaSnapshot del conector. D2 no lo consulta hoy
            (los hechos viven en el plan); se acepta por contrato
            uniforme con el resto de detectores y para facilitar
            extensiones futuras (ej. mostrar `last_analyze` cuando
            esté disponible en `snapshot["stats"]`).

    Returns:
        `Detection` con un match por scan afectado. Cada match incluye
        tabla, columna no aplica aquí, `plan_rows`, `actual_rows`,
        ratio calculado, dirección del error y el SQL sugerido para
        refrescar estadísticas.
    """
    _ = snapshot  # reservado para uso futuro; ver docstring
    matches: list[dict[str, Any]] = []
    root = plan.root if isinstance(plan, ExplainResult) else plan

    for node, under_limit in _walk_scans(root):
        if under_limit:
            # Bajo un `Limit`, Postgres trunca el scan antes de exhaustar
            # las filas que el planner había estimado: `actual_rows` ya
            # no representa "cuántas filas matcheaban el filtro" sino
            # "cuántas pidió el LIMIT". Comparar plan_rows contra ese
            # valor truncado produce un overestimate falso. Saltamos.
            continue
        ratio_info = _stale_ratio(node)
        if ratio_info is None:
            continue
        if node.relation_name is None:
            # Scan sin tabla identificable (ej. Seq Scan sobre VALUES,
            # function scan envuelto). Sin tabla no podemos recomendar
            # `ANALYZE`. Lo dejamos pasar — robustez sobre cobertura.
            continue

        ratio, direction = ratio_info
        # Para el `suggested_sql` usamos solo el nombre relativo; el
        # snapshot no garantiza que `relation_name` venga calificada
        # con schema. Es ANALYZE: si el usuario está conectado al
        # schema correcto, basta. La prosa del LLM puede enriquecer.
        suggested_sql = f"ANALYZE {node.relation_name};"

        matches.append(
            {
                "table": node.relation_name,
                "node_type": node.node_type,
                "plan_rows": node.plan_rows,
                "actual_rows": node.actual_rows,
                "ratio": round(ratio, 2),
                "direction": direction,
                "suggested_sql": suggested_sql,
            }
        )

    return Detection(
        found=bool(matches),
        confidence=0.85 if matches else 0.0,
        evidence={"matches": matches},
    )


def _walk_scans(
    node: PlanNode,
    under_limit: bool = False,
) -> Iterator[tuple[PlanNode, bool]]:
    """Recorre el árbol DFS y emite cada scan con flag `under_limit`.

    `under_limit` es True cuando algún ancestro del scan es `Limit`.
    Necesario porque `PlanNode` es frozen y no guarda punteros al padre,
    así que tenemos que propagar el contexto manualmente en el recorrido.
    """
    next_under_limit = under_limit or node.node_type == "Limit"
    if node.node_type in _SCAN_TYPES:
        yield (node, under_limit)
    for child in node.children:
        yield from _walk_scans(child, next_under_limit)


def _stale_ratio(node: PlanNode) -> tuple[float, str] | None:
    """¿La razón entre estimación y realidad supera STALE_STATS_RATIO?

    Devuelve `(ratio, direction)` cuando el nodo califica como "stats
    obsoletas", o `None` cuando no aplica:

    - `actual_rows is None`: EXPLAIN sin ANALYZE → no podemos comparar.
    - `plan_rows is None`: el parser no extrajo la estimación → idem.
    - `actual_rows == 0` y `plan_rows > UMBRAL`: overestimación total
      (la query no devolvió filas pero el planner esperaba muchas).
      Cuenta como obsoleto.
    - `plan_rows == 0` y `actual_rows > 0`: el planner no estimó nada y
      sí hubo filas — también obsoleto, pero por diseño Postgres rara
      vez emite `plan_rows = 0`; usamos `>= 1` como sanity.
    - Caso general: ratio = `max(plan/actual, actual/plan)`. ≥ UMBRAL
      cuenta. `direction` reporta cuál lado fue más grande para que la
      prosa del LLM la use.

    Mantenemos esto separado de `detect_stale_statistics` por
    legibilidad y para poder testearlo en aislamiento si hace falta.
    """
    plan_rows = node.plan_rows
    actual_rows = node.actual_rows

    if actual_rows is None or plan_rows is None:
        return None

    # Postgres divide actual_rows por loops en EXPLAIN, así que el
    # campo ya viene normalizado por iteración. No re-multiplicamos.

    if actual_rows == 0:
        if plan_rows > STALE_STATS_RATIO:
            # Overestimación absoluta — no hay división posible.
            # Reportamos plan_rows como "ratio efectivo" para mantener
            # comparable con el resto de los matches.
            return float(plan_rows), "overestimated"
        return None

    if plan_rows == 0:
        # Subestimación absoluta — Postgres pensó "0 filas, cero costo"
        # y terminó leyendo muchas. Es el caso más peligroso.
        if actual_rows > STALE_STATS_RATIO:
            return float(actual_rows), "underestimated"
        return None

    over = plan_rows / actual_rows
    under = actual_rows / plan_rows
    if over >= STALE_STATS_RATIO:
        return over, "overestimated"
    if under >= STALE_STATS_RATIO:
        return under, "underestimated"
    return None

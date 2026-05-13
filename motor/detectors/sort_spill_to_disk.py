"""Detector D3 — Sort en disco.
 
Detecta nodos `Sort` que Postgres tuvo que ejecutar en disco porque
el conjunto a ordenar no cabió en `work_mem`. En el plan se manifiesta
con `Sort Space Type: Disk` (campo estructurado) y `Sort Method:
external merge` o `external sort` (variantes textuales según versión
de Postgres).
 
Recomendaciones (el detector reporta los hechos; el recomendador
emite el SQL):
 
1. **Aumentar `work_mem`** para esta sesión/rol/query — barato, pero
   sube uso de RAM y debe dimensionarse con cuidado (work_mem es por
   nodo de sort, no por sesión).
2. **Agregar un índice btree sobre `sort_key`** — permite que el
   planner sirva el orden directamente del índice (Index Scan con
   `scan_direction`) y elimina el Sort por completo.
3. **Reducir el conjunto antes del Sort** (mover predicados al
   WHERE, ajustar `LIMIT`, eliminar columnas innecesarias) — depende
   de la query y queda para la prosa del LLM.
 
Frontera con detectores hermanos:
 
- **No interfiere con scans (C1/D16) ni con joins (D8/D18).** Sort es
  un nodo distinto en el árbol; estos detectores son ortogonales y
  pueden disparar a la vez si el plan tiene varios anti-patterns.
 
Cumple R1 (motor decide), R2 (estructura del plan: `sort_space_type`
y `sort_method` son atributos tipados del `PlanNode`), R9 (función
pura), R14 (sin literales hardcoded de AppDB).
"""
 
from __future__ import annotations
 
from typing import Any
 
from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode
 
# Valor que Postgres emite en `Sort Space Type` cuando el sort
# desbordó a disco. Las variantes que hemos visto en planes reales
# son `"Memory"` (cabe en work_mem) y `"Disk"` (no cabe). Si en el
# futuro Postgres introduce otras (`"Tape"`, `"External"`, etc.)
# basta sumarlas a este tuple.
_DISK_SPACE_TYPES = ("Disk",)
 
# Métodos de sort que aparecen explícitamente cuando el sort
# desborda. No los usamos como condición principal — el authoritative
# es `sort_space_type` — pero los reportamos en el match para que el
# LLM pueda mencionarlos en la explicación, y nos sirven como
# fallback defensivo si una versión rara de Postgres omite
# `Sort Space Type` y solo emite `Sort Method`.
_DISK_SORT_METHODS_LOWER = (
    "external merge",
    "external sort",
)
 
 
def detect_sort_spill_to_disk(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Encuentra nodos Sort que se ejecutaron en disco.
 
    Args:
        plan: árbol del plan parseado por `motor.parse_explain`.
            Requiere haber sido ejecutado con `EXPLAIN ANALYZE` (sin
            ANALYZE no hay `Sort Method` ni `Sort Space Type`).
        snapshot: SchemaSnapshot del conector. No se consulta hoy:
            la decisión es puramente estructural sobre el plan. Se
            acepta por contrato uniforme con el resto de detectores.
 
    Returns:
        `Detection` con un match por nodo Sort que desbordó. Cada
        match incluye `sort_key` (tupla de columnas/expresiones del
        ORDER BY), `sort_method`, `sort_space_type`, `sort_space_used`
        en KB, `plan_rows`, `actual_rows` y dos posibles SQL: uno
        para subir work_mem en sesión y otro para crear el índice
        sobre la primera columna del sort_key (mejor caso).
    """
    _ = snapshot  # reservado; ver docstring
    matches: list[dict[str, Any]] = []
 
    for node in find_nodes(plan, "Sort"):
        if not _spilled_to_disk(node):
            continue
 
        sort_key_list = list(node.sort_key) if node.sort_key else []
        matches.append(
            {
                "node_type": node.node_type,
                "sort_key": sort_key_list,
                "sort_method": node.sort_method,
                "sort_space_type": node.sort_space_type,
                "sort_space_used_kb": node.sort_space_used,
                "plan_rows": node.plan_rows,
                "actual_rows": node.actual_rows,
                "suggested_set_work_mem_sql": _suggest_work_mem_sql(node),
                "suggested_create_index_sql": _suggest_index_sql(sort_key_list),
            }
        )
 
    return Detection(
        found=bool(matches),
        confidence=0.95 if matches else 0.0,
        evidence={"matches": matches},
    )
 
 
def _spilled_to_disk(node: PlanNode) -> bool:
    """¿Este Sort terminó en disco?
 
    La condición primaria es `sort_space_type == "Disk"` (campo
    autoritativo emitido por Postgres). Caemos al método como
    fallback defensivo: si por alguna razón el campo no viene pero
    el `sort_method` menciona `external merge` o `external sort`,
    también cuenta. Cubrir las dos vías evita falsos negativos en
    planes de versiones de Postgres ligeramente distintas.
    """
    if node.sort_space_type in _DISK_SPACE_TYPES:
        return True
    if node.sort_method:
        method_lower = node.sort_method.lower()
        return any(m in method_lower for m in _DISK_SORT_METHODS_LOWER)
    return False
 
 
def _suggest_work_mem_sql(node: PlanNode) -> str:
    """Sugiere SET de `work_mem` con holgura ~2x sobre lo que usó.
 
    Si Postgres reporta `sort_space_used` (KB usados en disco), el
    valor ideal de work_mem es algo mayor — duplicamos y redondeamos
    al MB siguiente. Si no hay dato, devolvemos una sugerencia
    genérica de 64MB (el recomendador o el LLM puede ajustar). No
    emitimos ALTER ROLE ni cambios globales — solo SET de sesión,
    que es reversible.
    """
    if node.sort_space_used and node.sort_space_used > 0:
        # Duplicamos los KB usados y subimos al múltiplo de 1024 KB
        # más cercano para expresarlo en MB redondos.
        kb_needed = node.sort_space_used * 2
        mb_needed = max(1, (kb_needed + 1023) // 1024)
        return f"SET work_mem = '{mb_needed}MB';"
    return "SET work_mem = '64MB';"
 
 
def _suggest_index_sql(sort_key: list[str]) -> str | None:
    """Si podemos identificar tabla.columna en la primera entrada del
    sort_key, sugiere un CREATE INDEX. Si no, devuelve None.
 
    El campo `Sort Key` de Postgres viene como
    `["public.posts.created_at DESC", "public.posts.id"]` o
    `["created_at"]` o incluso `["lower(name)"]` según contexto. No
    intentamos parsear todos esos casos — solo el más simple
    (`"schema.tabla.columna"` o `"tabla.columna"`); cualquier otra
    forma cae al recomendador, que tiene más contexto. R14: nada
    hardcoded; si no es parseable, no inventamos.
    """
    if not sort_key:
        return None
    first = sort_key[0].strip()
    # Quitar dirección si viene pegada al nombre (`col DESC`, `col ASC`)
    for suffix in (" DESC", " ASC", " desc", " asc"):
        if first.endswith(suffix):
            first = first[: -len(suffix)].strip()
            break
    # Si tiene paréntesis es una expresión (función, cast, etc.) —
    # punteamos: el índice funcional es un caso aparte y lo decide
    # el recomendador con más info.
    if "(" in first or ")" in first:
        return None
    parts = first.split(".")
    if len(parts) == 3:
        schema, table, column = parts
        return (
            f"CREATE INDEX idx_{table}_{column} "
            f"ON {schema}.{table} ({column});"
        )
    if len(parts) == 2:
        table, column = parts
        return f"CREATE INDEX idx_{table}_{column} ON {table} ({column});"
    return None

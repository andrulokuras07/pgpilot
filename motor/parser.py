"""Parser de EXPLAIN (FORMAT JSON) a un árbol estructurado.

B7 + B8 del backlog. Convierte el output de
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` en un árbol de `PlanNode`s
propio del proyecto. El parser NO se queda con el JSON crudo: extrae
explícitamente cada campo relevante para que los detectores de
`/motor` puedan razonar sobre estructura tipada (R2: detección sobre
estructura, no sobre strings).

El árbol resultante es la entrada canónica de:
- los detectores de anti-patterns (find_nodes + análisis por tipo)
- el comparativo before/after del sandbox
- la generación de prosa pedagógica del LLM (que recibe la estructura
  sanitizada, no el SQL crudo)

Diseño:

- `PlanNode` es un `dataclass(frozen=True)` con campos comunes
  (costos, filas est/reales, tiempos) y campos específicos por tipo
  de nodo, todos opcionales para que cualquier nodo se construya con
  los campos que el JSON realmente trajo.
- Los hijos viven en `children: tuple[PlanNode, ...]`. Tupla en lugar
  de lista para preservar inmutabilidad y permitir `__hash__`.
- `ExplainResult` envuelve el árbol con metadata top-level
  (`planning_time_ms`, `execution_time_ms`).
- `parse_explain` acepta el output como `str` (JSON crudo), `list`
  (JSON ya decodificado de Postgres) o `dict` (entry suelto). Esto
  permite tests con fixtures en archivo y producción con
  `cur.fetchone()[0]` sin código de glue extra.

No depende del conector ni del LLM. Función pura: mismos bytes de
entrada → mismo árbol de salida.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class PlanNode:
    """Un nodo del plan de ejecución parseado.

    Solo `node_type` y los costos básicos están garantizados. Todo lo
    demás es opcional porque depende del tipo de nodo y de si el
    EXPLAIN se corrió con `ANALYZE`.

    Convención: nombres de atributos en `snake_case`; el JSON original
    usa `Title Case` con espacios. El mapeo se hace en `_parse_node`.
    """

    # --- comunes a todo nodo ---------------------------------------
    node_type: str
    startup_cost: float
    total_cost: float
    plan_rows: int
    plan_width: int

    # --- presentes solo si EXPLAIN ANALYZE -------------------------
    actual_startup_time: float | None = None
    actual_total_time: float | None = None
    actual_rows: int | None = None
    actual_loops: int | None = None

    # --- identidad de la relación escaneada ------------------------
    relation_name: str | None = None  # tabla escaneada (Seq/Index/Bitmap Heap)
    alias: str | None = None
    parent_relationship: str | None = None  # "Outer", "Inner", "Member"

    # --- scan-specific ---------------------------------------------
    index_name: str | None = None
    index_cond: str | None = None
    recheck_cond: str | None = None
    filter: str | None = None
    rows_removed_by_filter: int | None = None
    rows_removed_by_index_recheck: int | None = None
    scan_direction: str | None = None
    heap_fetches: int | None = None

    # --- join-specific ---------------------------------------------
    join_type: str | None = None  # "Inner", "Left", "Full", "Anti", "Semi"
    inner_unique: bool | None = None
    hash_cond: str | None = None
    merge_cond: str | None = None

    # --- sort-specific ---------------------------------------------
    sort_key: tuple[str, ...] | None = None
    sort_method: str | None = None
    sort_space_type: str | None = None
    sort_space_used: int | None = None

    # --- aggregate-specific ----------------------------------------
    strategy: str | None = None  # "Plain", "Hashed", "Sorted", "Mixed"
    partial_mode: str | None = None  # "Simple", "Partial", "Finalize"
    group_key: tuple[str, ...] | None = None

    # --- CTE / Subquery / Recursive --------------------------------
    cte_name: str | None = None
    subplan_name: str | None = None

    # --- hash-specific ---------------------------------------------
    hash_buckets: int | None = None
    hash_batches: int | None = None
    peak_memory_kb: int | None = None

    # --- parallelism -----------------------------------------------
    parallel_aware: bool = False
    workers_planned: int | None = None
    workers_launched: int | None = None

    # --- jerarquía -------------------------------------------------
    children: tuple[PlanNode, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExplainResult:
    """Resultado top-level de parsear un EXPLAIN.

    Wrappea la raíz del plan más metadata global de la ejecución.
    `planning_time_ms` y `execution_time_ms` pueden ser `None` cuando
    el EXPLAIN se corrió sin `ANALYZE`.
    """

    root: PlanNode
    planning_time_ms: float | None = None
    execution_time_ms: float | None = None


def parse_explain(raw: str | list[Any] | Mapping[str, Any]) -> ExplainResult:
    """Convierte el output de `EXPLAIN (FORMAT JSON)` en `ExplainResult`.

    Acepta tres formas de entrada para evitar boilerplate en el caller:

    - `str`: el JSON crudo tal como lo emite `psql -tAq` o
      `cur.fetchone()[0]` cuando viene como string.
    - `list`: lo que devuelve psycopg al hacer
      `cur.execute(...).fetchone()[0]` (Postgres siempre envuelve el
      EXPLAIN en una lista de un elemento).
    - `dict` / `Mapping`: una entrada ya extraída del wrapper.

    Lanza `ValueError` si la estructura no contiene un nodo raíz
    `Plan`. No oculta errores de parseo: si el JSON está corrupto,
    propaga `json.JSONDecodeError` para que el caller lo loguee.
    """
    if isinstance(raw, str):
        decoded: Any = json.loads(raw)
    else:
        decoded = raw

    if isinstance(decoded, list):
        if not decoded:
            raise ValueError("EXPLAIN output vacío (lista sin elementos)")
        decoded = decoded[0]

    if not isinstance(decoded, Mapping):
        raise ValueError(f"EXPLAIN entry no es un objeto JSON; recibido: {type(decoded).__name__}")
    if "Plan" not in decoded:
        raise ValueError("EXPLAIN entry no contiene la llave 'Plan'")

    root = _parse_node(decoded["Plan"])
    return ExplainResult(
        root=root,
        planning_time_ms=_as_float(decoded.get("Planning Time")),
        execution_time_ms=_as_float(decoded.get("Execution Time")),
    )


def _parse_node(node: Mapping[str, Any]) -> PlanNode:
    """Construye un `PlanNode` recursivamente a partir de un dict JSON.

    Función interna. No valida que `node` sea válido más allá de
    requerir `Node Type`; los campos faltantes quedan como `None`.
    """
    node_type = node.get("Node Type")
    if not isinstance(node_type, str):
        raise ValueError(f"Nodo sin 'Node Type' válido: {node_type!r}")

    children = tuple(_parse_node(c) for c in node.get("Plans", []))

    return PlanNode(
        node_type=node_type,
        startup_cost=_as_float(node.get("Startup Cost"), default=0.0),
        total_cost=_as_float(node.get("Total Cost"), default=0.0),
        plan_rows=_as_int(node.get("Plan Rows"), default=0),
        plan_width=_as_int(node.get("Plan Width"), default=0),
        actual_startup_time=_as_float(node.get("Actual Startup Time")),
        actual_total_time=_as_float(node.get("Actual Total Time")),
        actual_rows=_as_int(node.get("Actual Rows")),
        actual_loops=_as_int(node.get("Actual Loops")),
        relation_name=_as_str(node.get("Relation Name")),
        alias=_as_str(node.get("Alias")),
        parent_relationship=_as_str(node.get("Parent Relationship")),
        index_name=_as_str(node.get("Index Name")),
        index_cond=_as_str(node.get("Index Cond")),
        recheck_cond=_as_str(node.get("Recheck Cond")),
        filter=_as_str(node.get("Filter")),
        rows_removed_by_filter=_as_int(node.get("Rows Removed by Filter")),
        rows_removed_by_index_recheck=_as_int(node.get("Rows Removed by Index Recheck")),
        scan_direction=_as_str(node.get("Scan Direction")),
        heap_fetches=_as_int(node.get("Heap Fetches")),
        join_type=_as_str(node.get("Join Type")),
        inner_unique=_as_bool(node.get("Inner Unique")),
        hash_cond=_as_str(node.get("Hash Cond")),
        merge_cond=_as_str(node.get("Merge Cond")),
        sort_key=_as_str_tuple(node.get("Sort Key")),
        sort_method=_as_str(node.get("Sort Method")),
        sort_space_type=_as_str(node.get("Sort Space Type")),
        sort_space_used=_as_int(node.get("Sort Space Used")),
        strategy=_as_str(node.get("Strategy")),
        partial_mode=_as_str(node.get("Partial Mode")),
        group_key=_as_str_tuple(node.get("Group Key")),
        cte_name=_as_str(node.get("CTE Name")),
        subplan_name=_as_str(node.get("Subplan Name")),
        hash_buckets=_as_int(node.get("Hash Buckets")),
        hash_batches=_as_int(node.get("Hash Batches")),
        peak_memory_kb=_as_int(node.get("Peak Memory Usage")),
        parallel_aware=bool(node.get("Parallel Aware", False)),
        workers_planned=_as_int(node.get("Workers Planned")),
        workers_launched=_as_int(node.get("Workers Launched")),
        children=children,
    )


# --- helpers de coerción -------------------------------------------
# Existen para tolerar que Postgres a veces emita `null`, ints donde
# esperamos floats, etc., sin romper el parser. Mantienen el contrato
# "campo opcional → None cuando no está".


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"Esperaba número, recibí {type(value).__name__}: {value!r}")


def _as_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        # bool es subclase de int en Python; rechazamos explícito.
        raise TypeError(f"Esperaba int, recibí bool: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError(f"Esperaba int, recibí {type(value).__name__}: {value!r}")


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TypeError(f"Esperaba str, recibí {type(value).__name__}: {value!r}")


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise TypeError(f"Esperaba bool, recibí {type(value).__name__}: {value!r}")


def _as_str_tuple(value: Any) -> tuple[str, ...] | None:
    """Postgres emite `Sort Key` y `Group Key` como listas de strings."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise TypeError(f"Esperaba lista de strings, recibí {type(value).__name__}: {value!r}")

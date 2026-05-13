"""Detector D22 — count(*) (o cualquier agregación) sobre tabla grande sin WHERE.

Detecta cuando el plan ejecuta una agregación completa sobre una tabla
≥ `LARGE_TABLE_MIN_ROWS` filas sin filtros: el motor debe leer toda
la tabla (Seq Scan o equivalente paralelo) para producir un solo
escalar. Aplica al clásico `count(*)` pero también a `sum(x)`,
`avg(x)`, etc., sobre tabla completa.

Recomendaciones (las propondrá el LLM o template):
  - `pg_class.reltuples` para conteos aproximados baratos.
  - Tabla materializada de contadores mantenida por triggers.
  - Filtrar la query si el contexto lo permite.

La detección es estructural:

  1. Raíz `Aggregate` con `strategy="Plain"` y sin `group_key`.
  2. En el subárbol existe al menos un scan (Seq Scan, Index Scan,
     Index Only Scan, Bitmap Heap Scan) sobre la misma relación.
  3. Ninguno de esos scans tiene `Filter`, `Index Cond` ni
     `Recheck Cond` (la query no acota nada).
  4. La relación tiene `estimated_rows >= LARGE_TABLE_MIN_ROWS` en
     `snapshot["sizes"]`.
  5. El subárbol no contiene joins (la agregación no cruza tablas).

Esto evita falsos positivos con:
  - `SELECT count(*) FROM small_table` (umbral de tamaño).
  - `SELECT count(*) FROM t WHERE ...` (hay Filter).
  - `SELECT count(*) FROM t GROUP BY x` (strategy != Plain).
  - `SELECT count(*) FROM t1 JOIN t2 ...` (hay joins en el subárbol).

Cumple R1, R2 (estructura tipada del plan + snapshot), R9, R14.
"""

from __future__ import annotations

from typing import Any

from motor.detection import Detection
from motor.detectors._common import LARGE_TABLE_MIN_ROWS, resolve_table_key
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode

_SCAN_NODE_TYPES = frozenset(
    {
        "Seq Scan",
        "Index Scan",
        "Index Only Scan",
        "Bitmap Heap Scan",
    }
)

_JOIN_NODE_TYPES = frozenset({"Nested Loop", "Hash Join", "Merge Join"})


def detect_count_star_full_table(
    plan: ExplainResult | PlanNode,
    snapshot: dict[str, Any],
) -> Detection:
    """Detecta agregaciones completas sobre tabla grande sin WHERE.

    Args:
        plan: árbol del plan parseado. Se inspecciona la raíz para
            confirmar Aggregate(Plain, sin group_key) y se recorre el
            subárbol buscando un scan sin filtros.
        snapshot: SchemaSnapshot — se usa `snapshot["sizes"]` para
            verificar que la tabla escaneada sea grande.

    Returns:
        Detection. Cuando dispara, `evidence["matches"]` contiene una
        entrada con `table`, `estimated_rows`, `scan_node_type` y
        `suggested_alternatives` (lista de estrategias documentadas).
    """
    root = plan.root if isinstance(plan, ExplainResult) else plan

    if root.node_type != "Aggregate":
        return _empty()
    if root.strategy is not None and root.strategy != "Plain":
        return _empty()
    if root.group_key:
        return _empty()

    if find_nodes(root, _JOIN_NODE_TYPES):
        return _empty()

    scans = find_nodes(root, _SCAN_NODE_TYPES)
    if not scans:
        return _empty()

    if any(_has_filter(s) for s in scans):
        return _empty()

    relations = {s.relation_name for s in scans if s.relation_name}
    if len(relations) != 1:
        return _empty()
    relation = next(iter(relations))

    sizes = snapshot.get("sizes", {})
    table_key = resolve_table_key(sizes, relation)
    if table_key is None:
        return _empty()
    estimated_rows = sizes[table_key].get("estimated_rows", 0)
    if estimated_rows < LARGE_TABLE_MIN_ROWS:
        return _empty()

    primary_scan = scans[0]

    match = {
        "table": table_key,
        "estimated_rows": estimated_rows,
        "scan_node_type": primary_scan.node_type,
        "suggested_alternatives": (
            f"SELECT reltuples::bigint FROM pg_class WHERE relname = "
            f"'{relation}';  -- conteo aproximado O(1)",
            "Mantener una tabla de contadores actualizada con triggers "
            "INSERT/DELETE si se requiere exactitud O(1).",
            "Agregar un WHERE selectivo si el caso de uso lo permite.",
        ),
    }

    return Detection(
        found=True,
        confidence=0.95,
        evidence={"matches": [match]},
    )


def _empty() -> Detection:
    return Detection(found=False, confidence=0.0, evidence={"matches": []})


def _has_filter(scan: PlanNode) -> bool:
    """True si el scan tiene cualquier forma de predicado.

    El detector se abstiene en cuanto hay `Filter`, `Index Cond` o
    `Recheck Cond`: con cualquier acotación, la query ya no es un
    barrido completo de la tabla y no es el anti-pattern de D22.
    """
    return bool(scan.filter or scan.index_cond or scan.recheck_cond)

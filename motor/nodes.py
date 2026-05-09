"""Helpers para navegar árboles de `PlanNode`.

B9 del backlog. `find_nodes` es la base sobre la que cualquier
detector de anti-pattern razona: en lugar de buscar substrings en el
texto del EXPLAIN (prohibido por R2), los detectores piden los nodos
de un tipo y los analizan.

Diseño:

- `find_nodes` recorre en profundidad y devuelve una lista en el
  orden DFS (raíz primero). Lista, no generador, porque los
  detectores típicamente cuentan, intersectan o iteran varias veces.
- Acepta un `str` o un iterable de strings para permitir buscar
  familias enteras (p.ej. todos los scans con
  `("Seq Scan", "Index Scan", "Index Only Scan", ...)`).
- `KNOWN_NODE_TYPES` enumera los tipos que el parser ha visto en
  AppDB. No es restrictivo: el parser acepta cualquier `Node Type`
  que Postgres emita; esta constante existe para validar tests de
  cobertura y para que detectores futuros se documenten contra una
  lista cerrada.
"""

from __future__ import annotations

from collections.abc import Iterable

from motor.parser import ExplainResult, PlanNode

# Los 16 tipos de nodo que el backlog (B8) requiere soportar más
# Gather y Gather Merge, que aparecen naturalmente en planes
# paralelos de AppDB. Los detectores de `/motor` usan esta lista para
# documentar qué tipos cubren.
KNOWN_NODE_TYPES: frozenset[str] = frozenset(
    {
        "Seq Scan",
        "Index Scan",
        "Index Only Scan",
        "Bitmap Heap Scan",
        "Bitmap Index Scan",
        "Nested Loop",
        "Hash Join",
        "Merge Join",
        "Sort",
        "Hash",
        "Aggregate",
        "Limit",
        "Subquery Scan",
        "CTE Scan",
        "Materialize",
        "Gather",
        "Gather Merge",
    }
)


def find_nodes(
    tree: PlanNode | ExplainResult,
    node_type: str | Iterable[str],
) -> list[PlanNode]:
    """Devuelve todos los nodos del árbol cuyo `node_type` matchea.

    Recorre en DFS pre-order: el nodo padre aparece antes que sus
    hijos, los hermanos en el orden en que están en `children`.

    Acepta un `PlanNode` o un `ExplainResult` como entrada (en este
    último caso recorre desde `result.root`). Esto permite que los
    callers no tengan que hacer `.root` cada vez.

    `node_type` puede ser:
    - `str`: matchea exacto contra `PlanNode.node_type`.
    - iterable de `str`: matchea si `node_type` está en la colección.

    Devuelve lista vacía si no hay matches. Nunca lanza por "no
    encontrado": ausencia es un resultado válido.
    """
    root = tree.root if isinstance(tree, ExplainResult) else tree
    targets = _normalize_targets(node_type)

    found: list[PlanNode] = []
    _walk(root, targets, found)
    return found


def _walk(
    node: PlanNode,
    targets: frozenset[str],
    out: list[PlanNode],
) -> None:
    if node.node_type in targets:
        out.append(node)
    for child in node.children:
        _walk(child, targets, out)


def _normalize_targets(node_type: str | Iterable[str]) -> frozenset[str]:
    """Acepta `str` o iterable de `str`; rechaza otros tipos.

    Mantiene un solo path en `_walk` (siempre comparando contra un
    set), y permite al caller usar la forma que le sea más natural.
    """
    if isinstance(node_type, str):
        return frozenset({node_type})
    return frozenset(node_type)

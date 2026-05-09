"""Tests de `find_nodes` (B9).

Verifica:

1. Caso happy: en un plan complejo con joins anidados encuentra
   todos los Seq Scan (criterio explícito de B9).
2. Acepta tanto `PlanNode` como `ExplainResult`.
3. Acepta `str` o iterable de tipos.
4. Devuelve lista vacía cuando no hay matches.
5. Mantiene orden DFS pre-order.
6. Encuentra nodos en cualquier nivel de profundidad.
"""

from __future__ import annotations

from typing import Any

from motor import find_nodes, parse_explain
from motor.parser import PlanNode

# --- criterio del backlog ------------------------------------------


def test_encuentra_todos_los_seq_scan_en_plan_complejo(
    plan_hash_join_aggregate_sort: Any,
) -> None:
    """Hecho cuando: 'un test verifica que encuentra todos los Seq
    Scan en un plan complejo con joins anidados'.

    El plan 04 tiene esta forma:
        Limit > Aggregate > Gather Merge > Sort > Aggregate >
            Hash Join > [Seq Scan(posts), Hash > Index Only Scan(users)]
    Hay exactamente un Seq Scan, y debe encontrarlo aunque esté
    profundo en el árbol.
    """
    result = parse_explain(plan_hash_join_aggregate_sort)
    seq_scans = find_nodes(result, "Seq Scan")
    assert len(seq_scans) == 1
    assert seq_scans[0].relation_name == "posts"


def test_encuentra_multiples_nodos_del_mismo_tipo(
    plan_bitmap_scan: Any,
) -> None:
    """El plan 08 tiene dos Bitmap Index Scan bajo un BitmapOr."""
    result = parse_explain(plan_bitmap_scan)
    bis = find_nodes(result, "Bitmap Index Scan")
    assert len(bis) == 2


# --- formas de entrada ---------------------------------------------


def test_acepta_plan_node_directo(plan_index_scan: Any) -> None:
    result = parse_explain(plan_index_scan)
    nodes = find_nodes(result.root, "Index Scan")
    assert len(nodes) == 1
    assert isinstance(nodes[0], PlanNode)


def test_acepta_explain_result(plan_index_scan: Any) -> None:
    result = parse_explain(plan_index_scan)
    nodes = find_nodes(result, "Index Scan")
    assert len(nodes) == 1


def test_acepta_iterable_de_tipos(plan_hash_join_aggregate_sort: Any) -> None:
    """Buscar familia 'todos los scans' con un solo find_nodes."""
    result = parse_explain(plan_hash_join_aggregate_sort)
    scans = find_nodes(
        result,
        ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan"),
    )
    # plan tiene Seq Scan(posts) e Index Only Scan(users)
    tipos = sorted(n.node_type for n in scans)
    assert tipos == ["Index Only Scan", "Seq Scan"]


def test_acepta_set_de_tipos(plan_hash_join_aggregate_sort: Any) -> None:
    result = parse_explain(plan_hash_join_aggregate_sort)
    nodes = find_nodes(result, {"Hash Join", "Sort"})
    tipos_vistos = {n.node_type for n in nodes}
    assert tipos_vistos == {"Hash Join", "Sort"}


# --- casos negativos -----------------------------------------------


def test_lista_vacia_cuando_tipo_no_existe(plan_index_scan: Any) -> None:
    result = parse_explain(plan_index_scan)
    assert find_nodes(result, "Hash Join") == []


def test_lista_vacia_cuando_iterable_vacio(plan_index_scan: Any) -> None:
    result = parse_explain(plan_index_scan)
    assert find_nodes(result, []) == []


# --- orden DFS pre-order -------------------------------------------


def test_orden_dfs_preorder(plan_recursive_cte: Any) -> None:
    """Plan 09: CTE Scan > Recursive Union > [Index Only Scan,
    Nested Loop > [WorkTable Scan, Index Only Scan]]

    En DFS pre-order el primer Index Only Scan es el outer del
    Recursive Union; el segundo está bajo Nested Loop.
    """
    result = parse_explain(plan_recursive_cte)
    ios = find_nodes(result, "Index Only Scan")
    assert len(ios) == 2
    # El primero debe ser el "Outer" del Recursive Union (sin parent
    # Nested Loop encima).
    assert ios[0].parent_relationship == "Outer"
    # El segundo está dentro del Nested Loop.
    assert ios[1].parent_relationship == "Inner"


def test_raiz_se_devuelve_si_matchea() -> None:
    """Si el tipo buscado es la raíz, find_nodes la devuelve también."""
    plan = {
        "Plan": {
            "Node Type": "Limit",
            "Startup Cost": 0.0,
            "Total Cost": 1.0,
            "Plan Rows": 1,
            "Plan Width": 1,
            "Plans": [
                {
                    "Node Type": "Limit",
                    "Startup Cost": 0.0,
                    "Total Cost": 1.0,
                    "Plan Rows": 1,
                    "Plan Width": 1,
                }
            ],
        }
    }
    result = parse_explain(plan)
    limits = find_nodes(result, "Limit")
    assert len(limits) == 2  # raíz y su hijo

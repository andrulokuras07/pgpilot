"""Tests de cobertura completa de tipos de nodo (B8).

Verifica que para cada tipo de nodo de la lista del backlog (16
tipos), el parser:

1. Reconoce el `node_type` y lo expone tal cual.
2. Extrae los campos específicos relevantes (Index Cond, Hash Cond,
   Sort Key, Group Key, etc.) cuando el JSON los incluye.

Hecho cuando: 'los 16 tipos de nodo se parsean y tienen sus campos
accesibles'.
"""

from __future__ import annotations

from typing import Any

from motor import KNOWN_NODE_TYPES, find_nodes, parse_explain

# Los 16 tipos que el backlog (B8) requiere soportar. Si esta lista
# se mueve, hay que actualizar `motor/nodes.py:KNOWN_NODE_TYPES`.
TIPOS_REQUERIDOS_POR_B8: frozenset[str] = frozenset(
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
    }
)


def test_known_node_types_cubre_los_de_b8() -> None:
    """`KNOWN_NODE_TYPES` debe incluir los 16 que pide B8."""
    assert TIPOS_REQUERIDOS_POR_B8.issubset(KNOWN_NODE_TYPES)


def test_los_16_tipos_aparecen_al_menos_en_un_fixture(
    plan_aggregate_seq_scan: Any,
    plan_index_scan: Any,
    plan_hash_join_aggregate_sort: Any,
    plan_bitmap_scan: Any,
    plan_recursive_cte: Any,
    plan_merge_join: Any,
    plan_subquery_scan: Any,
    plan_materialize: Any,
    plan_limit_nested_loop: Any,
) -> None:
    """Recorre todos los fixtures y junta los node_types vistos."""
    fixtures = [
        plan_aggregate_seq_scan,
        plan_index_scan,
        plan_hash_join_aggregate_sort,
        plan_bitmap_scan,
        plan_recursive_cte,
        plan_merge_join,
        plan_subquery_scan,
        plan_materialize,
        plan_limit_nested_loop,
    ]
    vistos: set[str] = set()
    for plan in fixtures:
        result = parse_explain(plan)
        # find_nodes con todos los tipos conocidos = recorrido completo
        for node in find_nodes(result, KNOWN_NODE_TYPES):
            vistos.add(node.node_type)
    faltantes = TIPOS_REQUERIDOS_POR_B8 - vistos
    assert not faltantes, f"Tipos no encontrados en ningún fixture: {faltantes}"


# --- extracción de campos por tipo ---------------------------------


def test_seq_scan_expone_filter_y_relation(
    plan_aggregate_seq_scan: Any,
) -> None:
    seq = find_nodes(parse_explain(plan_aggregate_seq_scan), "Seq Scan")[0]
    assert seq.relation_name == "tags"
    assert seq.filter is not None
    assert "name" in seq.filter
    assert seq.rows_removed_by_filter is not None


def test_index_scan_expone_index_cond_y_index_name(
    plan_index_scan: Any,
) -> None:
    idx = find_nodes(parse_explain(plan_index_scan), "Index Scan")[0]
    assert idx.index_name == "idx_users_email"
    assert idx.index_cond is not None
    assert "email" in idx.index_cond


def test_index_only_scan_expone_heap_fetches(
    plan_hash_join_aggregate_sort: Any,
) -> None:
    ios = find_nodes(parse_explain(plan_hash_join_aggregate_sort), "Index Only Scan")
    assert ios, "El fixture debería tener al menos un Index Only Scan"
    assert ios[0].heap_fetches is not None
    assert ios[0].index_name


def test_bitmap_heap_scan_expone_recheck_cond(plan_bitmap_scan: Any) -> None:
    bhs = find_nodes(parse_explain(plan_bitmap_scan), "Bitmap Heap Scan")[0]
    assert bhs.relation_name == "users"
    assert bhs.recheck_cond is not None


def test_bitmap_index_scan_expone_index_cond(plan_bitmap_scan: Any) -> None:
    bis = find_nodes(parse_explain(plan_bitmap_scan), "Bitmap Index Scan")
    assert bis, "Bitmap Heap Scan debería tener un Bitmap Index Scan debajo"
    for node in bis:
        assert node.index_cond is not None
        assert node.index_name


def test_nested_loop_expone_join_type(plan_limit_nested_loop: Any) -> None:
    nl = find_nodes(parse_explain(plan_limit_nested_loop), "Nested Loop")[0]
    assert nl.join_type == "Inner"
    assert nl.inner_unique is not None


def test_hash_join_expone_hash_cond(plan_hash_join_aggregate_sort: Any) -> None:
    hj = find_nodes(parse_explain(plan_hash_join_aggregate_sort), "Hash Join")[0]
    assert hj.hash_cond is not None
    assert hj.join_type


def test_merge_join_expone_merge_cond(plan_merge_join: Any) -> None:
    mj = find_nodes(parse_explain(plan_merge_join), "Merge Join")[0]
    assert mj.merge_cond is not None
    assert mj.join_type


def test_sort_expone_sort_key_como_tupla(
    plan_hash_join_aggregate_sort: Any,
) -> None:
    sort = find_nodes(parse_explain(plan_hash_join_aggregate_sort), "Sort")[0]
    assert sort.sort_key is not None
    assert isinstance(sort.sort_key, tuple)
    assert len(sort.sort_key) >= 1


def test_hash_expone_hash_buckets(plan_hash_join_aggregate_sort: Any) -> None:
    h = find_nodes(parse_explain(plan_hash_join_aggregate_sort), "Hash")[0]
    assert h.hash_buckets is not None
    assert h.hash_batches is not None


def test_aggregate_expone_strategy(plan_hash_join_aggregate_sort: Any) -> None:
    aggs = find_nodes(parse_explain(plan_hash_join_aggregate_sort), "Aggregate")
    assert aggs
    assert any(a.strategy is not None for a in aggs)


def test_aggregate_con_groupby_expone_group_key(
    plan_hash_join_groupby: Any,
) -> None:
    aggs = find_nodes(parse_explain(plan_hash_join_groupby), "Aggregate")
    con_group = [a for a in aggs if a.group_key is not None]
    assert con_group, "Plan con GROUP BY debería tener Group Key en algún Aggregate"
    assert isinstance(con_group[0].group_key, tuple)


def test_limit_es_un_nodo_valido(plan_limit_nested_loop: Any) -> None:
    limit = find_nodes(parse_explain(plan_limit_nested_loop), "Limit")
    assert limit
    assert limit[0].children, "Limit siempre tiene un hijo"


def test_subquery_scan_expone_alias(plan_subquery_scan: Any) -> None:
    sq = find_nodes(parse_explain(plan_subquery_scan), "Subquery Scan")[0]
    assert sq.alias is not None


def test_cte_scan_expone_cte_name(plan_recursive_cte: Any) -> None:
    cte = find_nodes(parse_explain(plan_recursive_cte), "CTE Scan")[0]
    assert cte.cte_name is not None


def test_materialize_se_parsea(plan_materialize: Any) -> None:
    mat = find_nodes(parse_explain(plan_materialize), "Materialize")[0]
    # Materialize siempre tiene un solo hijo
    assert len(mat.children) == 1
    assert mat.actual_loops is not None


def test_gather_expone_workers_planned(plan_limit_nested_loop: Any) -> None:
    gather = find_nodes(parse_explain(plan_limit_nested_loop), "Gather")
    assert gather
    assert gather[0].workers_planned is not None

"""Tests de `sandbox.setup_sandbox_schema` y `drop_sandbox_schema` (B15).

Cubre el criterio del backlog: "un test crea un schema temporal con
3 tablas y stats falseadas, ejecuta EXPLAIN SELECT..., recibe un plan
razonable". Eso vive en `test_setup_explain_uses_faked_stats`. El
resto verifica las propiedades individuales del montaje.

Todos los tests aquí necesitan el contenedor `sandbox` levantado
(puerto 5435 por default). Se marcan con `@pytest.mark.integration`.
"""

from __future__ import annotations

import json

import pytest

from conector.types import SchemaSnapshot
from sandbox import drop_sandbox_schema, setup_sandbox_schema

pytestmark = pytest.mark.integration


def _table_exists(pool, schema_name: str, table_name: str) -> bool:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s AND c.relkind = 'r'",
            (schema_name, table_name),
        ).fetchone()
    return row is not None


def _index_exists(pool, schema_name: str, index_name: str) -> bool:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s AND c.relkind = 'i'",
            (schema_name, index_name),
        ).fetchone()
    return row is not None


def _read_relation_stats(pool, schema_name: str, table_name: str) -> tuple[float, int]:
    qualified = f"{schema_name}.{table_name}"
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT reltuples, relpages FROM pg_class WHERE oid = %s::regclass",
            (qualified,),
        ).fetchone()
    assert row is not None, f"no se encontró {qualified} en pg_class"
    return float(row[0]), int(row[1])


def test_setup_creates_schema_with_three_tables(sandbox_pool, synthetic_snapshot):
    schema_name = setup_sandbox_schema(sandbox_pool, synthetic_snapshot)
    try:
        assert _table_exists(sandbox_pool, schema_name, "users")
        assert _table_exists(sandbox_pool, schema_name, "posts")
        assert _table_exists(sandbox_pool, schema_name, "tags")
    finally:
        drop_sandbox_schema(sandbox_pool, schema_name)


def test_setup_creates_indexes_declared_in_snapshot(sandbox_pool, synthetic_snapshot):
    schema_name = setup_sandbox_schema(sandbox_pool, synthetic_snapshot)
    try:
        assert _index_exists(sandbox_pool, schema_name, "users_pkey_synth")
        assert _index_exists(sandbox_pool, schema_name, "idx_users_email_synth")
        assert _index_exists(sandbox_pool, schema_name, "posts_pkey_synth")
        # posts.author_id NO debe tener índice (Q01).
        assert not _index_exists(sandbox_pool, schema_name, "idx_posts_author_id_synth")
    finally:
        drop_sandbox_schema(sandbox_pool, schema_name)


def test_setup_fakes_relation_stats(sandbox_pool, synthetic_snapshot):
    schema_name = setup_sandbox_schema(sandbox_pool, synthetic_snapshot)
    try:
        reltuples, relpages = _read_relation_stats(sandbox_pool, schema_name, "posts")
        # El snapshot declara 5_000_000 filas para posts.
        assert reltuples == pytest.approx(5_000_000.0)
        # relpages = max(1, rows // 100) = 50_000.
        assert relpages == 50_000
    finally:
        drop_sandbox_schema(sandbox_pool, schema_name)


def test_setup_skips_unknown_category(sandbox_pool, synthetic_snapshot: SchemaSnapshot):
    """Tablas con `category="unknown"` no deben quedar con stats falseadas."""
    # Marcamos posts como unknown para este test.
    synthetic_snapshot["sizes"]["public.posts"]["category"] = "unknown"

    schema_name = setup_sandbox_schema(sandbox_pool, synthetic_snapshot)
    try:
        reltuples, relpages = _read_relation_stats(sandbox_pool, schema_name, "posts")
        # Postgres reporta -1 / 0 cuando una tabla nunca tuvo ANALYZE
        # ni UPDATE manual. Aceptamos ambos defaults.
        assert reltuples in (-1.0, 0.0)
        assert relpages == 0
    finally:
        drop_sandbox_schema(sandbox_pool, schema_name)


def test_setup_two_schemas_are_independent(sandbox_pool, synthetic_snapshot):
    """Dos llamadas concurrentes al setup producen schemas que no colisionan."""
    schema_a = setup_sandbox_schema(sandbox_pool, synthetic_snapshot)
    schema_b = setup_sandbox_schema(sandbox_pool, synthetic_snapshot)
    try:
        assert schema_a != schema_b
        assert _table_exists(sandbox_pool, schema_a, "posts")
        assert _table_exists(sandbox_pool, schema_b, "posts")
    finally:
        drop_sandbox_schema(sandbox_pool, schema_a)
        drop_sandbox_schema(sandbox_pool, schema_b)


def test_drop_schema_removes_tables(sandbox_pool, synthetic_snapshot):
    schema_name = setup_sandbox_schema(sandbox_pool, synthetic_snapshot)
    assert _table_exists(sandbox_pool, schema_name, "posts")
    drop_sandbox_schema(sandbox_pool, schema_name)
    assert not _table_exists(sandbox_pool, schema_name, "posts")


def test_drop_schema_is_idempotent(sandbox_pool):
    """Llamar drop sobre un schema inexistente no debe explotar."""
    drop_sandbox_schema(sandbox_pool, "analysis_does_not_exist_xyz")


def test_setup_explain_returns_reasonable_plan(sandbox_pool, synthetic_snapshot):
    """Criterio de B15 ("plan razonable") aterrizado como: con las 3 tablas
    montadas, `EXPLAIN` devuelve un plan parseable cuyo nodo raíz refiere
    a la tabla esperada y tipo de scan esperado.

    No comparamos costos absolutos a propósito: PG18 persiste `relpages`/
    `reltuples` con `pg_restore_relation_stats` pero su planner sigue
    consultando el tamaño físico del archivo (`RelationGetNumberOfBlocks`),
    y para tablas vacías eso empuja los costos a ~0. La validación
    por costo se atenderá en C3 (puede requerir inserción acotada de
    filas sintéticas, fuera del alcance de B15).
    """
    schema_name = setup_sandbox_schema(sandbox_pool, synthetic_snapshot)
    try:
        with sandbox_pool.connection() as conn:
            with conn.transaction():
                conn.execute(f"SET LOCAL search_path = {schema_name}, public")

                cur = conn.execute("EXPLAIN (FORMAT JSON) SELECT * FROM posts WHERE author_id = 42")
                posts_plan = cur.fetchone()[0]

        if isinstance(posts_plan, str):
            posts_plan = json.loads(posts_plan)

        top = posts_plan[0]["Plan"]
        assert top["Node Type"] == "Seq Scan"
        assert top["Relation Name"] == "posts"
        assert top["Filter"] == "(author_id = 42)"
    finally:
        drop_sandbox_schema(sandbox_pool, schema_name)

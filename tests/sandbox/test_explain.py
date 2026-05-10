"""Tests de `sandbox.explain_in_sandbox` (B16).

Cubre el criterio del backlog: "la función corre EXPLAIN sobre AppDB
schema y devuelve un plan en menos de 5 segundos". Eso vive en
`test_explain_with_appdb_snapshot_under_5_seconds`. El resto verifica
propiedades complementarias: parseo correcto, cleanup ante éxito y
ante error, respeto al timeout, uso de stats falseadas para producir
seq scans esperables.

Requiere los dos contenedores levantados (`appdb` en 5434 y
`sandbox` en 5435). Tests marcados con `@pytest.mark.integration`.
"""

from __future__ import annotations

import time

import psycopg
import pytest

from conector import extract_snapshot
from motor import ExplainResult, find_nodes
from sandbox import explain_in_sandbox

pytestmark = pytest.mark.integration


def _schema_exists(pool, schema_name: str) -> bool:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = %s",
            (schema_name,),
        ).fetchone()
    return row is not None


def test_explain_returns_parseable_plan(sandbox_pool, synthetic_snapshot):
    result = explain_in_sandbox(
        sandbox_pool,
        synthetic_snapshot,
        "SELECT * FROM posts WHERE author_id = 42",
    )

    assert isinstance(result, ExplainResult)
    assert result.root.node_type  # algún tipo de nodo


def test_explain_picks_seq_scan_on_unindexed_column(sandbox_pool, synthetic_snapshot):
    """Con stats falseadas a 5M filas y sin índice en `author_id`, el
    planner debe elegir Seq Scan. Es la base sobre la que C1 detectará
    el anti-pattern Q01 cuando exista."""
    result = explain_in_sandbox(
        sandbox_pool,
        synthetic_snapshot,
        "SELECT * FROM posts WHERE author_id = 42",
    )

    seq_scans = find_nodes(result, "Seq Scan")
    assert len(seq_scans) >= 1, f"Se esperaba al menos un Seq Scan; el plan fue: {result.root!r}"


def test_explain_with_appdb_snapshot_under_5_seconds(appdb_pool, sandbox_pool):
    """B16 acceptance: `EXPLAIN` sobre el schema real de AppDB termina
    en menos de 5 segundos."""
    snapshot = extract_snapshot(appdb_pool)

    start = time.monotonic()
    result = explain_in_sandbox(
        sandbox_pool,
        snapshot,
        "SELECT * FROM posts WHERE author_id = 42",
    )
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, f"EXPLAIN en sandbox tardó {elapsed:.2f}s, excedió 5s"
    assert isinstance(result, ExplainResult)


def test_explain_drops_schema_after_success(sandbox_pool, synthetic_snapshot):
    """Cleanup en el happy path: el schema temporal no debe quedar."""
    schema_name = "analysis_explain_cleanup_ok"
    explain_in_sandbox(
        sandbox_pool,
        synthetic_snapshot,
        "SELECT * FROM posts",
        schema_name=schema_name,
    )

    assert not _schema_exists(sandbox_pool, schema_name)


def test_explain_drops_schema_after_query_error(sandbox_pool, synthetic_snapshot):
    """Cleanup ante error: si el EXPLAIN falla (tabla inexistente),
    igual se dropea el schema temporal. Garantiza que un crash en
    medio del análisis no deja schemas zombies."""
    schema_name = "analysis_explain_cleanup_err"
    with pytest.raises(psycopg.errors.UndefinedTable):
        explain_in_sandbox(
            sandbox_pool,
            synthetic_snapshot,
            "SELECT * FROM tabla_que_no_existe",
            schema_name=schema_name,
        )

    assert not _schema_exists(sandbox_pool, schema_name)


def test_sandbox_pool_statement_timeout_aborts_slow_query(sandbox_pool):
    """El pool del sandbox arrastra el `statement_timeout` (default 5s)
    y aborta queries lentas con `QueryCanceled` (SQLSTATE 57014).
    Análogo a `tests/conector/test_pool.py::test_statement_timeout_aborta_query_lenta`,
    aplicado aquí porque sandbox tiene su propio `create_sandbox_pool`."""
    with sandbox_pool.connection() as conn:
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout = 100")  # 100 ms
            with pytest.raises(psycopg.errors.QueryCanceled):
                conn.execute("SELECT pg_sleep(2)")

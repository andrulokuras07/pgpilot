"""Fixtures compartidas de los tests de integración (D14 + D15).

Reutiliza el `appdb_pool` ya usado en `tests/conector/`, pero las
fixtures se declaran localmente para no acoplar paquetes de tests.
Las dos fixtures (`appdb_pool`, `appdb_snapshot`) son `session`-scoped
para evitar crear N pools y N snapshots cuando los tests parametrizados
de cobertura corren 20 veces.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from psycopg_pool import ConnectionPool

from conector import ConnectionConfig, create_pool, extract_snapshot


@pytest.fixture(scope="session")
def appdb_pool() -> Iterator[ConnectionPool]:
    config = ConnectionConfig(
        host=os.getenv("APPDB_HOST", "localhost"),
        port=int(os.getenv("APPDB_PORT", "5434")),
        dbname=os.getenv("APPDB_DB", "appdb"),
        user=os.getenv("APPDB_USER", "app_user"),
        password=os.getenv("APPDB_PASSWORD", "app_pass"),
        # Tests de cobertura corren `EXPLAIN ANALYZE` sobre queries
        # pesadas (Q01/Q15 Seq Scan sobre millones de filas, Q19 NOT IN
        # sin índice). El default de 5s del conector no alcanza; 180 s
        # da margen estable para que Q19 complete bajo carga del WSL y
        # mantiene la suite por debajo de 3 min en caso peor.
        statement_timeout_ms=int(os.getenv("APPDB_TEST_TIMEOUT_MS", "180000")),
    )
    pool = create_pool(config)
    try:
        yield pool
    finally:
        pool.close()


@pytest.fixture(scope="session")
def appdb_snapshot(appdb_pool: ConnectionPool) -> dict[str, Any]:
    """Snapshot del schema de AppDB v1; cacheado por sesión.

    Cada test de cobertura llama 13 detectores; sin cachear el snapshot,
    20 tests × 1 extracción ≈ 60 s extra de I/O contra la BD.
    """
    return extract_snapshot(appdb_pool)

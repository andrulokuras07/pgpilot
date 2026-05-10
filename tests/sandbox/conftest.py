"""Fixtures de tests del módulo sandbox.

Define dos pools de sesión (sandbox y AppDB) y un snapshot sintético
liviano para los tests de `setup_sandbox_schema`. El snapshot real
de AppDB se construye dentro de los tests que lo necesitan, para no
penalizar el arranque de los que no.

Convenciones:
- Variables de entorno con prefijo `SANDBOX_*` y `APPDB_*` (ver
  `.env.example`). Defaults coinciden con `docker-compose.yml`.
- Todos los tests del módulo son `@pytest.mark.integration` (requieren
  contenedores levantados): los marca cada test individualmente para
  poder filtrar con `-m "not integration"` y validar al menos imports.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from psycopg_pool import ConnectionPool

from conector import ConnectionConfig, create_pool
from conector.schema import ColumnInfo, IndexInfo, TableSchema
from conector.sizes import TableSize
from conector.types import SchemaSnapshot
from sandbox import SandboxConfig, create_sandbox_pool


@pytest.fixture(scope="session")
def sandbox_config() -> SandboxConfig:
    return SandboxConfig(
        host=os.getenv("SANDBOX_HOST", "localhost"),
        port=int(os.getenv("SANDBOX_PORT", "5435")),
        dbname=os.getenv("SANDBOX_DB", "sandbox"),
        user=os.getenv("SANDBOX_USER", "sandbox_user"),
        password=os.getenv("SANDBOX_PASSWORD", "sandbox_pass"),
    )


@pytest.fixture(scope="session")
def sandbox_pool(sandbox_config: SandboxConfig) -> Iterator[ConnectionPool]:
    pool = create_sandbox_pool(sandbox_config)
    try:
        yield pool
    finally:
        pool.close()


@pytest.fixture(scope="session")
def appdb_config() -> ConnectionConfig:
    return ConnectionConfig(
        host=os.getenv("APPDB_HOST", "localhost"),
        port=int(os.getenv("APPDB_PORT", "5434")),
        dbname=os.getenv("APPDB_DB", "appdb"),
        user=os.getenv("APPDB_USER", "app_user"),
        password=os.getenv("APPDB_PASSWORD", "app_pass"),
    )


@pytest.fixture(scope="session")
def appdb_pool(appdb_config: ConnectionConfig) -> Iterator[ConnectionPool]:
    pool = create_pool(appdb_config)
    try:
        yield pool
    finally:
        pool.close()


@pytest.fixture
def synthetic_snapshot() -> SchemaSnapshot:
    """SchemaSnapshot de 3 tablas para tests de setup sin tocar AppDB.

    Cubre el caso de B15 acceptance: 3 tablas, una de ellas grande con
    índice (`users`), otra grande sin índice en la columna que filtra
    (`posts.author_id`, equivalente a Q01 de AppDB), y una pequeña
    (`tags`) para verificar que no se intentan stats sobre tablas
    chicas también.
    """
    return SchemaSnapshot(
        schema={
            "public.users": TableSchema(
                schema="public",
                name="users",
                columns=[
                    ColumnInfo(
                        name="id",
                        data_type="integer",
                        is_nullable=False,
                        ordinal_position=1,
                    ),
                    ColumnInfo(
                        name="email",
                        data_type="character varying(200)",
                        is_nullable=False,
                        ordinal_position=2,
                    ),
                ],
                indexes=[
                    IndexInfo(
                        name="users_pkey_synth",
                        columns=["id"],
                        method="btree",
                        is_unique=True,
                        is_primary=True,
                    ),
                    IndexInfo(
                        name="idx_users_email_synth",
                        columns=["email"],
                        method="btree",
                        is_unique=True,
                        is_primary=False,
                    ),
                ],
                foreign_keys=[],
            ),
            "public.posts": TableSchema(
                schema="public",
                name="posts",
                columns=[
                    ColumnInfo(
                        name="id",
                        data_type="bigint",
                        is_nullable=False,
                        ordinal_position=1,
                    ),
                    ColumnInfo(
                        name="author_id",
                        data_type="integer",
                        is_nullable=False,
                        ordinal_position=2,
                    ),
                    ColumnInfo(
                        name="content",
                        data_type="text",
                        is_nullable=True,
                        ordinal_position=3,
                    ),
                ],
                indexes=[
                    IndexInfo(
                        name="posts_pkey_synth",
                        columns=["id"],
                        method="btree",
                        is_unique=True,
                        is_primary=True,
                    ),
                    # Sin índice en author_id — equivalente a Q01.
                ],
                foreign_keys=[],
            ),
            "public.tags": TableSchema(
                schema="public",
                name="tags",
                columns=[
                    ColumnInfo(
                        name="id",
                        data_type="integer",
                        is_nullable=False,
                        ordinal_position=1,
                    ),
                    ColumnInfo(
                        name="name",
                        data_type="character varying(50)",
                        is_nullable=False,
                        ordinal_position=2,
                    ),
                ],
                indexes=[
                    IndexInfo(
                        name="tags_pkey_synth",
                        columns=["id"],
                        method="btree",
                        is_unique=True,
                        is_primary=True,
                    ),
                ],
                foreign_keys=[],
            ),
        },
        sizes={
            "public.users": TableSize(
                schema="public",
                name="users",
                estimated_rows=500_000,
                total_bytes=50_000_000,
                category="medium",
            ),
            "public.posts": TableSize(
                schema="public",
                name="posts",
                estimated_rows=5_000_000,
                total_bytes=600_000_000,
                category="large",
            ),
            "public.tags": TableSize(
                schema="public",
                name="tags",
                estimated_rows=200,
                total_bytes=16_384,
                category="small",
            ),
        },
        stats={},
    )

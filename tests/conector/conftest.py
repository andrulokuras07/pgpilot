import os
from collections.abc import Iterator

import pytest
from psycopg_pool import ConnectionPool

from conector import ConnectionConfig, create_pool


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

"""Tests para `get_table_sizes` y `categorize`.

`categorize` se prueba como función pura. `get_table_sizes` necesita
AppDB corriendo (ver `tests/conector/conftest.py`).
"""

import pytest
from psycopg_pool import ConnectionPool

from conector import (
    LARGE_ROWS_THRESHOLD,
    SMALL_ROWS_THRESHOLD,
    categorize,
    get_table_sizes,
)


def test_categorize_unknown_para_reltuples_negativo() -> None:
    assert categorize(-1) == "unknown"


def test_categorize_small_bajo_threshold() -> None:
    assert categorize(0) == "small"
    assert categorize(SMALL_ROWS_THRESHOLD - 1) == "small"


def test_categorize_medium_entre_thresholds() -> None:
    assert categorize(SMALL_ROWS_THRESHOLD) == "medium"
    assert categorize(LARGE_ROWS_THRESHOLD - 1) == "medium"


def test_categorize_large_sobre_threshold() -> None:
    assert categorize(LARGE_ROWS_THRESHOLD) == "large"
    assert categorize(50_000_000) == "large"


@pytest.mark.integration
def test_devuelve_tamano_para_tablas_de_appdb(appdb_pool: ConnectionPool) -> None:
    sizes = get_table_sizes(appdb_pool)

    expected_tables = {
        "public.users",
        "public.posts",
        "public.comments",
        "public.likes",
        "public.follows",
        "public.notifications",
        "public.tags",
        "public.post_tags",
    }
    assert expected_tables.issubset(set(sizes.keys()))


@pytest.mark.integration
def test_categoria_y_estimated_rows_consistentes(appdb_pool: ConnectionPool) -> None:
    """Para cada tabla, la categoría debe coincidir con el rango de
    `estimated_rows`. Si AppDB nunca tuvo ANALYZE, `estimated_rows`
    queda en 0 y categoria == "unknown" (caso aceptado)."""
    sizes = get_table_sizes(appdb_pool)

    for key, size in sizes.items():
        rows = size["estimated_rows"]
        category = size["category"]
        if category == "unknown":
            assert rows == 0
        elif category == "small":
            assert rows < SMALL_ROWS_THRESHOLD
        elif category == "medium":
            assert SMALL_ROWS_THRESHOLD <= rows < LARGE_ROWS_THRESHOLD
        elif category == "large":
            assert rows >= LARGE_ROWS_THRESHOLD
        else:
            pytest.fail(f"categoria inesperada {category!r} en {key}")


@pytest.mark.integration
def test_total_bytes_es_positivo(appdb_pool: ConnectionPool) -> None:
    """Una tabla creada (aunque vacía) tiene al menos 0 bytes de heap;
    con datos plantados debe pasar de 0."""
    sizes = get_table_sizes(appdb_pool)
    assert all(size["total_bytes"] >= 0 for size in sizes.values())
    # AppDB v1 tiene seed_data y plant_problems, así que al menos una
    # tabla debe ocupar bytes reales.
    assert any(size["total_bytes"] > 0 for size in sizes.values())

"""Fixtures compartidas para los tests del módulo motor.

Los planes EXPLAIN se cargan desde `tests/motor/fixtures/*.json`.
Cada archivo es el output crudo de
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` contra AppDB v1
(ver `tests/motor/fixtures/README.md` para qué query produjo cada
uno) más un fixture sintético para `Materialize` que no aparece
naturalmente con el data-set actual.

Los tests son unit (no requieren AppDB corriendo): operan solo sobre
los JSON serializados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> Any:
    """Carga un fixture por nombre de archivo (sin path completo)."""
    with (FIXTURES_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def all_fixture_paths() -> list[Path]:
    """Lista ordenada de todos los fixtures JSON."""
    return sorted(FIXTURES_DIR.glob("*.json"))


@pytest.fixture
def plan_index_scan() -> Any:
    return _load("01_index_scan.json")


@pytest.fixture
def plan_aggregate_seq_scan() -> Any:
    return _load("02_aggregate_seq_scan.json")


@pytest.fixture
def plan_limit_nested_loop() -> Any:
    return _load("03_limit_nested_loop.json")


@pytest.fixture
def plan_hash_join_aggregate_sort() -> Any:
    """Plan complejo con muchos tipos de nodo. Usado en find_nodes."""
    return _load("04_hash_join_aggregate_sort.json")


@pytest.fixture
def plan_hash_join_groupby() -> Any:
    return _load("05_hash_join_groupby.json")


@pytest.fixture
def plan_aggregate_hash_join() -> Any:
    return _load("06_aggregate_hash_join.json")


@pytest.fixture
def plan_gather_sort_seq() -> Any:
    return _load("07_gather_sort_seq.json")


@pytest.fixture
def plan_bitmap_scan() -> Any:
    return _load("08_bitmap_scan.json")


@pytest.fixture
def plan_recursive_cte() -> Any:
    return _load("09_recursive_cte.json")


@pytest.fixture
def plan_merge_join() -> Any:
    return _load("10_merge_join.json")


@pytest.fixture
def plan_nested_loop_index() -> Any:
    return _load("11_nested_loop_index.json")


@pytest.fixture
def plan_subquery_scan() -> Any:
    return _load("12_subquery_scan.json")


@pytest.fixture
def plan_materialize() -> Any:
    """Sintético: PG no eligió Materialize con AppDB, pero el parser
    debe soportarlo (B8 requiere los 16 tipos)."""
    return _load("13_materialize.json")

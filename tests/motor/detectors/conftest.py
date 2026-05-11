"""Fixtures para los tests de detectores.

Los snapshots aquí son sintéticos y mínimos: solo los campos que
los detectores leen del `SchemaSnapshot` real del conector. No
necesitamos AppDB corriendo (R9 + tests unit).
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def snapshot_posts_con_indice_en_author_id() -> dict[str, Any]:
    """Caso positivo C1: tabla grande (500k filas) con índice btree
    en la columna del filtro. Replica el setup de Q01 EXCEPTO que
    el índice SÍ existe — es el escenario donde el planner sigue
    eligiendo Seq Scan a pesar del índice (lo que C1 debe detectar).
    """
    return {
        "schema": {
            "public.posts": {
                "schema": "public",
                "name": "posts",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "bigint",
                        "is_nullable": False,
                        "ordinal_position": 1,
                    },
                    {
                        "name": "author_id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "ordinal_position": 2,
                    },
                ],
                "indexes": [
                    {
                        "name": "posts_pkey",
                        "columns": ["id"],
                        "method": "btree",
                        "is_unique": True,
                        "is_primary": True,
                    },
                    {
                        "name": "idx_posts_author_id",
                        "columns": ["author_id"],
                        "method": "btree",
                        "is_unique": False,
                        "is_primary": False,
                    },
                ],
                "foreign_keys": [],
            },
        },
        "sizes": {
            "public.posts": {
                "estimated_rows": 500_000,
                "total_bytes": 67_000_000,
                "category": "large",
            },
        },
        "stats": {},
    }


@pytest.fixture
def snapshot_tags_tabla_pequena() -> dict[str, Any]:
    """Caso negativo C1: tabla pequeña (6k filas). El plan fixture
    02_aggregate_seq_scan.json hace Seq Scan sobre `tags` con
    `Filter: ((name)::text ~~ 'a%'::text)`. Como la tabla es
    pequeña, C1 NO debe disparar aunque haya un Seq Scan."""
    return {
        "schema": {
            "public.tags": {
                "schema": "public",
                "name": "tags",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "ordinal_position": 1,
                    },
                    {
                        "name": "name",
                        "data_type": "varchar(50)",
                        "is_nullable": False,
                        "ordinal_position": 2,
                    },
                ],
                "indexes": [
                    {
                        "name": "tags_pkey",
                        "columns": ["id"],
                        "method": "btree",
                        "is_unique": True,
                        "is_primary": True,
                    },
                    {
                        "name": "idx_tags_name",
                        "columns": ["name"],
                        "method": "btree",
                        "is_unique": False,
                        "is_primary": False,
                    },
                ],
                "foreign_keys": [],
            },
        },
        "sizes": {
            "public.tags": {
                "estimated_rows": 6_000,
                "total_bytes": 500_000,
                "category": "small",
            },
        },
        "stats": {},
    }


@pytest.fixture
def snapshot_posts_sin_indice_en_author_id() -> dict[str, Any]:
    """Caso negativo C1 (escenario distinto): tabla grande PERO sin
    índice en la columna del filtro. Esto es Q01 puro de AppDB —
    NO es C1 (es "falta de índice", lo atiende C2). C1 debe
    devolver found=False aquí."""
    return {
        "schema": {
            "public.posts": {
                "schema": "public",
                "name": "posts",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "bigint",
                        "is_nullable": False,
                        "ordinal_position": 1,
                    },
                    {
                        "name": "author_id",
                        "data_type": "integer",
                        "is_nullable": False,
                        "ordinal_position": 2,
                    },
                ],
                "indexes": [
                    {
                        "name": "posts_pkey",
                        "columns": ["id"],
                        "method": "btree",
                        "is_unique": True,
                        "is_primary": True,
                    },
                ],
                "foreign_keys": [],
            },
        },
        "sizes": {
            "public.posts": {
                "estimated_rows": 500_000,
                "total_bytes": 67_000_000,
                "category": "large",
            },
        },
        "stats": {},
    }

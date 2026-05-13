"""Tests del detector D21 — NOT IN con subquery sobre columna nullable.

Criterio del backlog:
  Hecho cuando: test verde para Q19 (`WHERE id NOT IN (SELECT
  author_id FROM posts)`). Detección incluye explicación de la trampa
  de NULL en `evidence`.
"""

from __future__ import annotations

from typing import Any

import sqlglot

from motor import parse_explain
from motor.detectors.not_in_nullable_subquery import (
    detect_not_in_nullable_subquery,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan_irrelevante() -> dict:
    """D21 no usa el plan. Devolvemos un Seq Scan trivial."""
    return {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 100,
            "Plan Width": 8,
        }
    }


def _snapshot_posts_author_id_nullable() -> dict[str, Any]:
    """Snapshot mínimo: posts.author_id es NULLABLE (caso Q19)."""
    return {
        "schema": {
            "public.posts": {
                "schema": "public",
                "name": "posts",
                "columns": [
                    {"name": "id", "data_type": "bigint", "is_nullable": False},
                    {"name": "author_id", "data_type": "integer", "is_nullable": True},
                ],
                "indexes": [],
                "foreign_keys": [],
            },
            "public.users": {
                "schema": "public",
                "name": "users",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_nullable": False},
                ],
                "indexes": [],
                "foreign_keys": [],
            },
        },
        "sizes": {},
        "stats": {},
    }


def _snapshot_posts_author_id_not_null() -> dict[str, Any]:
    """Snapshot donde posts.author_id es NOT NULL — D21 NO debe disparar."""
    snap = _snapshot_posts_author_id_nullable()
    snap["schema"]["public.posts"]["columns"][1]["is_nullable"] = False
    return snap


# ---------------------------------------------------------------------------
# Happy path — Q19
# ---------------------------------------------------------------------------


def test_dispara_q19_not_in_sobre_columna_nullable() -> None:
    """Q19: `WHERE id NOT IN (SELECT author_id FROM posts)` con
    author_id nullable → D21 debe disparar con confianza 0.95 y
    `null_trap=True`."""
    sql = "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is True
    assert detection.confidence == 0.95
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    m = matches[0]
    assert m["column"] == "id"
    assert m["inner_table"] == "posts"
    assert m["inner_column"] == "author_id"
    assert m["inner_is_nullable"] is True
    assert m["null_trap"] is True


def test_rewrite_q19_es_parseable_y_usa_not_exists() -> None:
    """El suggested_rewrite es SQL válido con NOT EXISTS correlacionado."""
    sql = "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)
    rewrite = detection.evidence["matches"][0]["suggested_rewrite"]

    parsed = sqlglot.parse_one(rewrite, dialect="postgres")
    assert parsed is not None

    upper = rewrite.upper()
    assert "NOT EXISTS" in upper
    # No debe sobrevivir el patrón NOT IN
    assert "NOT IN" not in upper


def test_dispara_q19_con_limit() -> None:
    """Q19 real incluye LIMIT — el LIMIT no afecta la detección."""
    sql = (
        "SELECT id FROM users "
        "WHERE id NOT IN (SELECT author_id FROM posts) "
        "LIMIT 10"
    )
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is True


# ---------------------------------------------------------------------------
# Negativos
# ---------------------------------------------------------------------------


def test_no_dispara_si_columna_interna_es_not_null() -> None:
    """Si posts.author_id es NOT NULL no hay trampa NULL. D21 se abstiene."""
    sql = "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_not_null()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_in_sin_not() -> None:
    """`IN (SELECT ...)` lo cubre D20, no D21."""
    sql = "SELECT id FROM users WHERE id IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is False


def test_no_dispara_not_in_con_lista_literal() -> None:
    """`NOT IN (1, 2, 3)` no es subquery — abstención."""
    sql = "SELECT id FROM users WHERE id NOT IN (1, 2, 3)"
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is False


def test_no_dispara_subquery_correlacionada() -> None:
    """NOT IN con subquery correlacionada → territorio de D7."""
    sql = (
        "SELECT id FROM users "
        "WHERE id NOT IN ("
        "SELECT author_id FROM posts WHERE posts.id = users.id"
        ")"
    )
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is False


def test_no_dispara_sin_sql() -> None:
    """Sin SQL D21 se abstiene silenciosamente."""
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sql_invalido() -> None:
    """SQL no parseable → abstención silenciosa, sin levantar."""
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(
        plan, snapshot, sql="NOT VALID SQL !!!"
    )

    assert detection.found is False


def test_no_dispara_con_snapshot_vacio() -> None:
    """Sin info de schema no podemos verificar nullability → abstención."""
    sql = "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_irrelevante())

    detection = detect_not_in_nullable_subquery(plan, {}, sql=sql)

    assert detection.found is False


def test_no_dispara_si_tabla_interna_desconocida() -> None:
    """Subquery sobre una tabla que no está en el snapshot → abstención."""
    sql = (
        "SELECT id FROM users "
        "WHERE id NOT IN (SELECT some_col FROM tabla_fantasma)"
    )
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is False


def test_no_dispara_si_proyeccion_no_es_columna_simple() -> None:
    """`NOT IN (SELECT COALESCE(author_id, 0) FROM posts)` — la proyección
    es una expresión, no podemos razonar sobre nullability estructural."""
    sql = (
        "SELECT id FROM users "
        "WHERE id NOT IN (SELECT COALESCE(author_id, 0) FROM posts)"
    )
    plan = parse_explain(_plan_irrelevante())
    snapshot = _snapshot_posts_author_id_nullable()

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is False


# ---------------------------------------------------------------------------
# Frontera y robustez
# ---------------------------------------------------------------------------


def test_resuelve_tabla_aunque_snapshot_use_otro_schema_solo() -> None:
    """Si el snapshot solo tiene `analytics.posts` (no `public.posts`),
    D21 resuelve por nombre corto. La columna sigue siendo nullable."""
    sql = "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts)"
    plan = parse_explain(_plan_irrelevante())
    snapshot: dict[str, Any] = {
        "schema": {
            "analytics.posts": {
                "schema": "analytics",
                "name": "posts",
                "columns": [
                    {"name": "author_id", "data_type": "integer", "is_nullable": True},
                ],
                "indexes": [],
                "foreign_keys": [],
            }
        },
        "sizes": {},
        "stats": {},
    }

    detection = detect_not_in_nullable_subquery(plan, snapshot, sql=sql)

    assert detection.found is True
    assert detection.evidence["matches"][0]["inner_table"] == "posts"
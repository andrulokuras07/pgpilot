"""Tests del detector D19 — HAVING que debería ser WHERE.

Criterio del backlog:
  Hecho cuando: test verde para Q16
  (`GROUP BY author_id HAVING author_id = $1`).
  Rewrite propuesto válido (parseable con sqlglot).
"""

from __future__ import annotations

import sqlglot

from motor import parse_explain
from motor.detectors.having_without_aggregate import detect_having_without_aggregate


# ---------------------------------------------------------------------------
# Helpers de plan (el detector no usa el plan, pero la firma lo requiere)
# ---------------------------------------------------------------------------

def _plan_aggregate() -> dict:
    """Plan sintético con un Aggregate para Q16."""
    return {
        "Plan": {
            "Node Type": "Aggregate",
            "Strategy": "Hashed",
            "Startup Cost": 0.0,
            "Total Cost": 9000.0,
            "Plan Rows": 1,
            "Plan Width": 12,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 8000.0,
                    "Plan Rows": 500000,
                    "Plan Width": 4,
                }
            ],
        }
    }


def _plan_seq_scan() -> dict:
    return {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 100,
            "Plan Width": 4,
        }
    }


# ---------------------------------------------------------------------------
# Happy path — Q16
# ---------------------------------------------------------------------------


def test_dispara_q16_having_author_id() -> None:
    """Q16: HAVING author_id = $1 donde author_id está en GROUP BY.
    El filtro puede moverse a WHERE — D19 debe disparar."""
    sql = "SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 1000"
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {}, sql=sql)

    assert detection.found is True
    assert detection.confidence == 0.9
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    m = matches[0]
    assert m["from_table"] == "posts"
    assert "author_id" in m["group_by_cols"]
    assert "author_id" in m["having_expr"]


def test_rewrite_q16_es_parseable_y_tiene_where() -> None:
    """El suggested_rewrite de Q16 es SQL válido y tiene WHERE en lugar de HAVING."""
    sql = "SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 1000"
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {}, sql=sql)

    assert detection.found is True
    rewrite = detection.evidence["matches"][0]["suggested_rewrite"]

    # Debe ser parseable
    parsed = sqlglot.parse_one(rewrite, dialect="postgres")
    assert parsed is not None

    # No debe tener HAVING
    assert parsed.args.get("having") is None

    # Debe tener WHERE con la condición del HAVING original
    where = parsed.args.get("where")
    assert where is not None
    assert "1000" in rewrite or "author_id" in rewrite


def test_rewrite_preserva_group_by() -> None:
    """El rewrite conserva el GROUP BY y el SELECT original."""
    sql = "SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 1000"
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {}, sql=sql)

    rewrite = detection.evidence["matches"][0]["suggested_rewrite"]
    parsed = sqlglot.parse_one(rewrite, dialect="postgres")

    # GROUP BY debe permanecer
    assert parsed.args.get("group") is not None


# ---------------------------------------------------------------------------
# Negativos — no debe disparar
# ---------------------------------------------------------------------------


def test_no_dispara_sin_sql() -> None:
    """Sin SQL el detector se abstiene (no lanza)."""
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_having() -> None:
    """SELECT con GROUP BY pero sin HAVING no dispara."""
    sql = "SELECT author_id, count(*) FROM posts GROUP BY author_id"
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {}, sql=sql)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_having_con_agregado() -> None:
    """HAVING count(*) > 5 contiene función agregada → no movible a WHERE."""
    sql = "SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING count(*) > 5"
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {}, sql=sql)

    assert detection.found is False


def test_no_dispara_having_con_suma() -> None:
    """HAVING sum(likes) > 100 contiene función agregada → no movible."""
    sql = "SELECT author_id, sum(likes_count) FROM posts GROUP BY author_id HAVING sum(likes_count) > 100"
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {}, sql=sql)

    assert detection.found is False


def test_no_dispara_sql_invalido() -> None:
    """SQL que no parsea → abstención silenciosa."""
    plan = parse_explain(_plan_seq_scan())
    detection = detect_having_without_aggregate(plan, {}, sql="NOT VALID SQL !!!")

    assert detection.found is False


def test_no_dispara_sin_group_by() -> None:
    """HAVING sin GROUP BY es SQL raro; el detector requiere GROUP BY."""
    # HAVING sin GROUP BY (SQL posiblemente inválido según dialect, pero testeamos robustez)
    sql = "SELECT count(*) FROM posts HAVING count(*) > 5"
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {}, sql=sql)

    # Puede no disparar porque no hay GROUP BY → group_cols está vacío
    assert detection.found is False


# ---------------------------------------------------------------------------
# Caso con WHERE existente — el HAVING se añade al WHERE con AND
# ---------------------------------------------------------------------------


def test_rewrite_preserva_where_existente() -> None:
    """Si el SELECT ya tiene WHERE, el rewrite lo conserva con AND."""
    sql = (
        "SELECT author_id, count(*) FROM posts "
        "WHERE is_deleted = false "
        "GROUP BY author_id HAVING author_id = 1000"
    )
    plan = parse_explain(_plan_aggregate())
    detection = detect_having_without_aggregate(plan, {}, sql=sql)

    assert detection.found is True
    rewrite = detection.evidence["matches"][0]["suggested_rewrite"]
    parsed = sqlglot.parse_one(rewrite, dialect="postgres")

    # Debe tener WHERE y no HAVING
    assert parsed.args.get("where") is not None
    assert parsed.args.get("having") is None
    # El WHERE debe contener ambas condiciones
    where_sql = parsed.args["where"].sql(dialect="postgres")
    assert "is_deleted" in where_sql or "deleted" in where_sql.lower()
    assert "author_id" in where_sql


# ---------------------------------------------------------------------------
# Frontera con otros detectores
# ---------------------------------------------------------------------------


def test_no_dispara_sobre_select_sin_tablas() -> None:
    """SELECT sin FROM: el detector devuelve found=False (sin tabla implicada)."""
    sql = "SELECT 1 GROUP BY 1 HAVING 1 = 1"
    plan = parse_explain(_plan_seq_scan())
    # group_cols estarán vacíos (1 no es exp.Column) → no dispara
    detection = detect_having_without_aggregate(plan, {}, sql=sql)
    assert detection.found is False

"""Tests del detector D9 — SELECT * con índice cubriente disponible.

Criterio del backlog:
  Hecho cuando: detector pasa test, documentado.
"""

from __future__ import annotations

from motor import detect_select_star, parse_explain


_SIMPLE_INDEX_SCAN_PLAN = {
    "Plan": {
        "Node Type": "Index Scan",
        "Relation Name": "users",
        "Index Name": "idx_users_email",
        "Startup Cost": 0.0,
        "Total Cost": 8.5,
        "Plan Rows": 1,
        "Plan Width": 200,
        "Index Cond": "(email = 'x'::text)",
    }
}


def test_dispara_con_select_star_simple() -> None:
    """`SELECT * FROM users WHERE email = $1` → dispara."""
    sql = "SELECT * FROM users WHERE email = $LITERAL_1_0"
    plan = parse_explain(_SIMPLE_INDEX_SCAN_PLAN)
    detection = detect_select_star(plan, {}, sql=sql)

    assert detection.found is True
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    assert matches[0]["index_only_candidate"] is True
    assert matches[0]["table"] == "users"


def test_dispara_con_table_dot_star() -> None:
    """`SELECT u.* FROM users u` → también dispara."""
    sql = "SELECT u.* FROM users u WHERE u.email = $LITERAL_1_0"
    plan = parse_explain(_SIMPLE_INDEX_SCAN_PLAN)
    detection = detect_select_star(plan, {}, sql=sql)

    assert detection.found is True


def test_no_dispara_con_columnas_explicitas() -> None:
    """`SELECT id, email FROM users` → no dispara."""
    sql = "SELECT id, email FROM users WHERE email = $LITERAL_1_0"
    plan = parse_explain(_SIMPLE_INDEX_SCAN_PLAN)
    detection = detect_select_star(plan, {}, sql=sql)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_sql() -> None:
    """Sin SQL no hay forma estructural de detectar `*` — se abstiene."""
    plan = parse_explain(_SIMPLE_INDEX_SCAN_PLAN)
    detection = detect_select_star(plan, {}, sql=None)

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_levanta_con_sql_no_parseable() -> None:
    """SQL inválido → Detection found=False, no excepción."""
    sql = "esto no es SQL ;;;"
    plan = parse_explain(_SIMPLE_INDEX_SCAN_PLAN)
    detection = detect_select_star(plan, {}, sql=sql)

    assert detection.found is False


def test_dispara_solo_en_select_anidado_con_star() -> None:
    """Outer con columnas explícitas, inner con `*` → dispara una vez."""
    sql = (
        "SELECT id FROM (SELECT * FROM users WHERE email = $LITERAL_1_0) sub"
    )
    plan = parse_explain(_SIMPLE_INDEX_SCAN_PLAN)
    detection = detect_select_star(plan, {}, sql=sql)

    assert detection.found is True
    assert len(detection.evidence["matches"]) == 1


def test_index_only_candidate_false_sin_index_scan() -> None:
    """Si el plan es Seq Scan, no hay oportunidad de Index Only."""
    sql = "SELECT * FROM users WHERE name = $LITERAL_1_0"
    plan = parse_explain(
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "users",
                "Startup Cost": 0.0,
                "Total Cost": 500.0,
                "Plan Rows": 1,
                "Plan Width": 200,
                "Filter": "(name = 'x'::text)",
            }
        }
    )
    detection = detect_select_star(plan, {}, sql=sql)

    assert detection.found is True
    assert detection.evidence["matches"][0]["index_only_candidate"] is False

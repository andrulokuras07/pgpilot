"""Tests del detector D4 — LIKE con wildcard al inicio.

Criterio del backlog:
  Hecho cuando: detector pasa test sobre plan plantado, documentado
  en patterns.
"""

from __future__ import annotations

from typing import Any

from motor import detect_like_leading_wildcard, parse_explain


def test_dispara_con_like_wildcard_al_inicio() -> None:
    """Filtro `(name)::text ~~ '%abc'::text` — wildcard al inicio."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "tags",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 100,
            "Plan Width": 10,
            "Filter": "((name)::text ~~ '%abc'::text)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_like_leading_wildcard(plan, {})

    assert detection.found is True
    matches = detection.evidence["matches"]
    assert len(matches) == 1
    assert matches[0]["column"] == "name"
    assert matches[0]["table"] == "tags"


def test_no_dispara_con_like_sin_wildcard_al_inicio() -> None:
    """Filtro `name ~~ 'abc%'` — wildcard al final, índice btree sirve."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "tags",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 100,
            "Plan Width": 10,
            "Filter": "((name)::text ~~ 'abc%'::text)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_like_leading_wildcard(plan, {})

    assert detection.found is False
    assert detection.evidence == {"matches": []}


def test_no_dispara_sin_filtro() -> None:
    """Nodo sin filtro — nada que detectar."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "tags",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 100,
            "Plan Width": 10,
        }
    }
    plan = parse_explain(raw)
    detection = detect_like_leading_wildcard(plan, {})
    assert detection.found is False


def test_dispara_en_bitmap_heap_scan() -> None:
    """El wildcard puede aparecer como recheck_cond en Bitmap Heap Scan."""
    raw = {
        "Plan": {
            "Node Type": "Bitmap Heap Scan",
            "Relation Name": "users",
            "Startup Cost": 0.0,
            "Total Cost": 50.0,
            "Plan Rows": 10,
            "Plan Width": 10,
            "Recheck Cond": "((email)::text ~~ '%@gmail.com'::text)",
        }
    }
    plan = parse_explain(raw)
    detection = detect_like_leading_wildcard(plan, {})

    assert detection.found is True
    assert detection.evidence["matches"][0]["column"] == "email"


def test_multiples_likes_en_un_plan() -> None:
    """Dos nodos con LIKE wildcard al inicio."""
    raw = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 1,
            "Plan Width": 1,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 1,
                    "Plan Width": 1,
                    "Filter": "((name)::text ~~ '%john'::text)",
                },
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 50.0,
                    "Plan Rows": 1,
                    "Plan Width": 1,
                    "Filter": "((title)::text ~~ '%urgent'::text)",
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_like_leading_wildcard(plan, {})

    assert detection.found is True
    assert len(detection.evidence["matches"]) == 2

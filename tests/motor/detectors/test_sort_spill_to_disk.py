"""Tests del detector D3 — Sort en disco.
 
Criterio del backlog:
    Hecho cuando: detector pasa test, documentado.
 
Cubre:
- Happy path: `Sort Space Type: Disk` con `external merge` → dispara.
- Variante: solo `Sort Method` menciona `external merge` (fallback) → dispara.
- Negativo: `Sort Space Type: Memory` → no dispara.
- Negativo: plan sin nodos Sort → no dispara.
- Robustez: sort_key None, sort_key con expresión funcional,
  sort_space_used ausente.
- Plurales: dos sorts en disco en el mismo plan.
"""
 
from __future__ import annotations
 
from typing import Any
 
import pytest
 
from motor import detect_sort_spill_to_disk, parse_explain
 
_EMPTY_SNAPSHOT: dict[str, Any] = {"schema": {}, "sizes": {}, "stats": {}}
 
 
# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
 
 
def test_dispara_con_sort_space_type_disk() -> None:
    """Sort que desbordó: campo authoritativo `Sort Space Type=Disk`."""
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 1000.0,
            "Total Cost": 1100.0,
            "Plan Rows": 200_000,
            "Plan Width": 50,
            "Actual Rows": 200_000,
            "Actual Loops": 1,
            "Sort Key": ["public.posts.created_at DESC"],
            "Sort Method": "external merge",
            "Sort Space Type": "Disk",
            "Sort Space Used": 24576,  # 24 MB
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "posts",
                    "Startup Cost": 0.0,
                    "Total Cost": 800.0,
                    "Plan Rows": 200_000,
                    "Plan Width": 50,
                    "Actual Rows": 200_000,
                    "Actual Loops": 1,
                }
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
 
    assert detection.found is True
    assert detection.confidence == pytest.approx(0.95)
    match = detection.evidence["matches"][0]
    assert match["sort_space_type"] == "Disk"
    assert match["sort_method"] == "external merge"
    assert match["sort_space_used_kb"] == 24576
    assert match["sort_key"] == ["public.posts.created_at DESC"]
    # Sugerencia de work_mem ≈ 2x lo usado, redondeado al MB siguiente:
    # 24576 KB usados → 49152 KB → 48 MB
    assert match["suggested_set_work_mem_sql"] == "SET work_mem = '48MB';"
    # Sugerencia de índice sobre primera columna del sort_key
    assert match["suggested_create_index_sql"] == (
        "CREATE INDEX idx_posts_created_at "
        "ON public.posts (created_at);"
    )
 
 
def test_dispara_con_sort_method_external_aunque_space_type_falte() -> None:
    """Fallback defensivo: si por alguna razón Postgres no emite
    `Sort Space Type` pero el método dice `external merge`, igual
    contamos como spill."""
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 500.0,
            "Total Cost": 600.0,
            "Plan Rows": 100_000,
            "Plan Width": 20,
            "Actual Rows": 100_000,
            "Actual Loops": 1,
            "Sort Key": ["name"],
            "Sort Method": "external merge Disk",
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
    assert detection.found is True
 
 
def test_sort_key_con_tabla_columna_emite_create_index() -> None:
    """`Sort Key: ['users.email']` → `CREATE INDEX idx_users_email`."""
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 100.0,
            "Total Cost": 200.0,
            "Plan Rows": 50_000,
            "Plan Width": 30,
            "Actual Rows": 50_000,
            "Actual Loops": 1,
            "Sort Key": ["users.email"],
            "Sort Method": "external merge",
            "Sort Space Type": "Disk",
            "Sort Space Used": 4096,
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
 
    match = detection.evidence["matches"][0]
    assert match["suggested_create_index_sql"] == (
        "CREATE INDEX idx_users_email ON users (email);"
    )
 
 
# ---------------------------------------------------------------------------
# Casos negativos
# ---------------------------------------------------------------------------
 
 
def test_no_dispara_con_sort_en_memoria() -> None:
    """Sort que cupo en work_mem — comportamiento sano."""
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 50.0,
            "Total Cost": 60.0,
            "Plan Rows": 100,
            "Plan Width": 20,
            "Actual Rows": 100,
            "Actual Loops": 1,
            "Sort Key": ["id"],
            "Sort Method": "quicksort",
            "Sort Space Type": "Memory",
            "Sort Space Used": 32,
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
 
    assert detection.found is False
    assert detection.evidence == {"matches": []}
 
 
def test_no_dispara_sin_nodos_sort() -> None:
    """Plan sin Sort — nada que verificar."""
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 100,
            "Plan Width": 20,
            "Actual Rows": 100,
            "Actual Loops": 1,
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
    assert detection.found is False
 
 
def test_no_dispara_si_sort_method_no_es_external() -> None:
    """`Sort Method: top-N heapsort` — sort en memoria que cupo."""
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 50.0,
            "Total Cost": 60.0,
            "Plan Rows": 10,
            "Plan Width": 20,
            "Actual Rows": 10,
            "Actual Loops": 1,
            "Sort Key": ["created_at DESC"],
            "Sort Method": "top-N heapsort",
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
    assert detection.found is False
 
 
# ---------------------------------------------------------------------------
# Robustez de la sugerencia de índice
# ---------------------------------------------------------------------------
 
 
def test_sort_key_es_expresion_no_emite_create_index() -> None:
    """`Sort Key: ['lower(name)']` — expresión funcional, no inventamos
    SQL: el índice funcional es decisión del recomendador con más
    contexto. R14: no hardcodear formato que no podemos garantizar."""
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 100.0,
            "Total Cost": 200.0,
            "Plan Rows": 80_000,
            "Plan Width": 40,
            "Actual Rows": 80_000,
            "Actual Loops": 1,
            "Sort Key": ["lower(name)"],
            "Sort Method": "external merge",
            "Sort Space Type": "Disk",
            "Sort Space Used": 8192,
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
 
    assert detection.found is True
    match = detection.evidence["matches"][0]
    assert match["suggested_create_index_sql"] is None
 
 
def test_sort_sin_sort_key_no_emite_create_index() -> None:
    """Caso degenerado: Sort node parseado sin Sort Key. No crashea."""
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 100.0,
            "Total Cost": 200.0,
            "Plan Rows": 80_000,
            "Plan Width": 40,
            "Actual Rows": 80_000,
            "Actual Loops": 1,
            "Sort Method": "external merge",
            "Sort Space Type": "Disk",
            "Sort Space Used": 8192,
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
 
    assert detection.found is True
    match = detection.evidence["matches"][0]
    assert match["sort_key"] == []
    assert match["suggested_create_index_sql"] is None
 
 
def test_sort_sin_sort_space_used_emite_work_mem_default() -> None:
    """Sin `Sort Space Used` no podemos dimensionar — sugerimos 64MB
    como punto de partida razonable."""
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Startup Cost": 100.0,
            "Total Cost": 200.0,
            "Plan Rows": 80_000,
            "Plan Width": 40,
            "Actual Rows": 80_000,
            "Actual Loops": 1,
            "Sort Key": ["id"],
            "Sort Method": "external merge",
            "Sort Space Type": "Disk",
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
    match = detection.evidence["matches"][0]
    assert match["suggested_set_work_mem_sql"] == "SET work_mem = '64MB';"
 
 
# ---------------------------------------------------------------------------
# Plurales
# ---------------------------------------------------------------------------
 
 
def test_dos_sorts_en_disco_se_reportan_ambos() -> None:
    """Plan con dos Sort, uno arriba de cada rama de un Merge Join.
    Ejercita la convención `evidence['matches']` en plural."""
    raw = {
        "Plan": {
            "Node Type": "Merge Join",
            "Startup Cost": 200.0,
            "Total Cost": 500.0,
            "Plan Rows": 100_000,
            "Plan Width": 80,
            "Actual Rows": 100_000,
            "Actual Loops": 1,
            "Plans": [
                {
                    "Node Type": "Sort",
                    "Parent Relationship": "Outer",
                    "Startup Cost": 100.0,
                    "Total Cost": 110.0,
                    "Plan Rows": 100_000,
                    "Plan Width": 40,
                    "Actual Rows": 100_000,
                    "Actual Loops": 1,
                    "Sort Key": ["posts.id"],
                    "Sort Method": "external merge",
                    "Sort Space Type": "Disk",
                    "Sort Space Used": 4096,
                },
                {
                    "Node Type": "Sort",
                    "Parent Relationship": "Inner",
                    "Startup Cost": 90.0,
                    "Total Cost": 100.0,
                    "Plan Rows": 100_000,
                    "Plan Width": 40,
                    "Actual Rows": 100_000,
                    "Actual Loops": 1,
                    "Sort Key": ["comments.post_id"],
                    "Sort Method": "external merge",
                    "Sort Space Type": "Disk",
                    "Sort Space Used": 2048,
                },
            ],
        }
    }
    plan = parse_explain(raw)
    detection = detect_sort_spill_to_disk(plan, _EMPTY_SNAPSHOT)
 
    assert detection.found is True
    keys = {tuple(m["sort_key"]) for m in detection.evidence["matches"]}
    assert keys == {("posts.id",), ("comments.post_id",)}
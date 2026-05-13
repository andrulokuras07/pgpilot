"""Tests del scoring de workload — E2."""

from __future__ import annotations

from workload.parser import StatementEntry
from workload.scoring import score_workload


def _entry(query: str, total_time: float, calls: int = 1) -> StatementEntry:
    return StatementEntry(
        query=query,
        calls=calls,
        total_exec_time=total_time,
        mean_exec_time=total_time / max(calls, 1),
        rows=calls,
    )


def test_top_10_ordenado_por_total_exec_time() -> None:
    entries = [_entry(f"Q{i}", total_time=float(i)) for i in range(20)]
    scored = score_workload(entries, top_n=10)
    assert len(scored) == 10
    assert scored[0].query == "Q19"
    assert scored[9].query == "Q10"


def test_score_normalizado_al_maximo() -> None:
    entries = [
        _entry("big", 1000.0),
        _entry("half", 500.0),
        _entry("small", 100.0),
    ]
    scored = score_workload(entries)
    assert scored[0].score == 1.0
    assert scored[1].score == 0.5
    assert scored[2].score == 0.1


def test_rank_empieza_en_1() -> None:
    entries = [_entry("Q1", 100.0), _entry("Q2", 50.0)]
    scored = score_workload(entries)
    assert scored[0].rank == 1
    assert scored[1].rank == 2


def test_lista_vacia() -> None:
    assert score_workload([]) == []


def test_frecuencia_no_domina_sobre_tiempo() -> None:
    """E2: query lenta total pesa más que query frecuente pero rápida."""
    slow = _entry("slow", total_time=50000.0, calls=10)
    fast = _entry("fast", total_time=10000.0, calls=100000)
    scored = score_workload([slow, fast])
    assert scored[0].query == "slow"

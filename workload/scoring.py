"""Score de impacto para queries de pg_stat_statements.

E2 del backlog: ordena por total_exec_time descendente (no por
frecuencia). Una query que tarda mucho en total duele más que una
que se ejecuta muchas veces pero es rápida.
"""

from __future__ import annotations

from dataclasses import dataclass

from workload.parser import StatementEntry


@dataclass(frozen=True)
class ScoredEntry:
    query: str
    calls: int
    total_exec_time: float
    mean_exec_time: float
    rows: int
    score: float
    rank: int


def score_workload(
    entries: list[StatementEntry],
    *,
    top_n: int = 10,
) -> list[ScoredEntry]:
    """Calcula score y devuelve top N queries por impacto.

    El score es el total_exec_time normalizado al máximo (0..1).
    Si el máximo es 0, todos tienen score 0.
    """
    if not entries:
        return []

    sorted_entries = sorted(entries, key=lambda e: e.total_exec_time, reverse=True)
    top = sorted_entries[:top_n]

    max_time = top[0].total_exec_time if top else 0.0

    result = []
    for rank_idx, entry in enumerate(top, start=1):
        score = entry.total_exec_time / max_time if max_time > 0 else 0.0
        result.append(
            ScoredEntry(
                query=entry.query,
                calls=entry.calls,
                total_exec_time=entry.total_exec_time,
                mean_exec_time=entry.mean_exec_time,
                rows=entry.rows,
                score=round(score, 4),
                rank=rank_idx,
            )
        )

    return result

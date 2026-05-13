"""Mide cobertura real de todos los detectores registrados en el motor
contra las 20 queries plantadas en AppDB v1.

Hermano de `measure_c1_coverage.py` — reutiliza el catálogo `PLANTED` y
añade D4..D7. Reporta:

1. Por query: qué detector(es) dispararon.
2. Conteo global de queries con al menos una detección.
3. Detalle de matches por detector para evidenciar en PROGRESS.md.

NOTA: este script NO etiqueta `target` por detector (eso requeriría
triage por query para los 4 detectores nuevos). La métrica que entrega
es la honesta para Demo Day: "tras C1+D4-D7, ¿cuántas de las 20 quedan
cubiertas?". El triage de FP se hace manualmente comparando contra el
`triage_reason` documentado en `measure_c1_coverage.py`.

Uso:
    docker compose up appdb -d
    python -m scripts.measure_coverage

Variables de entorno: idénticas a measure_c1_coverage.py.
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conector import ConnectionConfig, create_pool, extract_snapshot  # noqa: E402
from motor import (  # noqa: E402
    Detection,
    detect_cardinality_misestimate,
    detect_correlated_subquery,
    detect_count_star_full_table,
    detect_function_in_where,
    detect_having_without_aggregate,
    detect_in_subquery_to_exists,
    detect_like_leading_wildcard,
    detect_missing_covering_index,
    detect_missing_index,
    detect_nested_loop_large_outer,
    detect_or_across_tables,
    detect_partial_index_opportunity,
    detect_select_star,
    detect_seq_scan_on_large_table,
    detect_sort_spill_to_disk,
    detect_stale_statistics,
    detect_type_mismatch,
    detect_unnecessary_cte_materialize,
    parse_explain,
)
from scripts.measure_c1_coverage import PLANTED, PlantedQuery  # noqa: E402

DETECTORS: tuple[tuple[str, Callable[..., Detection]], ...] = (
    ("C1", detect_seq_scan_on_large_table),
    ("D2", detect_stale_statistics),
    ("D3", detect_sort_spill_to_disk),
    ("D4", detect_like_leading_wildcard),
    ("D5", detect_function_in_where),
    ("D6", detect_or_across_tables),
    ("D7", detect_correlated_subquery),
    ("D8", detect_nested_loop_large_outer),
    ("D9", detect_select_star),
    ("D10", detect_missing_covering_index),
    ("D11", detect_type_mismatch),
    ("D12", detect_unnecessary_cte_materialize),
    ("D16", detect_missing_index),
    ("D17", detect_partial_index_opportunity),
    ("D18", detect_cardinality_misestimate),
    ("D19", detect_having_without_aggregate),
    ("D20", detect_in_subquery_to_exists),
    ("D22", detect_count_star_full_table),
)


def _get_pool():
    config = ConnectionConfig(
        host=os.environ.get("APPDB_HOST", "localhost"),
        port=int(os.environ.get("APPDB_PORT", "5434")),
        dbname=os.environ.get("APPDB_DB", "appdb"),
        user=os.environ.get("APPDB_USER", "app_user"),
        password=os.environ.get("APPDB_PASSWORD", "app_pass"),
    )
    return create_pool(config)


def _explain(pool, sql: str) -> Any:
    try:
        with pool.connection() as conn:
            cur = conn.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:  # noqa: BLE001
        return {"__error__": str(exc)}


def _run_all(plan: Any, snapshot: Any, sql: str) -> dict[str, Detection]:
    """Llama cada detector pasándole `sql` por kwarg cuando lo acepta.

    Convención: detectores con firma extendida `(plan, snapshot, *, sql=None)`
    (D9, D11) reciben el SQL plantado para poder operar; el resto se llama
    con la firma estándar `(plan, snapshot)`.
    """
    out: dict[str, Detection] = {}
    for code, fn in DETECTORS:
        params = inspect.signature(fn).parameters
        if "sql" in params:
            out[code] = fn(plan, snapshot, sql=sql)
        else:
            out[code] = fn(plan, snapshot)
    return out


def main() -> int:
    codes = "+".join(code for code, _ in DETECTORS)
    print(f"# Cobertura agregada — {codes} contra AppDB v1\n")
    print("Conectando a AppDB...")
    pool = _get_pool()
    try:
        print("Extrayendo snapshot del schema...")
        snapshot = extract_snapshot(pool)
        big = sum(1 for t in snapshot["sizes"].values() if t.get("estimated_rows", 0) >= 100_000)
        print(f"  {len(snapshot['schema'])} tablas, " f"{big} con ≥100k filas estimadas\n")

        results: list[tuple[PlantedQuery, dict[str, Any]]] = []
        for q in PLANTED:
            raw = _explain(pool, q.sql)
            if isinstance(raw, dict) and "__error__" in raw:
                results.append((q, {"status": "ERROR", "msg": raw["__error__"]}))
                continue
            try:
                plan = parse_explain(raw)
            except Exception as exc:  # noqa: BLE001
                results.append((q, {"status": "PARSE_FAIL", "msg": str(exc)}))
                continue
            detections = _run_all(plan, snapshot, q.sql)
            results.append(
                (
                    q,
                    {
                        "status": "OK",
                        "top": plan.root.node_type,
                        "detections": detections,
                    },
                )
            )

        # Tabla principal
        print("## Resultados por query\n")
        detector_headers = " | ".join(code for code, _ in DETECTORS)
        header = f"| Q | Anti-pattern | Top node | {detector_headers} | Cubierta |"
        sep = "|" + "---|" * (3 + len(DETECTORS) + 1)
        print(header)
        print(sep)

        covered = 0
        per_detector = {code: 0 for code, _ in DETECTORS}
        errors = 0

        def _mark(d: Detection) -> str:
            return "✅" if d.found else "—"

        for q, r in results:
            if r["status"] != "OK":
                errors += 1
                msg = r.get("msg", "")[:60]
                empty_cols = " | ".join(["—"] * len(DETECTORS))
                print(
                    f"| {q.qid} | {q.antipattern} | " f"`{r['status']}: {msg}` | {empty_cols} | — |"
                )
                continue

            ds = r["detections"]
            any_found = any(ds[c].found for c, _ in DETECTORS)
            if any_found:
                covered += 1
            for code, _ in DETECTORS:
                if ds[code].found:
                    per_detector[code] += 1

            marks = " | ".join(_mark(ds[code]) for code, _ in DETECTORS)
            print(
                f"| {q.qid} | {q.antipattern} | `{r['top']}` | "
                f"{marks} | "
                f"{'**SÍ**' if any_found else '—'} |"
            )

        # Resumen
        print("\n## Resumen\n")
        print(f"- Total queries probadas: **{len(PLANTED)}**")
        print(f"- Queries cubiertas por al menos un detector: **{covered}/20**")
        print(f"- Errores de ejecución: **{errors}**")
        print()
        print("### Detecciones por detector")
        for code, _ in DETECTORS:
            print(f"- **{code}** disparó en: **{per_detector[code]}** queries")

        detector_codes = "+".join(code for code, _ in DETECTORS)
        print(
            f"\n**Cobertura GLOBAL (rúbrica) con {detector_codes}:** "
            f"**{covered} / 20** queries detectadas (objetivo ≥16).\n"
        )

        # Detalle
        any_detected = any(
            r["status"] == "OK" and any(r["detections"][c].found for c, _ in DETECTORS)
            for _, r in results
        )
        if any_detected:
            print("## Detecciones detalladas\n")
            for q, r in results:
                if r["status"] != "OK":
                    continue
                ds = r["detections"]
                if not any(ds[c].found for c, _ in DETECTORS):
                    continue
                print(f"### {q.qid} — {q.antipattern}")
                print(f"- top node: `{r['top']}`")
                for code, _ in DETECTORS:
                    d = ds[code]
                    if not d.found:
                        continue
                    matches = d.evidence.get("matches", [])
                    print(f"- **{code}** ({len(matches)} match):")
                    for m in matches:
                        snippet = ", ".join(
                            f"{k}={v!r}"
                            for k, v in m.items()
                            if k
                            in (
                                "table",
                                "column",
                                "columns",
                                "function",
                                "tables",
                                "filter",
                                "subplan_name",
                                "outer_table",
                                "inner_table",
                                "index_name",
                                "node_type",
                                "join_node_type",
                                "scan_node_type",
                                "bool_column",
                                "bool_value",
                                "plan_rows",
                                "actual_rows",
                                "estimated_rows",
                                "suggested_sql",
                            )
                        )
                        print(f"  - {snippet}")
                print()

        return 0
    finally:
        pool.close()


if __name__ == "__main__":
    sys.exit(main())

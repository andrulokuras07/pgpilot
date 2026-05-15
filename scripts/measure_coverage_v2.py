"""Mide cobertura de los 19 detectores contra AppDB v2 (BD "sorpresa" del
profesor entregada para Demo Day).

AppDB v2 corre en puerto 5444 (foro_user/foro_pass, db `appdb`). Schema de
foro tipo Reddit con 24 queries plantadas:

- Q01-Q20: los mismos anti-patterns de v1 disfrazados sobre nuevo schema
  (mide la regla R2 — detección estructural, no sobre strings — y R14 —
  no hardcodear nombres). Si los detectores se rompen aquí, el bonus se
  pierde por completo.
- Q21-Q24: anti-patterns NUEVOS no anunciados (UNION vs UNION ALL,
  predicado no-sargable, CTE MATERIALIZED forzada, UPDATE sin filtro
  indexado). Mide la cobertura genérica honesta.

Objetivo rúbrica (Criterio 2.2): **≥4 de 5 queries nuevas detectadas**.
La entrega trae 4 queries nuevas (Q21-Q24), así que el umbral efectivo
es 4/4 o 3/4 con justificación.

Uso:
    docker compose up appdb_v2 -d
    python -m scripts.measure_coverage_v2

Variables de entorno (defaults alineados con docker-compose.yml raíz):
    APPDBV2_HOST=localhost  APPDBV2_PORT=5444  APPDBV2_DB=appdb
    APPDBV2_USER=foro_user  APPDBV2_PASSWORD=foro_pass

NOTA: este script es paralelo a `measure_coverage.py` (que mide v1 en
puerto 5434). NO lo reemplaza — se mantienen los dos para poder
demostrar ambas cifras en Demo Day.
"""

from __future__ import annotations

import inspect
import os
import sys
from dataclasses import dataclass
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
    detect_not_in_nullable_subquery,
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
    ("D21", detect_not_in_nullable_subquery),
    ("D22", detect_count_star_full_table),
)


@dataclass(frozen=True)
class PlantedQueryV2:
    qid: str
    antipattern: str
    sql: str
    is_new: bool  # True para Q21-Q24 (los anti-patterns nuevos no anunciados)


# Una variante representativa por cada Q##. Literales tomados directo de
# `infra/appdb_v2/init/02_plantar_queries.sql`. Para Q24 se eligió el SELECT
# que representa el WHERE del UPDATE plantado (sobre `eliminado`, columna
# sin índice — el anti-pattern real, no las variantes con `autor_id` que
# sí tiene índice).
PLANTED_V2: tuple[PlantedQueryV2, ...] = (
    PlantedQueryV2(
        "Q01",
        "Seq scan en tabla grande sin índice (hilos.autor_id)",
        "SELECT * FROM hilos WHERE autor_id = 12345",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q02",
        "OR cross-column (autor_id OR citado_id)",
        "SELECT id FROM hilos WHERE autor_id = 100 OR citado_id = 100",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q03",
        "LIKE con comodín al inicio",
        "SELECT id FROM hilos WHERE cuerpo LIKE '%bitcoin%'",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q04",
        "Función no-immutable en WHERE (EXTRACT)",
        "SELECT * FROM hilos WHERE EXTRACT(YEAR FROM creado) = 2024",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q05",
        "GROUP BY + ORDER BY con sort en disco",
        "SELECT miembro_id, count(*) FROM votos GROUP BY miembro_id ORDER BY 2 DESC",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q06",
        "JOIN con sintaxis de coma",
        (
            "SELECT h.id, r.contenido FROM hilos h, respuestas r "
            "WHERE h.id = r.hilo_id AND h.autor_id BETWEEN 1 AND 1000"
        ),
        is_new=False,
    ),
    PlantedQueryV2(
        "Q07",
        "SELECT * cuando solo se usan pocas columnas",
        "SELECT * FROM hilos WHERE creado > NOW() - INTERVAL '7 days'",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q08",
        "Falta de índice cubriente (autor_id, creado)",
        "SELECT id, creado FROM hilos WHERE autor_id = 5000 ORDER BY creado DESC LIMIT 20",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q09",
        "Subquery correlacionada que debería ser JOIN",
        (
            "SELECT h.id, (SELECT count(*) FROM respuestas r WHERE r.hilo_id = h.id) "
            "AS num_resp FROM hilos h WHERE h.autor_id BETWEEN 1 AND 200"
        ),
        is_new=False,
    ),
    PlantedQueryV2(
        "Q10",
        "Stats desactualizadas en hilos_recientes",
        "SELECT * FROM hilos_recientes WHERE autor_id = 100",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q11",
        "Falta índice parcial (avisos.leido = false)",
        "SELECT * FROM avisos WHERE miembro_id = 100 AND leido = false",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q12",
        "DISTINCT que esconde JOIN duplicador",
        (
            "SELECT DISTINCT h.id, h.titulo "
            "FROM hilos h JOIN hilo_etiquetas he ON he.hilo_id = h.id "
            "WHERE h.autor_id BETWEEN 1 AND 500"
        ),
        is_new=False,
    ),
    PlantedQueryV2(
        "Q13",
        "OFFSET grande en paginación",
        "SELECT * FROM respuestas ORDER BY id LIMIT 20 OFFSET 500000",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q14",
        "Función sobre columna invalida índice (upper)",
        "SELECT id FROM miembros WHERE upper(correo) = 'MIEMBRO999@FORO.MX'",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q15",
        "NOT IN con subquery nullable",
        "SELECT id FROM miembros WHERE id NOT IN (SELECT autor_id FROM hilos)",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q16",
        "COUNT(*) sobre tabla enorme",
        "SELECT count(*) FROM hilos",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q17",
        "ORDER BY con función (date_trunc)",
        "SELECT id, creado FROM hilos ORDER BY date_trunc('day', creado) DESC LIMIT 50",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q18",
        "ORDER BY ... LIMIT sobre columna sin índice",
        "SELECT * FROM respuestas ORDER BY creado DESC LIMIT 50",
        is_new=False,
    ),
    PlantedQueryV2(
        "Q19",
        "JOIN ON true (cross join acotado por LIMIT)",
        (
            "SELECT h.id, m.alias FROM hilos h JOIN miembros m ON true "
            "WHERE h.autor_id = 100 LIMIT 100"
        ),
        is_new=False,
    ),
    PlantedQueryV2(
        "Q20",
        "IN con lista enorme de literales",
        (
            "SELECT * FROM miembros WHERE id IN ("
            "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,"
            "21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,"
            "41,42,43,44,45,46,47,48,49,50)"
        ),
        is_new=False,
    ),
    PlantedQueryV2(
        "Q21",
        "[NUEVO] UNION en lugar de UNION ALL",
        (
            "SELECT id FROM hilos WHERE autor_id = 100 "
            "UNION SELECT id FROM hilos WHERE autor_id = 200"
        ),
        is_new=True,
    ),
    PlantedQueryV2(
        "Q22",
        "[NUEVO] Predicado no-sargable (autor_id + 0)",
        "SELECT * FROM respuestas WHERE autor_id + 0 = 100",
        is_new=True,
    ),
    PlantedQueryV2(
        "Q23",
        "[NUEVO] CTE forzada con MATERIALIZED",
        (
            "WITH hilos_cte AS MATERIALIZED (SELECT * FROM hilos) "
            "SELECT * FROM hilos_cte WHERE autor_id = 100"
        ),
        is_new=True,
    ),
    PlantedQueryV2(
        "Q24",
        "[NUEVO] UPDATE/DELETE sin filtro indexado (eliminado)",
        "SELECT count(*) FROM respuestas WHERE eliminado = true",
        is_new=True,
    ),
)


def _get_pool():
    config = ConnectionConfig(
        host=os.environ.get("APPDBV2_HOST", "localhost"),
        port=int(os.environ.get("APPDBV2_PORT", "5444")),
        dbname=os.environ.get("APPDBV2_DB", "appdb"),
        user=os.environ.get("APPDBV2_USER", "foro_user"),
        password=os.environ.get("APPDBV2_PASSWORD", "foro_pass"),
    )
    return create_pool(config)


def _explain(pool, sql: str) -> Any:
    """EXPLAIN ANALYZE con timeout extendido a 180s.

    El pool de `/conector` aplica `statement_timeout = 5000` por R7 (es lo
    correcto para el orquestador de runtime, donde queremos cancelar queries
    largas del usuario). Pero las queries plantadas en AppDB v2 son lentas a
    propósito (Q15 NOT IN sin índice nullable mide ~76s a mano). Para
    *medir cobertura* necesitamos verlas completas, así que subimos el
    timeout solo en este script vía `SET LOCAL` dentro de transacción
    explícita (recomendación de `conector/CLAUDE.md`).
    """
    try:
        with pool.connection() as conn:
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout = 180000")
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
    print(f"# Cobertura agregada — {codes} contra AppDB v2 (sorpresa del profe)\n")
    print("Conectando a AppDB v2 (puerto 5444)...")
    pool = _get_pool()
    try:
        print("Extrayendo snapshot del schema...")
        snapshot = extract_snapshot(pool)
        big = sum(1 for t in snapshot["sizes"].values() if t.get("estimated_rows", 0) >= 100_000)
        print(f"  {len(snapshot['schema'])} tablas, " f"{big} con ≥100k filas estimadas\n")

        results: list[tuple[PlantedQueryV2, dict[str, Any]]] = []
        for q in PLANTED_V2:
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

        legacy_covered = 0
        new_covered = 0
        legacy_total = 0
        new_total = 0
        per_detector = {code: 0 for code, _ in DETECTORS}
        errors = 0

        def _mark(d: Detection) -> str:
            return "✅" if d.found else "—"

        for q, r in results:
            if q.is_new:
                new_total += 1
            else:
                legacy_total += 1

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
                if q.is_new:
                    new_covered += 1
                else:
                    legacy_covered += 1
            for code, _ in DETECTORS:
                if ds[code].found:
                    per_detector[code] += 1

            marks = " | ".join(_mark(ds[code]) for code, _ in DETECTORS)
            print(
                f"| {q.qid} | {q.antipattern} | `{r['top']}` | "
                f"{marks} | "
                f"{'**SÍ**' if any_found else '—'} |"
            )

        # Resumen partido legacy / nuevos (lo que la rúbrica evalúa por separado)
        print("\n## Resumen\n")
        print(f"- Total queries probadas: **{len(PLANTED_V2)}** (20 disfrazadas + 4 nuevas)")
        print(
            f"- **Legacy (Q01-Q20):** {legacy_covered}/{legacy_total} cubiertas "
            f"(objetivo: misma cobertura que v1 = ≥16/20)"
        )
        print(
            f"- **Nuevos (Q21-Q24):** {new_covered}/{new_total} cubiertas "
            f"(objetivo bonus: ≥4 según rúbrica original; aquí solo hay 4 plantados)"
        )
        print(f"- Errores de ejecución: **{errors}**")
        print()
        print("### Detecciones por detector")
        for code, _ in DETECTORS:
            print(f"- **{code}** disparó en: **{per_detector[code]}** queries")

        # Veredicto rúbrica explícito (para no tener que leer la tabla)
        print("\n### Veredicto rúbrica\n")
        v1_pass = legacy_covered >= 16
        bonus_pass = new_covered >= 4
        print(
            f"- Cobertura genérica (R2/R14): **{'OK' if v1_pass else 'FALTA'}** — "
            f"{legacy_covered}/20 sobre schema nuevo (objetivo ≥16)"
        )
        print(
            f"- Bonus detección anti-patterns nuevos: "
            f"**{'OK' if bonus_pass else 'PARCIAL'}** — {new_covered}/4 nuevos detectados"
        )

        # Detalle de qué disparó dónde
        any_detected = any(
            r["status"] == "OK" and any(r["detections"][c].found for c, _ in DETECTORS)
            for _, r in results
        )
        if any_detected:
            print("\n## Detecciones detalladas\n")
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

"""Mide cobertura real del detector C1 contra las 20 queries plantadas en AppDB v1.

Por cada query representativa de Q01..Q20:
1. Corre `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` contra AppDB (read-only).
2. Parsea el plan con `motor.parse_explain`.
3. Llama `detect_seq_scan_on_large_table` + `recommend_for_seq_scan_on_large_table`.
4. Compara contra el objetivo legítimo de C1 (triage manual basado en
   `01_schema.sql`, `HALLAZGOS_v1.md` y el código del detector).

C1 dispara cuando: Seq Scan + tabla ≥100k filas + índice btree cuya primera
columna coincide con la columna del filtro WHERE. NO cubre "índice falta"
(`motor/detectors/seq_scan_on_large_table.py` líneas 100-105).

Uso:
    docker compose up appdb -d
    python -m scripts.measure_c1_coverage

Variables de entorno (defaults de docker-compose.yml):
    APPDB_HOST=localhost  APPDB_PORT=5434  APPDB_DB=appdb
    APPDB_USER=app_user   APPDB_PASSWORD=app_pass
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Permite correr el script desde la raíz del repo sin instalación.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conector import ConnectionConfig, create_pool, extract_snapshot  # noqa: E402
from motor import (  # noqa: E402
    Recommendation,
    detect_seq_scan_on_large_table,
    parse_explain,
    recommend_for_seq_scan_on_large_table,
)


@dataclass(frozen=True)
class PlantedQuery:
    qid: str
    antipattern: str
    sql: str
    c1_target: bool
    triage_reason: str


# Una variante representativa por cada Q##. Los literales son irrelevantes
# para el shape del plan; el detector decide sobre estructura (R2).
PLANTED: tuple[PlantedQuery, ...] = (
    PlantedQuery(
        "Q01",
        "Seq scan sin índice en author_id",
        "SELECT * FROM posts WHERE author_id = 5000",
        c1_target=False,
        triage_reason="posts.author_id sin índice → C1 no dispara (frontera con C2)",
    ),
    PlantedQuery(
        "Q02",
        "OR cross-column",
        "SELECT id FROM posts WHERE author_id = 100 OR mentioned_user_id = 100",
        c1_target=False,
        triage_reason="Regex captura 'author_id' (sin índice)",
    ),
    PlantedQuery(
        "Q03",
        "LIKE wildcard inicial",
        "SELECT id FROM posts WHERE content LIKE '%bitcoin%'",
        c1_target=False,
        triage_reason="posts.content sin índice btree",
    ),
    PlantedQuery(
        "Q04",
        "Función no-immutable en WHERE",
        "SELECT count(*) FROM posts WHERE EXTRACT(YEAR FROM created_at) = 2024",
        c1_target=False,
        triage_reason="Filtro envuelto en date_part(); regex no extrae columna",
    ),
    PlantedQuery(
        "Q05",
        "Sort spill to disk",
        (
            "SELECT u.username, count(l.id) AS like_count "
            "FROM users u JOIN likes l ON l.user_id = u.id "
            "GROUP BY u.username ORDER BY like_count DESC"
        ),
        c1_target=False,
        triage_reason="JOIN/GROUP BY sin WHERE simple sobre tabla grande",
    ),
    PlantedQuery(
        "Q06",
        "Nested loop ineficiente",
        (
            "SELECT p.id, c.content FROM posts p, comments c "
            "WHERE p.id = c.post_id AND p.author_id BETWEEN 1 AND 100"
        ),
        c1_target=False,
        triage_reason="posts.author_id sin índice (idéntico a Q01)",
    ),
    PlantedQuery(
        "Q07",
        "SELECT * sobre tabla grande",
        "SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '7 days'",
        c1_target=True,
        triage_reason="posts.created_at tiene índice; si planner elige Seq Scan, C1 dispara",
    ),
    PlantedQuery(
        "Q08",
        "Falta índice cubriente",
        (
            "SELECT id, created_at FROM posts "
            "WHERE author_id = 5000 ORDER BY created_at DESC LIMIT 20"
        ),
        c1_target=False,
        triage_reason="posts.author_id sin índice",
    ),
    PlantedQuery(
        "Q09",
        "Subquery correlacionada",
        (
            "SELECT id, (SELECT count(*) FROM comments WHERE post_id = posts.id) "
            "FROM posts WHERE author_id = 1000 LIMIT 50"
        ),
        c1_target=False,
        triage_reason="Outer query usa posts.author_id (sin índice)",
    ),
    PlantedQuery(
        "Q10",
        "Stats obsoletas en tags",
        "SELECT count(*) FROM tags WHERE use_count > 100",
        c1_target=False,
        triage_reason="tags es tabla chica (<100k filas)",
    ),
    PlantedQuery(
        "Q11",
        "Falta índice parcial",
        "SELECT id FROM notifications WHERE user_id = 1000 AND read = false",
        c1_target=True,
        triage_reason="notifications.user_id tiene índice; si Seq Scan, C1 dispara",
    ),
    PlantedQuery(
        "Q12",
        "Cast en columna indexada",
        "SELECT * FROM users WHERE username::text = '12345'",
        c1_target=False,
        triage_reason="users es chica (~50k); el cast esconde la columna",
    ),
    PlantedQuery(
        "Q13",
        "Cardinalidad multi-condición",
        (
            "SELECT p.id, u.username FROM posts p "
            "JOIN users u ON u.id = p.author_id "
            "WHERE u.is_verified = true AND u.is_active = true "
            "AND p.is_deleted = false"
        ),
        c1_target=False,
        triage_reason="Filtros sobre bools sin índices apuntables",
    ),
    PlantedQuery(
        "Q14",
        "CTE MATERIALIZED",
        (
            "WITH active_users AS MATERIALIZED ("
            "SELECT id FROM users WHERE last_login > NOW() - INTERVAL '30 days'"
            ") "
            "SELECT count(*) FROM active_users "
            "JOIN posts ON posts.author_id = active_users.id"
        ),
        c1_target=False,
        triage_reason="CTE sobre users (chica); JOIN no genera filter sobre col indexada",
    ),
    PlantedQuery(
        "Q15",
        "Recheck con alta filter ratio",
        (
            "SELECT id FROM posts "
            "WHERE created_at > NOW() - INTERVAL '2 years' AND likes_count > 950"
        ),
        c1_target=True,
        triage_reason="posts.created_at indexada; si Seq Scan, C1 dispara",
    ),
    PlantedQuery(
        "Q16",
        "HAVING que debería ser WHERE",
        ("SELECT author_id, count(*) FROM posts " "GROUP BY author_id HAVING author_id = 1000"),
        c1_target=False,
        triage_reason="HAVING es post-agregación; no aparece como filter en Seq Scan",
    ),
    PlantedQuery(
        "Q17",
        "IN con subquery vs EXISTS",
        (
            "SELECT id FROM users WHERE id IN ("
            "SELECT author_id FROM posts WHERE created_at > NOW() - INTERVAL '7 days'"
            ")"
        ),
        c1_target=False,
        triage_reason="users es chica; semi-join no genera filter simple",
    ),
    PlantedQuery(
        "Q18",
        "ORDER BY+LIMIT sin índice",
        "SELECT * FROM comments ORDER BY created_at DESC LIMIT 50",
        c1_target=False,
        triage_reason="Sin WHERE; C1 exige columna del filtro",
    ),
    PlantedQuery(
        "Q19",
        "NOT IN con NULL",
        "SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts) LIMIT 10",
        c1_target=False,
        triage_reason="users es chica + anti-join sin WHERE simple",
    ),
    PlantedQuery(
        "Q20",
        "count(*) sobre tabla grande",
        "SELECT count(*) FROM posts",
        c1_target=False,
        triage_reason="Sin WHERE → sin filter parseable",
    ),
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
    """Devuelve el JSON parseado de EXPLAIN o un dict con clave 'error'."""
    try:
        with pool.connection() as conn:
            cur = conn.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:  # noqa: BLE001 — queremos cualquier error tabulado
        return {"__error__": str(exc)}


def _classify(target: bool, detected: bool) -> str:
    if target and detected:
        return "TP"
    if target and not detected:
        return "FN"
    if not target and detected:
        return "FP"
    return "TN"


def _format_recs(recs: list[Recommendation]) -> str:
    if not recs:
        return "—"
    return ", ".join(f"{r.kind}({r.table}.{r.column})" for r in recs)


def main() -> int:
    print("# Cobertura C1 — medición empírica contra AppDB v1\n")
    print("Conectando a AppDB...")
    pool = _get_pool()
    try:
        print("Extrayendo snapshot del schema...")
        snapshot = extract_snapshot(pool)
        tables_with_size = sum(
            1 for t in snapshot["sizes"].values() if t.get("estimated_rows", 0) >= 100_000
        )
        print(
            f"  {len(snapshot['schema'])} tablas, "
            f"{tables_with_size} con ≥100k filas estimadas\n"
        )

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
            detection = detect_seq_scan_on_large_table(plan, snapshot)
            recs = (
                recommend_for_seq_scan_on_large_table(detection, snapshot)
                if detection.found
                else []
            )
            results.append(
                (
                    q,
                    {
                        "status": "OK",
                        "top": plan.root.node_type,
                        "detection": detection,
                        "recs": recs,
                    },
                )
            )

        # Tabla principal
        print("## Resultados\n")
        header = (
            "| Q | Anti-pattern | Top node | Target C1 | Detectado | Veredicto | Recomendación |"
        )
        sep = "|---|---|---|---|---|---|---|"
        print(header)
        print(sep)

        counts = {"TP": 0, "FP": 0, "FN": 0, "TN": 0, "ERROR": 0}
        for q, r in results:
            if r["status"] != "OK":
                counts["ERROR"] += 1
                msg = r.get("msg", "")[:60]
                print(f"| {q.qid} | {q.antipattern} | " f"`{r['status']}: {msg}` | — | — | — | — |")
                continue

            detection = r["detection"]
            verdict = _classify(q.c1_target, detection.found)
            counts[verdict] += 1
            print(
                f"| {q.qid} | {q.antipattern} | `{r['top']}` | "
                f"{'sí' if q.c1_target else '—'} | "
                f"{'sí' if detection.found else '—'} | "
                f"**{verdict}** | {_format_recs(r['recs'])} |"
            )

        # Resumen
        target_total = sum(1 for q in PLANTED if q.c1_target)
        print("\n## Resumen\n")
        print(f"- Total queries probadas: **{len(PLANTED)}**")
        print(f"- Objetivos legítimos de C1 (triage manual): **{target_total}**")
        print(f"- True positives (TP):  **{counts['TP']}**")
        print(f"- False negatives (FN): **{counts['FN']}**")
        print(f"- False positives (FP): **{counts['FP']}**")
        print(f"- True negatives (TN):  **{counts['TN']}**")
        print(f"- Errores de ejecución: **{counts['ERROR']}**")

        if target_total:
            recall = counts["TP"] / target_total
            print(
                f"\n**Recall sobre target de C1:** {counts['TP']}/{target_total} = {recall*100:.0f}%"
            )
        denom = counts["TP"] + counts["FP"]
        if denom:
            precision = counts["TP"] / denom
            print(f"**Precisión:** {counts['TP']}/{denom} = {precision*100:.0f}%")

        print(
            "\n**Cobertura GLOBAL del proyecto (rúbrica) con sólo C1:** "
            f"**{counts['TP']} / 20** queries detectadas "
            f"(objetivo ≥16; falsos positivos {counts['FP']}, tope <3).\n"
        )

        # Detalle de detecciones (evidencia para PROGRESS.md)
        any_detected = any(r["status"] == "OK" and r["detection"].found for _, r in results)
        if any_detected:
            print("## Detecciones detalladas\n")
            for q, r in results:
                if r["status"] != "OK" or not r["detection"].found:
                    continue
                print(f"### {q.qid} — {q.antipattern}")
                for m in r["detection"].evidence["matches"]:
                    print(
                        f"- tabla=`{m['table']}` col=`{m['column']}` "
                        f"idx=`{m['index_name']}` filas≈{m['estimated_rows']:,} "
                        f"rows_removed={m.get('rows_removed_by_filter')}"
                    )
                for rec in r["recs"]:
                    print(f"- recomendación `{rec.kind}`: `{rec.create_index_sql}`")
                print()

        return 0
    finally:
        pool.close()


if __name__ == "__main__":
    sys.exit(main())

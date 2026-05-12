"""Recomendador del motor — C2 (base) + D13 (ampliación).

Función pura (R9) que recibe `Detection` de los detectores del motor y
produce una lista de `Recommendation`. No habla con el LLM, no toca el
sandbox, no consulta la BD. Toda la decisión sale de la detección y del
`SchemaSnapshot`.

**D13 — Selectividad real (2026-05-12).** El recomendador filtra las
recomendaciones tipo `create_index` cuando la columna no es
suficientemente selectiva: si `n_distinct` y `null_frac` indican que el
filtro deja pasar más del `MIN_SELECTIVITY_FOR_INDEX` (20 % por
defecto), un btree no aporta y la recomendación se descarta (devuelve
una `Recommendation` con `kind="skipped_low_selectivity"` para que el
backend pueda exponerlo en el JSONL/logs sin alimentar la UI con ruido).
Para `analyze`, `create_partial_index` y `create_statistics` no aplica
el filtro: son acciones cuya utilidad no depende del cardinality del
filtro principal.

Cubre las recomendaciones de:
- C1 → `recommend_for_seq_scan_on_large_table`
- D16 → `recommend_for_missing_index`
- D17 → `recommend_for_partial_index_opportunity`
- D18 → `recommend_for_cardinality_misestimate`
- Orquestador → `recommend(detections, snapshot)` que recibe
  `dict[str, Detection]` (clave = código de detector) y combina todas
  las recomendaciones aplicando el filtro de selectividad.

Cumple R1 (motor decide, sin LLM), R2 (lee solo campos tipados de
`Detection`), R14 (cero literales hardcoded de AppDB).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from motor.detection import Detection

RecommendationKind = Literal[
    "create_index",
    "analyze",
    "create_partial_index",
    "create_statistics",
    "skipped_low_selectivity",
]

# Umbral D13: si selectividad estimada > este valor, un índice btree no
# aporta (un Seq Scan escanea menos páginas que muchísimos lookups). El
# backlog usa el ejemplo "3 valores distintos en 10M filas" (≈0.33) como
# caso a descartar; 0.2 lo cubre con margen razonable y deja pasar
# columnas con ≥5 valores distintos.
MIN_SELECTIVITY_FOR_INDEX = 0.2


@dataclass(frozen=True)
class Recommendation:
    """Acción concreta sugerida por el motor para un anti-pattern detectado.

    `kind` indica qué hacer con la recomendación:
    - `"create_index"`: índice btree faltante; SQL es `CREATE INDEX`.
    - `"analyze"`: el índice ya existe y el planner lo ignora; SQL es
      `ANALYZE <tabla>`.
    - `"create_partial_index"`: índice parcial con predicado WHERE.
    - `"create_statistics"`: estadística extendida multi-columna (D18).
    - `"skipped_low_selectivity"`: la recomendación quedó descartada
      por baja selectividad (D13); útil para logging y debug, no se
      muestra en la UI principal.

    Inmutable: viaja del recomendador al validador (C3) y al prompt
    builder (C4) sin riesgo de mutación accidental.
    """

    kind: RecommendationKind
    table: str  # "<schema>.<tabla>"
    column: str
    index_method: str  # "btree" en v1
    index_name: str  # nombre sugerido o existente
    create_index_sql: str  # SQL listo para mostrar; vacío en `skipped_*`
    justification: str
    expected_impact: str
    selectivity: float | None  # 0..1 si hay stats; None si la tabla no tuvo ANALYZE
    # Campos opcionales agregados en D13:
    partial_predicate: str | None = None  # cláusula WHERE del índice parcial
    statistics_columns: tuple[str, ...] | None = None  # columnas de CREATE STATISTICS


# --- API pública: por detector --------------------------------------


def recommend_for_seq_scan_on_large_table(
    detection: Detection,
    snapshot: dict[str, Any],
    *,
    min_selectivity: float = MIN_SELECTIVITY_FOR_INDEX,
) -> list[Recommendation]:
    """Recomendaciones a partir de la detección C1.

    Mantiene el comportamiento original (`analyze` cuando el índice
    existe; `create_index` cuando no) y agrega el filtro D13: si el
    `create_index` saldría con selectividad > `min_selectivity`, se
    sustituye por `skipped_low_selectivity` con la razón en
    `justification`. `analyze` nunca se filtra (es barato y útil).
    """
    if not detection.found:
        return []

    schema = snapshot.get("schema", {})
    stats = snapshot.get("stats", {})

    recommendations: list[Recommendation] = []
    for match in detection.evidence.get("matches", []):
        table = match["table"]
        column = match["column"]
        estimated_rows = match.get("estimated_rows", 0)

        column_stats = stats.get(table, {}).get(column)
        selectivity = compute_selectivity(column_stats, estimated_rows)
        existing_index = _existing_btree_on_column(schema.get(table), column)

        if existing_index is not None:
            recommendations.append(
                _analyze_recommendation(
                    table=table,
                    column=column,
                    existing_index_name=existing_index,
                    estimated_rows=estimated_rows,
                    selectivity=selectivity,
                    column_stats=column_stats,
                )
            )
            continue

        if _is_low_selectivity(selectivity, min_selectivity):
            recommendations.append(
                _skipped_low_selectivity(
                    table=table,
                    column=column,
                    selectivity=selectivity,
                    estimated_rows=estimated_rows,
                    threshold=min_selectivity,
                )
            )
            continue

        recommendations.append(
            _create_index_recommendation(
                table=table,
                column=column,
                estimated_rows=estimated_rows,
                selectivity=selectivity,
                column_stats=column_stats,
            )
        )

    return recommendations


def recommend_for_missing_index(
    detection: Detection,
    snapshot: dict[str, Any],
    *,
    min_selectivity: float = MIN_SELECTIVITY_FOR_INDEX,
) -> list[Recommendation]:
    """Recomendaciones a partir de la detección D16.

    D16 emite `suggested_sql` en cada match; el recomendador construye
    `Recommendation` enriqueciendo con stats reales (selectividad,
    null_frac) y aplica el filtro D13.
    """
    if not detection.found:
        return []

    stats = snapshot.get("stats", {})
    recommendations: list[Recommendation] = []

    for match in detection.evidence.get("matches", []):
        table = match["table"]
        column = match["column"]
        estimated_rows = match.get("estimated_rows", 0)
        index_name = match.get("suggested_index_name") or f"idx_{table.split('.')[-1]}_{column}"
        sql = match.get("suggested_sql") or _default_create_index_sql(table, column, index_name)

        column_stats = stats.get(table, {}).get(column)
        selectivity = compute_selectivity(column_stats, estimated_rows)

        if _is_low_selectivity(selectivity, min_selectivity):
            recommendations.append(
                _skipped_low_selectivity(
                    table=table,
                    column=column,
                    selectivity=selectivity,
                    estimated_rows=estimated_rows,
                    threshold=min_selectivity,
                )
            )
            continue

        justification = _build_create_justification(
            table=table,
            column=column,
            estimated_rows=estimated_rows,
            selectivity=selectivity,
            column_stats=column_stats,
        )
        impact = _build_create_impact(estimated_rows, selectivity)

        recommendations.append(
            Recommendation(
                kind="create_index",
                table=table,
                column=column,
                index_method="btree",
                index_name=index_name,
                create_index_sql=sql,
                justification=justification,
                expected_impact=impact,
                selectivity=selectivity,
            )
        )

    return recommendations


def recommend_for_partial_index_opportunity(
    detection: Detection,
    snapshot: dict[str, Any],
) -> list[Recommendation]:
    """Recomendaciones a partir de la detección D17.

    D17 ya filtra estructuralmente (predicado bool + otra columna). La
    selectividad efectiva depende del valor del bool (D17 no consulta
    `most_common_freqs` — eso requeriría extender B4), así que el filtro
    D13 NO se aplica aquí: la decisión final la toma el sandbox.
    """
    if not detection.found:
        return []

    stats = snapshot.get("stats", {})
    recommendations: list[Recommendation] = []

    for match in detection.evidence.get("matches", []):
        table = match["table"]
        column = match["column"]
        bool_col = match["bool_column"]
        bool_value = match["bool_value"]
        index_name = match.get("suggested_index_name") or (
            f"idx_{table.split('.')[-1]}_{column}_partial"
        )
        sql = match.get("suggested_sql") or (
            f"CREATE INDEX {index_name} ON {table} ({column}) " f"WHERE {bool_col} = {bool_value};"
        )
        predicate = f"{bool_col} = {bool_value}"

        column_stats = stats.get(table, {}).get(column)
        # Para índice parcial usamos la selectividad de la columna NO
        # booleana; sirve como referencia pero no es la efectiva real.
        selectivity = compute_selectivity(column_stats, match.get("plan_rows", 0))

        justification = (
            f"El filtro combina `{bool_col} = {bool_value}` con `{column}`. "
            f"Un índice parcial sobre `{column}` restringido a "
            f"`{predicate}` reduce el tamaño del índice y mejora la "
            f"selectividad efectiva sobre las filas que cumplen el "
            f"predicado booleano."
        )
        impact = (
            "Cambio esperado en el plan: el scan filtra primero por el "
            "predicado bool y luego usa el índice parcial; valida con "
            "sandbox (C3) que el plan adopte el nuevo índice y que el "
            "costo baje."
        )

        recommendations.append(
            Recommendation(
                kind="create_partial_index",
                table=table,
                column=column,
                index_method="btree",
                index_name=index_name,
                create_index_sql=sql,
                justification=justification,
                expected_impact=impact,
                selectivity=selectivity,
                partial_predicate=predicate,
            )
        )

    return recommendations


def recommend_for_cardinality_misestimate(
    detection: Detection,
    snapshot: dict[str, Any],
) -> list[Recommendation]:
    """Recomendaciones a partir de la detección D18 (CREATE STATISTICS).

    D18 reporta joins mal estimados originados en AND multi-columna.
    El recomendador emite `CREATE STATISTICS` con las columnas
    correlacionadas, ordenadas por selectividad descendente cuando hay
    stats (más selectiva primero, mejor diagnóstico). No se filtra por
    selectividad: una estadística no impone overhead de espacio
    comparable a un índice.
    """
    if not detection.found:
        return []

    stats = snapshot.get("stats", {})
    recommendations: list[Recommendation] = []

    for match in detection.evidence.get("matches", []):
        table = match["table"]
        cols: list[str] = list(match["columns"])
        ordered_cols = _order_columns_by_selectivity(stats.get(table, {}), cols)
        table_name_only = table.split(".")[-1]
        stats_name = match.get("suggested_statistics_name") or (
            f"stats_{table_name_only}_" + "_".join(ordered_cols)
        )
        cols_csv = ", ".join(ordered_cols)
        sql = match.get("suggested_sql") or (
            f"CREATE STATISTICS {stats_name} ON {cols_csv} FROM {table};"
        )

        plan_rows = match.get("plan_rows", 0)
        actual_rows = match.get("actual_rows", 0)
        justification = (
            f"El join `{match.get('join_node_type')}` estimó {plan_rows:,} "
            f"filas pero produjo {actual_rows:,}. El scan descendiente "
            f"({match.get('scan_node_type')}) filtra por {len(cols)} "
            f"columnas de `{table}` que probablemente están correlacionadas. "
            f"`CREATE STATISTICS` permite al planner capturar la "
            f"dependencia y mejorar la estimación."
        )
        impact = (
            "Cambio esperado en el plan: la estimación del join se "
            "alinea con la realidad; el planner puede elegir un "
            "algoritmo distinto (Hash → Merge, o viceversa) o cambiar "
            "el orden del join. Validar con sandbox (C3) tras ANALYZE."
        )

        recommendations.append(
            Recommendation(
                kind="create_statistics",
                table=table,
                column=ordered_cols[0] if ordered_cols else "",
                index_method="extended_statistics",
                index_name=stats_name,
                create_index_sql=sql,
                justification=justification,
                expected_impact=impact,
                selectivity=None,
                statistics_columns=tuple(ordered_cols),
            )
        )

    return recommendations


# --- API pública: orquestador --------------------------------------


def recommend(
    detections: dict[str, Detection],
    snapshot: dict[str, Any],
    *,
    min_selectivity: float = MIN_SELECTIVITY_FOR_INDEX,
) -> list[Recommendation]:
    """Combina recomendaciones de todos los detectores con recomendador.

    Recibe un mapa `código_detector → Detection` (mismo shape que
    `scripts/measure_coverage.py.DETECTORS`). Devuelve la lista plana de
    todas las recomendaciones, en orden por código de detector ascendente
    para que el output sea determinista.

    Códigos cubiertos hoy: C1, D16, D17, D18. Los demás detectores
    estructurales (D4–D12) no emiten recomendaciones de índice — su
    salida la consume el LLM/template como prosa explicativa o reescritura.
    """
    recommenders = {
        "C1": lambda d: recommend_for_seq_scan_on_large_table(
            d, snapshot, min_selectivity=min_selectivity
        ),
        "D16": lambda d: recommend_for_missing_index(d, snapshot, min_selectivity=min_selectivity),
        "D17": lambda d: recommend_for_partial_index_opportunity(d, snapshot),
        "D18": lambda d: recommend_for_cardinality_misestimate(d, snapshot),
    }
    out: list[Recommendation] = []
    for code in sorted(recommenders):
        det = detections.get(code)
        if det is None or not det.found:
            continue
        out.extend(recommenders[code](det))
    return out


# --- API pública: helpers de selectividad --------------------------


def compute_selectivity(
    column_stats: dict[str, Any] | None,
    estimated_rows: int,
) -> float | None:
    """Selectividad estimada del filtro de igualdad sobre la columna.

    Convención Postgres: `n_distinct` positivo = conteo absoluto;
    negativo = ratio respecto al total de filas (ej. -0.5 = 50% de filas
    tienen valor distinto). Devuelve un float en (0, 1] o `None` cuando
    no hay stats (tabla sin ANALYZE).
    """
    if column_stats is None or not column_stats.get("has_stats"):
        return None
    n_distinct = column_stats.get("n_distinct")
    if n_distinct is None:
        return None
    if n_distinct > 0:
        return 1.0 / n_distinct
    if n_distinct < 0:
        if estimated_rows > 0:
            distinct = max(1.0, -n_distinct * estimated_rows)
            return 1.0 / distinct
        return -n_distinct
    return 1.0


def order_columns_by_selectivity(
    snapshot: dict[str, Any],
    table: str,
    columns: list[str] | tuple[str, ...],
) -> list[str]:
    """Ordena `columns` por selectividad ascendente (más selectiva primero).

    Si no hay stats para alguna columna, queda al final preservando el
    orden original entre ellas. Útil para índices compuestos
    (`CREATE INDEX … (a, b)` rinde mejor con la más selectiva primero) y
    para presentar columnas en `CREATE STATISTICS`.
    """
    stats_for_table = snapshot.get("stats", {}).get(table, {})
    sizes = snapshot.get("sizes", {}).get(table, {})
    rows = sizes.get("estimated_rows", 0)
    return _order_columns_by_selectivity(stats_for_table, list(columns), estimated_rows=rows)


# --- helpers internos ----------------------------------------------


def _existing_btree_on_column(
    table_meta: dict[str, Any] | None,
    column: str,
) -> str | None:
    if table_meta is None:
        return None
    for idx in table_meta.get("indexes", []):
        if idx.get("method") != "btree":
            continue
        cols = idx.get("columns", [])
        if cols and cols[0] == column:
            return idx.get("name")
    return None


def _is_low_selectivity(selectivity: float | None, threshold: float) -> bool:
    """¿La selectividad supera el umbral? `None` = desconocida, NO se filtra."""
    if selectivity is None:
        return False
    return selectivity > threshold


def _order_columns_by_selectivity(
    stats_for_table: dict[str, Any],
    columns: list[str],
    *,
    estimated_rows: int = 0,
) -> list[str]:
    """Implementación. Más selectiva (menor `selectivity`) primero."""

    def key(col: str) -> tuple[int, float, int]:
        sel = compute_selectivity(stats_for_table.get(col), estimated_rows)
        if sel is None:
            return (1, 1.0, columns.index(col))
        return (0, sel, columns.index(col))

    return sorted(columns, key=key)


def _default_create_index_sql(table: str, column: str, index_name: str) -> str:
    schema_name, table_simple = _split_table_key(table)
    qualified = _quote_qualified(schema_name, table_simple)
    return (
        f"CREATE INDEX {_quote_identifier(index_name)} ON {qualified} "
        f"({_quote_identifier(column)});"
    )


def _create_index_recommendation(
    *,
    table: str,
    column: str,
    estimated_rows: int,
    selectivity: float | None,
    column_stats: dict[str, Any] | None,
) -> Recommendation:
    schema_name, table_simple = _split_table_key(table)
    index_name = f"idx_{table_simple}_{column}"
    sql = _default_create_index_sql(table, column, index_name)

    justification = _build_create_justification(
        table=table,
        column=column,
        estimated_rows=estimated_rows,
        selectivity=selectivity,
        column_stats=column_stats,
    )
    expected_impact = _build_create_impact(estimated_rows, selectivity)

    return Recommendation(
        kind="create_index",
        table=table,
        column=column,
        index_method="btree",
        index_name=index_name,
        create_index_sql=sql,
        justification=justification,
        expected_impact=expected_impact,
        selectivity=selectivity,
    )


def _analyze_recommendation(
    *,
    table: str,
    column: str,
    existing_index_name: str,
    estimated_rows: int,
    selectivity: float | None,
    column_stats: dict[str, Any] | None,
) -> Recommendation:
    schema_name, table_simple = _split_table_key(table)
    qualified = _quote_qualified(schema_name, table_simple)
    sql = f"ANALYZE {qualified};"

    sel_str = f"{selectivity:.4%}" if selectivity is not None else "desconocida (tabla sin ANALYZE)"
    justification = (
        f"Existe el índice btree {existing_index_name!r} sobre {table}({column}) "
        f"pero el planner eligió Seq Scan sobre {estimated_rows:,} filas. "
        f"Selectividad estimada del filtro: {sel_str}. La causa más probable es "
        f"que las estadísticas de la tabla estén desactualizadas: refrescarlas "
        f"con ANALYZE puede llevar al planner a usar el índice. Si tras ANALYZE "
        f"el plan sigue siendo Seq Scan, evaluar un índice parcial o de cobertura."
    )
    expected_impact = (
        "Refresco de stats; el planner reevalúa el costo del Index Scan y, si la "
        "selectividad es alta, lo elige sobre el Seq Scan actual."
    )

    return Recommendation(
        kind="analyze",
        table=table,
        column=column,
        index_method="btree",
        index_name=existing_index_name,
        create_index_sql=sql,
        justification=justification,
        expected_impact=expected_impact,
        selectivity=selectivity,
    )


def _skipped_low_selectivity(
    *,
    table: str,
    column: str,
    selectivity: float | None,
    estimated_rows: int,
    threshold: float,
) -> Recommendation:
    """Recomendación marcadora cuando D13 descarta un CREATE INDEX."""
    sel_str = f"{selectivity:.4%}" if selectivity is not None else "desconocida"
    justification = (
        f"Se omitió CREATE INDEX sobre {table}({column}): la columna no es "
        f"suficientemente selectiva (selectividad estimada {sel_str} sobre "
        f"{estimated_rows:,} filas, umbral del recomendador "
        f"{threshold:.0%}). Un índice btree no aceleraría el filtro porque "
        f"Postgres seguiría prefiriendo Seq Scan; la oportunidad real puede "
        f"estar en `CREATE STATISTICS`, un índice parcial o reescribir el "
        f"predicado para que sea más selectivo."
    )
    return Recommendation(
        kind="skipped_low_selectivity",
        table=table,
        column=column,
        index_method="btree",
        index_name="",
        create_index_sql="",
        justification=justification,
        expected_impact=("Sin acción recomendada: crear el índice no mejoraría el plan."),
        selectivity=selectivity,
    )


def _build_create_justification(
    *,
    table: str,
    column: str,
    estimated_rows: int,
    selectivity: float | None,
    column_stats: dict[str, Any] | None,
) -> str:
    parts = [
        f"Seq Scan sobre {table} ({estimated_rows:,} filas estimadas) con filtro "
        f"sobre la columna {column!r}, sin índice btree utilizable."
    ]
    if selectivity is not None:
        parts.append(
            f"Selectividad estimada del filtro: {selectivity:.4%} — un Index Scan visita "
            f"~{max(1, int(selectivity * estimated_rows)):,} filas en lugar de {estimated_rows:,}."
        )
    else:
        parts.append(
            "La tabla nunca fue analizada (`ANALYZE`), así que la selectividad del filtro "
            "no se puede estimar — la recomendación se basa solo en el tamaño de la tabla."
        )
    if column_stats and column_stats.get("null_frac") is not None:
        null_frac = column_stats["null_frac"]
        if null_frac > 0.5:
            parts.append(
                f"Atención: {null_frac:.1%} de la columna son NULL. Considerar un índice "
                f"parcial `WHERE {column} IS NOT NULL` para evitar indexar NULLs."
            )
    parts.append("Método btree: igualdades y rangos sobre escalares.")
    return " ".join(parts)


def _build_create_impact(estimated_rows: int, selectivity: float | None) -> str:
    if selectivity is None:
        return (
            f"Cambio esperado en el plan: Seq Scan ({estimated_rows:,} filas) → Index Scan. "
            "Magnitud por confirmar (sin stats de selectividad). Validar con sandbox (C3)."
        )
    rows_visited = max(1, int(selectivity * estimated_rows))
    return (
        f"Cambio esperado en el plan: Seq Scan ({estimated_rows:,} filas) → Index Scan "
        f"(~{rows_visited:,} filas visitadas, selectividad {selectivity:.4%}). "
        "Validar con sandbox (C3)."
    )


def _split_table_key(table_key: str) -> tuple[str, str]:
    if "." in table_key:
        schema, table = table_key.split(".", 1)
        return schema, table
    return "public", table_key


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_qualified(schema: str, table: str) -> str:
    return f"{_quote_identifier(schema)}.{_quote_identifier(table)}"

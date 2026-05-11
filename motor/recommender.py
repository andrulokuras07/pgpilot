"""Recomendador de índices — C2.

Función pura (R9) que recibe una `Detection` de un detector del motor
y produce una lista de `Recommendation`. No habla con el LLM, no toca
el sandbox, no consulta la BD. Toda la decisión sale de la detección y
del `SchemaSnapshot`.

Decisión clave: el recomendador adapta la acción según si ya existe un
índice btree utilizable sobre la columna. Cuando existe (típico de C1
en su scope actual: "índice presente y planner lo ignora"), emite
`kind="analyze"` — el problema rara vez es índice faltante en ese caso
y casi siempre es stats desactualizadas. Cuando no existe, emite
`kind="create_index"`. Esto deja al recomendador útil tanto para C1
como para detectores futuros del estilo "missing index".

Cumple R1 (motor decide, sin LLM), R2 (no toca strings del SQL crudo:
todo lo lee del snapshot y de los campos tipados de `Detection`),
R14 (cero nombres de tabla/columna hardcodeados).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from motor.detection import Detection

RecommendationKind = Literal["create_index", "analyze"]


@dataclass(frozen=True)
class Recommendation:
    """Acción concreta sugerida por el motor para un anti-pattern detectado.

    `kind` distingue el tipo de acción:
    - `"create_index"`: el índice no existe; SQL es un `CREATE INDEX`.
    - `"analyze"`: el índice ya existe y el planner lo ignora; SQL es
      `ANALYZE <tabla>` para refrescar stats antes de medidas más drásticas.

    Inmutable a propósito: el recomendador es función pura y la
    `Recommendation` viaja al validador (C3) y al prompt builder (C4)
    sin posibilidad de mutación accidental.
    """

    kind: RecommendationKind
    table: str  # "<schema>.<tabla>"
    column: str
    index_method: str  # "btree" en v1
    index_name: str  # nombre sugerido (kind=create_index) o existente (kind=analyze)
    create_index_sql: str  # SQL completo para mostrar al usuario
    justification: str
    expected_impact: str
    selectivity: float | None  # 0..1 si hay stats; None si la tabla no tuvo ANALYZE


def recommend_for_seq_scan_on_large_table(
    detection: Detection,
    snapshot: dict[str, Any],
) -> list[Recommendation]:
    """Genera una `Recommendation` por cada match de una detección C1.

    Si `detection.found is False`, devuelve `[]`. Si dispara con N
    matches, devuelve N recomendaciones en el mismo orden.

    No valida la detección contra el sandbox — eso lo hace C3.
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
        selectivity = _compute_selectivity(column_stats, estimated_rows)

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
        else:
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


# --- helpers internos ----------------------------------------------


def _existing_btree_on_column(
    table_meta: dict[str, Any] | None,
    column: str,
) -> str | None:
    """Devuelve el nombre del primer índice btree con `column` como
    primera columna, o `None` si no existe.

    Misma lógica que el detector C1 — si fuera a divergir, mover a un
    helper compartido en `motor/`. Por ahora se duplica intencionalmente
    para que el contrato detector/recomendador sea explícito (cada uno
    consulta el snapshot por su cuenta).
    """
    if table_meta is None:
        return None
    for idx in table_meta.get("indexes", []):
        if idx.get("method") != "btree":
            continue
        cols = idx.get("columns", [])
        if cols and cols[0] == column:
            return idx.get("name")
    return None


def _compute_selectivity(
    column_stats: dict[str, Any] | None,
    estimated_rows: int,
) -> float | None:
    """Selectividad estimada del filtro de igualdad sobre la columna.

    Convención Postgres: `n_distinct` positivo es conteo absoluto;
    negativo es ratio respecto al total de filas (ej. -0.5 = 50% de
    filas tienen valor distinto). Devolvemos un float en (0, 1].
    `None` cuando no hay stats (tabla sin ANALYZE).
    """
    if column_stats is None or not column_stats.get("has_stats"):
        return None
    n_distinct = column_stats.get("n_distinct")
    if n_distinct is None:
        return None
    if n_distinct > 0:
        return 1.0 / n_distinct
    if n_distinct < 0:
        # Ratio negativo: -0.5 ⇒ 50% de filas son distintas ⇒
        # selectividad = 1 / (rows * 0.5).
        if estimated_rows > 0:
            distinct = max(1.0, -n_distinct * estimated_rows)
            return 1.0 / distinct
        return -n_distinct  # fallback razonable
    # n_distinct == 0: todos los valores iguales — escanea toda la tabla.
    return 1.0


def _create_index_recommendation(
    *,
    table: str,
    column: str,
    estimated_rows: int,
    selectivity: float | None,
    column_stats: dict[str, Any] | None,
) -> Recommendation:
    """Construye la recomendación CREATE INDEX. El SQL usa identificadores
    citados para tolerar nombres con mayúsculas o caracteres especiales —
    el snapshot los puede traer así desde `pg_catalog`.
    """
    schema_name, table_simple = _split_table_key(table)
    index_name = f"idx_{table_simple}_{column}"
    qualified = _quote_qualified(schema_name, table_simple)
    sql = f"CREATE INDEX {_quote_identifier(index_name)} ON {qualified} ({_quote_identifier(column)});"

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
    """Construye la recomendación ANALYZE para el caso "índice existe pero
    el planner lo ignora".
    """
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


def _build_create_justification(
    *,
    table: str,
    column: str,
    estimated_rows: int,
    selectivity: float | None,
    column_stats: dict[str, Any] | None,
) -> str:
    """Prosa de justificación para la recomendación CREATE INDEX.

    La justificación se arma a partir de hechos del snapshot
    (tamaño + selectividad). Nada de literales hardcodeados (R14).
    """
    parts = [
        f"Seq Scan sobre {table} ({estimated_rows:,} filas estimadas) con filtro de igualdad "
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
                "parcial `WHERE {col} IS NOT NULL` para evitar indexar NULLs.".format(col=column)
            )
    parts.append("Método btree: igualdades y rangos sobre escalares.")
    return " ".join(parts)


def _build_create_impact(estimated_rows: int, selectivity: float | None) -> str:
    """Estimación cualitativa del impacto. No se mete con magnitudes
    absolutas de costo porque dependen del planner y los validamos en C3."""
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
    """Parte `"public.posts"` en (`"public"`, `"posts"`). Si no hay schema,
    devuelve `("public", table_key)` como fallback. El snapshot del
    conector siempre trae la forma calificada, así que el fallback es
    defensivo para entradas degeneradas."""
    if "." in table_key:
        schema, table = table_key.split(".", 1)
        return schema, table
    return "public", table_key


def _quote_identifier(name: str) -> str:
    """Cita un identificador de SQL al estilo Postgres: comillas dobles y
    escape de comillas internas. No se usa para inyección — los nombres
    vienen del snapshot, que vino de `pg_catalog`. La cita es defensa en
    profundidad para tolerar identifiers con mayúsculas o caracteres
    especiales sin romper el SQL."""
    return '"' + name.replace('"', '""') + '"'


def _quote_qualified(schema: str, table: str) -> str:
    return f"{_quote_identifier(schema)}.{_quote_identifier(table)}"

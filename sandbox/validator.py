"""Validación de recomendaciones de índice contra el sandbox — C3.

Dada una `Recommendation` del motor (C2), arma un experimento en el
sandbox: EXPLAIN antes, aplica la recomendación, EXPLAIN después. Si
el tipo de nodo sobre la tabla cambió de `Seq Scan` a algún `Index/
Bitmap Heap/Bitmap Index/Index Only Scan`, la recomendación se
considera **validada**. Si no, se **descarta** con motivo.

**Por qué tipo de nodo y no costo absoluto:** el sandbox monta tablas
vacías. Aun con `pg_restore_relation_stats` falseando `relpages`/
`reltuples`, Postgres consulta el tamaño físico del archivo y, para
archivos vacíos, los costos colapsan a ~0. Las decisiones cualitativas
del planner (escoger Seq vs Index) sí responden a la presencia de
índices, así que ése es el discriminador honesto. Decisión registrada
en `PROGRESS.md` 2026-05-10 (B15+B16, trade-off de PG18 sandbox).

Para recomendaciones de tipo `analyze` (kind="analyze"), el sandbox
no puede simular el efecto de un `ANALYZE` sobre tablas vacías: los
planes antes y después serían idénticos. C3 las marca como
`verdict="skipped_no_sandbox_signal"` para que el caller distinga
"no validable aquí" de "validada"/"descartada". Esto preserva la
honestidad operativa: una recomendación de ANALYZE pasa al usuario
con la prosa del motor (C2) sin pretender que el sandbox la avaló.

Cumple R3 (validación obligatoria de propuestas antes de mostrarlas
al usuario; aquí del motor — aplica también a las del LLM en C6),
R6 (no copia datos), R9 (función pura modulo el I/O al sandbox; cada
llamada self-contained).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from psycopg.sql import SQL, Identifier
from psycopg_pool import ConnectionPool

from conector.types import SchemaSnapshot
from motor import ExplainResult, Recommendation, find_nodes, parse_explain
from motor.parser import PlanNode
from sandbox.setup import drop_sandbox_schema, setup_sandbox_schema

ValidationVerdict = Literal["validated", "discarded", "skipped_no_sandbox_signal"]

# Tipos de nodo que cuentan como "ahora se usa el índice". Cualquier
# transición Seq Scan → uno de estos sobre la misma tabla valida la
# recomendación. Index Only Scan incluido (mejor caso: ni siquiera
# toca el heap).
_INDEX_NODE_TYPES = frozenset(
    {
        "Index Scan",
        "Index Only Scan",
        "Bitmap Heap Scan",
        "Bitmap Index Scan",
    }
)


@dataclass(frozen=True)
class ValidationResult:
    """Veredicto del validador sobre una recomendación.

    - `verdict="validated"`: el tipo de nodo sobre `table` cambió de
      Seq Scan a Index/Bitmap. La recomendación se puede mostrar.
    - `verdict="discarded"`: el plan no cambió (planner sigue ignorando
      el índice). La recomendación NO se muestra; `reason` explica.
    - `verdict="skipped_no_sandbox_signal"`: la recomendación es de
      tipo no validable en sandbox (ej. ANALYZE sobre tabla vacía).
      Se delega al motor (C2) la confianza sobre la prosa.

    `node_type_before`/`_after` son los tipos del nodo de scan que
    afecta `table` en cada plan, o `None` si la query no lo tocó (caso
    raro, se trata como `discarded`).

    `cost_before`/`cost_after` y `plan_rows_before`/`plan_rows_after`
    son el `total_cost` y el `plan_rows` (filas estimadas por el
    planner) de ese mismo nodo en cada corrida. Alimentan el
    comparativo enriquecido del frontend (C11 + E7) y los logs;
    **no participan en el veredicto** — el discriminador es el tipo de
    nodo (las tablas del sandbox están vacías por R6, así que costo y
    filas absolutas no representan producción). No exponemos tiempos:
    el EXPLAIN del sandbox corre sin `ANALYZE` (tablas vacías → un
    `EXPLAIN ANALYZE` no informaría), así que no hay tiempo real que
    mostrar.
    """

    verdict: ValidationVerdict
    reason: str
    node_type_before: str | None
    node_type_after: str | None
    cost_before: float | None
    cost_after: float | None
    plan_rows_before: int | None = None
    plan_rows_after: int | None = None


def validate_index_recommendation(
    pool: ConnectionPool,
    snapshot: SchemaSnapshot,
    query: str,
    recommendation: Recommendation,
    *,
    timeout_seconds: float = 5.0,
    schema_name: str | None = None,
) -> ValidationResult:
    """Valida una recomendación corriendo EXPLAIN antes/después en sandbox.

    Pasos:
    1. Monta el schema del snapshot.
    2. EXPLAIN del `query` → plan_before.
    3. Aplica `recommendation` (CREATE INDEX dentro del schema temporal).
    4. EXPLAIN del `query` otra vez → plan_after.
    5. Compara y dropea el schema en `finally`.

    `recommendation.kind="analyze"` se devuelve como
    `skipped_no_sandbox_signal` sin tocar el sandbox: ejecutar ANALYZE
    sobre tablas vacías no informa.
    """
    if recommendation.kind == "analyze":
        return ValidationResult(
            verdict="skipped_no_sandbox_signal",
            reason=(
                "Recomendación tipo ANALYZE no se valida en sandbox: las tablas "
                "están vacías por R6, así que un ANALYZE no produce señal "
                "comparable a la BD real. La prosa del motor (C2) viaja sin aval "
                "del sandbox."
            ),
            node_type_before=None,
            node_type_after=None,
            cost_before=None,
            cost_after=None,
            plan_rows_before=None,
            plan_rows_after=None,
        )

    schema_name = setup_sandbox_schema(pool, snapshot, schema_name=schema_name)
    timeout_ms = max(1, int(timeout_seconds * 1000))

    try:
        with pool.connection() as conn:
            with conn.transaction():
                conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                conn.execute(
                    SQL("SET LOCAL search_path = {}, public").format(Identifier(schema_name))
                )
                row_before = conn.execute(f"EXPLAIN (FORMAT JSON) {query}").fetchone()
            plan_before = parse_explain(row_before[0]) if row_before is not None else None

            # Aplica la recomendación. Reconstruimos el SQL para apuntarlo al
            # schema temporal — la recomendación del motor usa
            # `<schema_cliente>.<tabla>` (ej. "public.posts") pero en el
            # sandbox la tabla vive en `<schema_name>`. Usar
            # identificadores citados defiende contra nombres con
            # mayúsculas/caracteres especiales.
            _, table_simple = _split_table_key(recommendation.table)
            with conn.transaction():
                conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                conn.execute(
                    SQL("CREATE INDEX {} ON {}.{} USING {} ({})").format(
                        Identifier(recommendation.index_name + "_c3"),
                        Identifier(schema_name),
                        Identifier(table_simple),
                        SQL(recommendation.index_method),
                        Identifier(recommendation.column),
                    )
                )

            # EXPLAIN "after" con `enable_seqscan = off`. Sin este flag, el
            # planner del sandbox preferiría Seq Scan porque las tablas
            # están físicamente vacías y `total_cost` colapsa a 0
            # (limitación heredada de B15+B16, ver `sandbox/CLAUDE.md`).
            # Con el flag, le pedimos al planner: "si te prohibimos Seq
            # Scan, ¿usarías el índice nuevo?". Si emite Index/Bitmap →
            # el índice es estructuralmente aplicable → recomendación
            # validada. Si emite Seq Scan con `Disabled: true` (cuando no
            # hay alternativa viable) → el índice no aplica al filtro →
            # descartada. La semántica acotada del "validated" se
            # documenta en `sandbox/CLAUDE.md`.
            with conn.transaction():
                conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                conn.execute(
                    SQL("SET LOCAL search_path = {}, public").format(Identifier(schema_name))
                )
                conn.execute("SET LOCAL enable_seqscan = off")
                row_after = conn.execute(f"EXPLAIN (FORMAT JSON) {query}").fetchone()
            plan_after = parse_explain(row_after[0]) if row_after is not None else None

        if plan_before is None or plan_after is None:
            return ValidationResult(
                verdict="discarded",
                reason="EXPLAIN no devolvió plan en alguna de las dos corridas.",
                node_type_before=None,
                node_type_after=None,
                cost_before=None,
                cost_after=None,
                plan_rows_before=None,
                plan_rows_after=None,
            )

        return verdict_from_plans(plan_before, plan_after, recommendation.table)
    finally:
        drop_sandbox_schema(pool, schema_name)


def verdict_from_plans(
    plan_before: ExplainResult,
    plan_after: ExplainResult,
    table_key: str,
) -> ValidationResult:
    """Calcula el veredicto a partir de dos planes y la tabla afectada.

    Función pura: sirve como contrato testable sin sandbox real.
    `table_key` es la clave del snapshot (`<schema>.<tabla>`) que se
    matchea contra `relation_name` del nodo de scan en el plan.
    """
    _, table_simple = _split_table_key(table_key)
    node_before = _find_scan_on_relation(plan_before, table_simple)
    node_after = _find_scan_on_relation(plan_after, table_simple)

    type_before = node_before.node_type if node_before else None
    type_after = node_after.node_type if node_after else None
    cost_before = node_before.total_cost if node_before else None
    cost_after = node_after.total_cost if node_after else None
    rows_before = node_before.plan_rows if node_before else None
    rows_after = node_after.plan_rows if node_after else None

    if node_before is None or node_after is None:
        return ValidationResult(
            verdict="discarded",
            reason=f"La query no escanea {table_key!r} en ambos planes.",
            node_type_before=type_before,
            node_type_after=type_after,
            cost_before=cost_before,
            cost_after=cost_after,
            plan_rows_before=rows_before,
            plan_rows_after=rows_after,
        )

    # Caso ideal: Seq Scan → Index/Bitmap.
    if type_before == "Seq Scan" and type_after in _INDEX_NODE_TYPES:
        return ValidationResult(
            verdict="validated",
            reason=(
                f"El planner cambió de Seq Scan a {type_after} sobre {table_simple!r} tras "
                f"crear el índice. La recomendación es útil."
            ),
            node_type_before=type_before,
            node_type_after=type_after,
            cost_before=cost_before,
            cost_after=cost_after,
            plan_rows_before=rows_before,
            plan_rows_after=rows_after,
        )

    # Mismo tipo de nodo: el planner sigue ignorando el índice.
    if type_before == type_after:
        return ValidationResult(
            verdict="discarded",
            reason=(
                f"El planner mantuvo {type_before!r} sobre {table_simple!r} aun con el índice. "
                "Razones probables: selectividad insuficiente, tabla demasiado pequeña en el "
                "sandbox, o el índice elegido no aplica al filtro."
            ),
            node_type_before=type_before,
            node_type_after=type_after,
            cost_before=cost_before,
            cost_after=cost_after,
            plan_rows_before=rows_before,
            plan_rows_after=rows_after,
        )

    # Cambio de nodo pero a algo que no es Index/Bitmap: caso raro,
    # tratamos como descarte para no avalar a ciegas.
    return ValidationResult(
        verdict="discarded",
        reason=(
            f"El nodo sobre {table_simple!r} pasó de {type_before!r} a {type_after!r}, "
            "que no cuenta como uso de índice. Recomendación descartada por precaución."
        ),
        node_type_before=type_before,
        node_type_after=type_after,
        cost_before=cost_before,
        cost_after=cost_after,
        plan_rows_before=rows_before,
        plan_rows_after=rows_after,
    )


# --- helpers -------------------------------------------------------


def _find_scan_on_relation(plan: ExplainResult, relation_name: str) -> PlanNode | None:
    """Devuelve el primer nodo en pre-order DFS cuyo `relation_name` matchea.

    Busca cualquier tipo de scan: Seq/Index/Bitmap. Si la query toca la
    tabla más de una vez (self-join), se queda con la primera —
    suficiente para C3 v1; refinar cuando aparezca el primer self-join
    en AppDB v2.
    """
    scan_types = frozenset(
        {
            "Seq Scan",
            "Index Scan",
            "Index Only Scan",
            "Bitmap Heap Scan",
            "Bitmap Index Scan",
        }
    )
    for node in find_nodes(plan, scan_types):
        if node.relation_name == relation_name:
            return node
    return None


def _split_table_key(table_key: str) -> tuple[str, str]:
    """`"public.posts"` → `("public", "posts")`. Fallback `public` si no
    hay schema en la clave (defensivo)."""
    if "." in table_key:
        schema, table = table_key.split(".", 1)
        return schema, table
    return "public", table_key

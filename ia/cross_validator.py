"""Validación cruzada de sugerencias del LLM — C6.

Después de que C5 valida que la respuesta del LLM respeta el schema
acordado, C6 verifica que lo que el LLM dijo sea coherente con la
realidad: las columnas mencionadas existen, los identificadores no
están inventados, el SQL parsea, los índices propuestos no duplican
otros existentes.

Reglas vivas:

- **R3**: toda salida del LLM se valida antes de mostrarse. C5 fue la
  primera capa (forma); C6 es la segunda (contenido contra schema).
- **R14**: el LLM no puede inventar nombres. Si propone una columna
  o tabla que no existe en el snapshot, descartamos.
- **R1**: el motor manda. Si una sugerencia del LLM contradice lo que
  el motor sabe (índice duplicado, etc.), gana el motor.

Diseño:

- Función pura por defecto: `cross_validate(...)` solo lee el
  `Recommendation`, el `LLMResponseSchema` y el `snapshot`. No toca
  el sandbox.
- Hook opcional para la validación con sandbox (B16): si el caller
  pasa `sandbox_pool` Y `sanitized_query`, se valida con
  `sandbox.validate_index_recommendation` que el índice
  recomendado por el motor sigue siendo aplicable. El sandbox check
  es lento (Docker), por eso es opcional — el orquestador puede
  decidir cuándo correrlo (típicamente: solo en el flujo /analyze del
  backend, no en tests unitarios).
- Razones agrupadas en `CrossValidationResult.reasons` para que C8
  (logs estructurados) pueda guardarlas y para que el frontend pueda
  mostrarlas al developer en modo debug.

El parseo con sqlglot es robusto a SQL no estándar: si sqlglot no
parsea, marcamos la sugerencia como inválida (regla 3 del backlog
C6). Para extracción de identificadores caminamos el AST.

Cumple R8 (type hints), R9 (pura cuando `sandbox_pool=None`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from ia.validator import LLMResponseSchema
from motor import Recommendation

# Dialecto Postgres para sqlglot. AppDB es Postgres 16; sandbox 18.
# sqlglot maneja ambos con el mismo dialect string.
_SQL_DIALECT = "postgres"


@dataclass(frozen=True)
class CrossValidationResult:
    """Resultado de la validación cruzada.

    - `passed`: True si todas las verificaciones pasaron. False si
      alguna falla — en ese caso, el orquestador descarta la respuesta
      del LLM y cae a plantilla.
    - `reasons`: lista de razones cuando falla. Vacía si pasa.
    - `sandbox_verdict`: si se corrió validación de sandbox, el verdict
      crudo (`"validated"`/`"discarded"`/`"skipped_no_sandbox_signal"`).
      `None` si no se corrió.
    """

    passed: bool
    reasons: list[str] = field(default_factory=list)
    sandbox_verdict: str | None = None


def cross_validate(
    response: LLMResponseSchema,
    recommendation: Recommendation,
    snapshot: dict[str, Any],
    *,
    sandbox_pool: Any | None = None,
    sanitized_sql: str | None = None,
) -> CrossValidationResult:
    """Valida cruzando la respuesta del LLM contra schema, SQL y sandbox.

    Verificaciones (todas se corren; reportamos todas las que fallen):

    1. La columna del `Recommendation` existe en la tabla del snapshot
       (defensa: el LLM no debería poder cambiar esto, pero si su
       respuesta apunta a columnas que no existen, descartamos).
    2. Si `recommendation.kind == "create_index"`: el índice
       propuesto NO existe ya en el snapshot.
    3. Si `response.suggested_rewrite` está presente:
       a. Parsea con sqlglot (dialect=postgres).
       b. Si el rewrite contiene `CREATE INDEX`, el nombre del índice
          NO debe existir en el snapshot (R3 explícito del backlog).
       c. Todas las columnas referenciadas existen en algún table del
          snapshot.
    4. Si `sandbox_pool` y `sanitized_sql` están presentes (opcional):
       corremos `sandbox.validate_index_recommendation` para confirmar
       que el motor sigue avalando el índice ante el sandbox.

    Es deliberadamente conservador: si en duda, falla. Mejor caer a
    plantilla determinística que arriesgar mostrar una sugerencia mala
    (R3 + criterio "Menos de 3 falsos positivos sobre queries sanas").
    """
    reasons: list[str] = []
    sandbox_verdict: str | None = None

    schema = snapshot.get("schema", {})

    # 1. Columna del recomendador existe en la tabla del snapshot
    if not _column_exists(schema, recommendation.table, recommendation.column):
        reasons.append(
            f"La columna {recommendation.column!r} no existe en {recommendation.table}; "
            "descartando la recomendación."
        )

    # 2. Índice del recomendador no duplica uno existente
    if recommendation.kind == "create_index":
        if _index_name_exists(schema, recommendation.table, recommendation.index_name):
            reasons.append(
                f"Ya existe un índice llamado {recommendation.index_name!r} en "
                f"{recommendation.table}; el CREATE INDEX duplicaría un nombre."
            )

    # 3. Validación del suggested_rewrite (si vino)
    if response.suggested_rewrite is not None and response.suggested_rewrite.strip():
        rewrite = response.suggested_rewrite
        parsed = _safe_parse(rewrite)
        if parsed is None:
            reasons.append(
                "La reescritura sugerida por el LLM no parsea como SQL Postgres "
                "(sqlglot rechazó la sintaxis)."
            )
        else:
            # 3.b — CREATE INDEX en el rewrite no debe duplicar uno existente
            for index_name in _extract_create_index_names(parsed):
                # Buscamos en todas las tablas porque el rewrite podría no
                # calificar el schema; cualquier índice homónimo en cualquier
                # tabla del snapshot rompe (los nombres de índice son
                # globales por schema en Postgres).
                if _index_name_exists_anywhere(schema, index_name):
                    reasons.append(
                        f"El LLM propone un CREATE INDEX llamado {index_name!r}, "
                        "pero ya existe un índice con ese nombre en el schema."
                    )

            # 3.c — columnas referenciadas existen
            unknown = _unknown_column_references(parsed, schema)
            if unknown:
                reasons.append(
                    "La reescritura del LLM referencia columnas que no existen "
                    f"en el schema: {sorted(unknown)}."
                )

    # 4. Validación opcional con sandbox
    if sandbox_pool is not None and sanitized_sql is not None:
        sandbox_verdict = _sandbox_verdict(sandbox_pool, snapshot, sanitized_sql, recommendation)
        if sandbox_verdict == "discarded":
            reasons.append(
                "El sandbox no pudo validar el índice recomendado "
                "(verdict=discarded); el planner no lo usaría aun con el flag forzado."
            )

    return CrossValidationResult(
        passed=not reasons,
        reasons=reasons,
        sandbox_verdict=sandbox_verdict,
    )


# --- helpers de schema ---------------------------------------------


def _column_exists(
    schema: dict[str, Any],
    table_key: str,
    column: str,
) -> bool:
    table_meta = schema.get(table_key)
    if table_meta is None:
        return False
    for col in table_meta.get("columns", []):
        if col.get("name") == column:
            return True
    return False


def _index_name_exists(
    schema: dict[str, Any],
    table_key: str,
    index_name: str,
) -> bool:
    table_meta = schema.get(table_key)
    if table_meta is None:
        return False
    for idx in table_meta.get("indexes", []):
        if idx.get("name") == index_name:
            return True
    return False


def _index_name_exists_anywhere(
    schema: dict[str, Any],
    index_name: str,
) -> bool:
    """Postgres scope-a los nombres de índice por schema, no por tabla.
    Si dos tablas distintas ya tienen un índice con el mismo nombre,
    el CREATE INDEX falla. Mejor reportarlo desde aquí."""
    for table_meta in schema.values():
        for idx in table_meta.get("indexes", []):
            if idx.get("name") == index_name:
                return True
    return False


# --- helpers de sqlglot --------------------------------------------


def _safe_parse(sql: str) -> list[exp.Expression] | None:
    """Parsea con sqlglot; devuelve None si falla. Filtra el caso
    "sqlglot devuelve `[None]`" que pasa con SQL semánticamente vacío."""
    try:
        statements = sqlglot.parse(sql, dialect=_SQL_DIALECT)
    except ParseError:
        return None
    cleaned = [s for s in statements if s is not None]
    if not cleaned:
        return None
    return cleaned


def _extract_create_index_names(parsed: list[exp.Expression]) -> list[str]:
    """Saca los nombres de los índices creados en `CREATE INDEX` del rewrite.

    sqlglot modela `CREATE INDEX foo ON tbl(col)` como `exp.Create(kind="INDEX", this=exp.Index)`.
    La forma exacta varía por versión; navegamos defensivo.
    """
    names: list[str] = []
    for stmt in parsed:
        for create in stmt.find_all(exp.Create):
            kind = (create.args.get("kind") or "").upper()
            if kind != "INDEX":
                continue
            # `this` puede ser un `exp.Index`, cuyo `this` es el nombre
            # (sqlglot >= 25 lo modela así; antes era plano).
            target = create.this
            name = _expression_name(target)
            if name:
                names.append(name)
    return names


def _expression_name(node: Any) -> str | None:
    """Saca el nombre de un nodo sqlglot, sea Identifier, Table o Index.
    Defensivo a cambios de modelado entre versiones.
    """
    if node is None:
        return None
    if isinstance(node, str):
        return node
    # exp.Index.this es el nombre del índice; exp.Table.name idem
    inner = getattr(node, "this", None)
    if isinstance(inner, exp.Identifier):
        return inner.name
    if isinstance(inner, str):
        return inner
    name_attr = getattr(node, "name", None)
    if isinstance(name_attr, str) and name_attr:
        return name_attr
    return None


def _unknown_column_references(
    parsed: list[exp.Expression],
    schema: dict[str, Any],
) -> set[str]:
    """Columnas referenciadas en el rewrite que no aparecen en NINGÚN
    table del snapshot.

    Es una verificación relajada (no resuelve aliases) — por diseño:
    queremos atrapar inventos del LLM (columna fantasma), no rechazar
    queries por sutilezas de aliasing. Falsos negativos aceptados;
    falsos positivos minimizados.
    """
    known: set[str] = set()
    for table_meta in schema.values():
        for col in table_meta.get("columns", []):
            name = col.get("name")
            if name:
                known.add(name)

    referenced: set[str] = set()
    for stmt in parsed:
        for col in stmt.find_all(exp.Column):
            col_name = col.name
            if col_name:
                referenced.add(col_name)

    return referenced - known


# --- hook opcional al sandbox --------------------------------------


def _sandbox_verdict(
    sandbox_pool: Any,
    snapshot: dict[str, Any],
    sanitized_sql: str,
    recommendation: Recommendation,
) -> str:
    """Corre `sandbox.validate_index_recommendation` y devuelve el verdict
    crudo. Import inline para que el módulo `ia` no quede acoplado a
    `sandbox` en su forma básica (los tests unit de C6 pueden correr
    sin Docker mientras no le pasen `sandbox_pool`)."""
    from sandbox import validate_index_recommendation

    result = validate_index_recommendation(sandbox_pool, snapshot, sanitized_sql, recommendation)
    return result.verdict

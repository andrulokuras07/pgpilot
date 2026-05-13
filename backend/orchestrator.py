"""Orquestador del endpoint /analyze — C9 + E8 (aislamiento de errores).

Aísla la pipeline `query → detección → recomendación → validación →
explicación` en una función pura(-ish) testeable sin levantar uvicorn.
`backend.main` solo conecta este orquestador con el ciclo de vida del
pool y traduce errores a HTTP.

Pipeline:

1. **Sanitizar** la query con `ia.sanitize` (el LLM jamás ve literales — R4).
2. **EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)** contra AppDB con la query
   ORIGINAL (los placeholders no son SQL ejecutable; sanitize es solo
   para el LLM).
3. **Parsear** el plan con `motor.parse_explain` (B7+B8).
4. **Detectar** anti-patterns con los 18 detectores del motor. Cada
   detector corre en su propio try/except (E8). Los que necesitan el SQL
   del usuario (D9, D11, D19, D20, D21) reciben `sql=query`.
5. **Recomendar** índices con `motor.recommend()` para los detectores que
   tienen recomendador formal (C1, D16, D17, D18). Los demás 14
   detectores producen una recomendación sintética `kind="finding"` con
   la evidencia del detector.
6. **Validar** cada recomendación formal en sandbox cuando hay
   `sandbox_pool` con `sandbox.validate_index_recommendation` (C3).
   Las findings no pasan por sandbox (no hay SQL que validar).
7. **Explicar** cada recomendación formal con `ia.explain_recommendation`
   (C4-C7). Las findings usan una explicación determinística basada en
   la evidencia del detector — no se invoca al LLM.

**E8 — aislamiento de errores.** Cada etapa va envuelta en `try/except`.
Si una etapa falla:

- el resto de la pipeline sigue lo que pueda (las etapas por-recomendación
  — validación de sandbox y explicación — son independientes entre sí y
  entre recomendaciones);
- el endpoint NUNCA crashea: devuelve resultados parciales (lo que sí se
  pudo calcular) más una lista `errors` con la etapa que falló y un flag
  `partial=True`;
- la excepción real se loggea server-side (`logging`), pero el mensaje
  que llega al frontend es genérico — no filtra nombres de tabla, paths
  ni stack traces (misma política que `AnalyzeError`).

La única etapa "terminal" es la extracción (EXPLAIN): sin un plan no hay
nada que parsear ni detectar, así que sus fallos se traducen a un
`AnalyzeError` con status HTTP apropiado (4xx para input del usuario,
504 timeout, 500 lo inesperado) en lugar de a un resultado parcial.

Forma del dict devuelto (estable, consumido por `AnalyzeResponse`):

```jsonc
{
  "detections": [...],
  "recommendations": [...],
  "errors": [{"stage": "explain", "message": "..."}],   // vacío si todo OK
  "partial": true                                        // == bool(errors)
}
```

Reglas vivas:

- **R1**: el motor decide. Sólo después de que un detector dispara
  llamamos al LLM (y solo para los detectores con recomendador formal).
- **R3**: cada recomendación lleva su `sandbox_verdict` para que el
  frontend pueda mostrar la columna "validado por sandbox" en la
  tarjeta. Las explicaciones del LLM ya pasaron por cross-validation
  dentro de `explain_recommendation`.
- **R4**: el LLM solo recibe `sanitized_query`; AppDB recibe la query
  original. Si la sanitización falla, NO se llama al LLM para ninguna
  recomendación — se usan explicaciones determinísticas (plantilla).
- **R5**: si el LLM está apagado, sandbox no disponible, sanitize o el
  parser explotan, etc., la pipeline degrada elegante.
- **R7**: AppDB read-only (forzado por `/conector`). El usuario podría
  mandar `UPDATE` o `DROP`, pero la sesión lo rechaza.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from ia import (
    Explanation,
    SanitizedQuery,
    explain_from_template,
    explain_recommendation,
    sanitize,
)
from motor import (
    Detection,
    ExplainResult,
    Recommendation,
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
    recommend,
)
from sandbox import ValidationResult, validate_index_recommendation

log = logging.getLogger("pgpilot.orchestrator")


class AnalyzeError(Exception):
    """Error en el pipeline que el caller HTTP traduce a un status code.

    `status_code` es el HTTP a devolver, `message` la prosa que ve el
    cliente. Los detalles internos NO se filtran al frontend (defensa
    contra leak de info: nombres de tabla, paths internos, etc.).
    """

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# Mensajes que el frontend ve cuando una etapa falla. Genéricos a
# propósito (E8 + política de `AnalyzeError`): el detalle real se loggea
# server-side, no se manda al cliente.
_STAGE_MESSAGES: dict[str, str] = {
    "sanitize": (
        "No se pudo sanitizar la query; por privacidad (R4) se omitió la "
        "explicación con IA y se usaron explicaciones determinísticas."
    ),
    "parse": "No se pudo interpretar el plan de ejecución que devolvió Postgres.",
    "detect": "Falló el análisis de anti-patterns; no hay detecciones para esta query.",
    "recommend": (
        "Se detectó el anti-pattern pero falló la generación de " "recomendaciones de índice."
    ),
    "validate": (
        "No se pudo validar una recomendación en el sandbox; su veredicto de "
        "sandbox no está disponible."
    ),
    "explain": (
        "No se pudo generar la explicación enriquecida de una recomendación; "
        "se muestra la versión determinística."
    ),
}


# =====================================================================
# Registro de detectores
# =====================================================================
# Cada entrada: (código, función, accepts_sql).
# `accepts_sql` indica si el detector acepta el kwarg `sql=` (D9, D11,
# D19, D20, D21). Se detecta estáticamente aquí en vez de usar
# inspect.signature en cada llamada (más rápido, más legible).
#
# El código (C1, D2, …) coincide con el que usa motor.recommend() y
# con scripts/measure_coverage.py, para consistencia.
# =====================================================================

_DETECTORS: list[tuple[str, Any, bool]] = [
    ("C1", detect_seq_scan_on_large_table, False),
    ("D2", detect_stale_statistics, False),
    ("D3", detect_sort_spill_to_disk, False),
    ("D4", detect_like_leading_wildcard, False),
    ("D5", detect_function_in_where, False),
    ("D6", detect_or_across_tables, False),
    ("D7", detect_correlated_subquery, False),
    ("D8", detect_nested_loop_large_outer, False),
    ("D9", detect_select_star, True),
    ("D10", detect_missing_covering_index, False),
    ("D11", detect_type_mismatch, True),
    ("D12", detect_unnecessary_cte_materialize, False),
    ("D16", detect_missing_index, False),
    ("D17", detect_partial_index_opportunity, False),
    ("D18", detect_cardinality_misestimate, False),
    ("D19", detect_having_without_aggregate, True),
    ("D20", detect_in_subquery_to_exists, True),
    ("D21", detect_not_in_nullable_subquery, True),
    ("D22", detect_count_star_full_table, False),
]

# Códigos que tienen recomendador formal en motor.recommend().
_CODES_WITH_RECOMMENDER = frozenset({"C1", "D16", "D17", "D18"})

# Nombres humanos por código, para la detección serializada.
_DETECTOR_NAMES: dict[str, str] = {
    "C1": "seq_scan_on_large_table",
    "D2": "stale_statistics",
    "D3": "sort_spill_to_disk",
    "D4": "like_leading_wildcard",
    "D5": "function_in_where",
    "D6": "or_across_tables",
    "D7": "correlated_subquery",
    "D8": "nested_loop_large_outer",
    "D9": "select_star",
    "D10": "missing_covering_index",
    "D11": "type_mismatch",
    "D12": "unnecessary_cte_materialize",
    "D16": "missing_index",
    "D17": "partial_index_opportunity",
    "D18": "cardinality_misestimate",
    "D19": "having_without_aggregate",
    "D20": "in_subquery_to_exists",
    "D21": "not_in_nullable_subquery",
    "D22": "count_star_full_table",
}


def analyze_query(
    *,
    query: str,
    appdb_pool: ConnectionPool,
    snapshot: dict[str, Any],
    sandbox_pool: ConnectionPool | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Corre la pipeline completa y devuelve el dict que va al frontend.

    El shape devuelto coincide con el `AnalyzeResponse` del backend:
    `{"detections": [...], "recommendations": [...], "errors": [...],
    "partial": bool}`. Cuando ningún detector dispara, ambas listas son
    vacías y el endpoint responde 200 (no es un error que la query no
    tenga anti-patterns). `errors` lista las etapas que fallaron (E8) y
    `partial == bool(errors)`.

    Garantía E8: esta función no propaga excepciones salvo `AnalyzeError`
    (extracción fallida → status HTTP). Cualquier otro fallo de etapa se
    captura, se loggea, y se refleja en `errors`/`partial` sin tumbar la
    respuesta.

    `request_id` se propaga al log de C8 para correlación con el log de
    requests HTTP del backend (uvicorn / nginx).
    """
    errors: list[dict[str, str]] = []

    # --- Etapa: sanitizar (gate de R4 — si falla, el LLM se omite) -----
    sanitized: SanitizedQuery | None = None
    try:
        sanitized = sanitize(query)
    except Exception as exc:  # noqa: BLE001 — E8: aislamos la etapa
        _record(errors, "sanitize", exc)
        # `sanitized` queda None → las explicaciones usarán plantilla,
        # nunca el LLM (no podemos arriesgar mandarle literales).

    # --- Etapa: extracción (terminal — sin plan no hay nada que hacer) -
    raw_plan = _run_explain(appdb_pool, query)

    # --- Etapa: parser ------------------------------------------------
    try:
        plan = parse_explain(raw_plan)
    except Exception as exc:  # noqa: BLE001 — E8
        _record(errors, "parse", exc)
        return _result([], [], errors)

    # --- Etapa: detectores (todos, cada uno aislado por E8) -----------
    detections: dict[str, Detection] = {}
    detections_out: list[dict[str, Any]] = []

    for code, detector_fn, accepts_sql in _DETECTORS:
        try:
            if accepts_sql:
                detection = detector_fn(plan, snapshot, sql=query)
            else:
                detection = detector_fn(plan, snapshot)
        except Exception as exc:  # noqa: BLE001 — E8
            _record(errors, "detect", exc)
            continue

        if detection.found:
            detections[code] = detection
            detections_out.append(
                {
                    "type": _DETECTOR_NAMES.get(code, code),
                    "code": code,
                    "found": True,
                    "confidence": detection.confidence,
                    "evidence": _serialize_evidence(detection.evidence),
                }
            )

    if not detections:
        return _result([], [], errors)

    # --- Etapa: recomendador formal (C1, D16, D17, D18) ---------------
    formal_recs: list[Recommendation] = []
    try:
        formal_recs = list(recommend(detections, snapshot))
    except Exception as exc:  # noqa: BLE001 — E8
        _record(errors, "recommend", exc)

    recommendations_out: list[dict[str, Any]] = []

    # --- Procesar recomendaciones formales (con sandbox + LLM) --------
    for rec in formal_recs:
        sandbox_validation = _safe_sandbox_validate(sandbox_pool, snapshot, query, rec, errors)

        # Buscar la detección que generó esta recomendación para explain.
        # recommend() procesa C1, D16, D17, D18 — la tabla de la rec
        # coincide con alguno de esos detectores.
        det_for_explain = _find_detection_for_rec(rec, detections)

        explanation = _safe_explain(
            detection=det_for_explain,
            plan=plan,
            rec=rec,
            sanitized=sanitized,
            snapshot=snapshot,
            sandbox_pool=sandbox_pool,
            request_id=request_id,
            errors=errors,
        )
        recommendations_out.append(
            {
                "kind": rec.kind,
                "table": rec.table,
                "column": rec.column,
                "index_method": rec.index_method,
                "index_name": rec.index_name,
                "create_index_sql": rec.create_index_sql,
                "justification": rec.justification,
                "expected_impact": rec.expected_impact,
                "selectivity": rec.selectivity,
                "sandbox_verdict": _verdict_or_none(sandbox_validation),
                "sandbox_reason": _reason_or_none(sandbox_validation),
                "sandbox_plan_comparison": _plan_comparison_or_none(sandbox_validation),
                "explanation": {
                    "text": explanation.explanation,
                    "suggested_rewrite": explanation.suggested_rewrite,
                    "confidence": explanation.confidence,
                    "source": explanation.source,
                },
            }
        )

    # --- Procesar findings (detectores sin recomendador formal) -------
    for code, detection in sorted(detections.items()):
        if code in _CODES_WITH_RECOMMENDER:
            continue  # ya procesado arriba via recommend()

        finding = _build_finding(code, detection)
        recommendations_out.append(finding)

    return _result(detections_out, recommendations_out, errors)


# --- helpers privados ---------------------------------------------


def _find_detection_for_rec(
    rec: Recommendation,
    detections: dict[str, Detection],
) -> Detection:
    """Busca la Detection que generó una Recommendation formal.

    recommend() solo procesa C1, D16, D17, D18. Intentamos matchear
    por tabla en la evidencia; si no hay match claro, tomamos la primera
    detección de los códigos formales que haya disparado.
    """
    for code in ("C1", "D16", "D17", "D18"):
        det = detections.get(code)
        if det is None:
            continue
        for match in det.evidence.get("matches", []):
            if match.get("table") == rec.table:
                return det
    # Fallback: primera detección formal que exista
    for code in ("C1", "D16", "D17", "D18"):
        det = detections.get(code)
        if det is not None:
            return det
    # Absolutamente defensivo — no debería llegar aquí
    return Detection(found=True, confidence=0.5, evidence={"matches": []})


def _build_finding(code: str, detection: Detection) -> dict[str, Any]:
    """Construye una recomendación sintética `kind="finding"` para un
    detector sin recomendador formal.

    No pasa por sandbox ni por el LLM. La explicación se genera a partir
    de la evidencia del detector: suggested_rewrite, suggested_sql, o
    una descripción genérica del hallazgo.
    """
    matches = detection.evidence.get("matches", [])
    first = matches[0] if matches else {}

    # Tabla y columna del primer match (si los hay)
    table = first.get("table", first.get("from_table", ""))
    column = first.get("column", "")
    human_name = _DETECTOR_NAMES.get(code, code)

    # Buscar SQL sugerido en la evidencia del detector
    suggested_sql = (
        first.get("suggested_rewrite")
        or first.get("suggested_sql")
        or first.get("suggested_set_work_mem_sql")
        or first.get("suggested_create_index_sql")
        or ""
    )

    # Buscar alternativas sugeridas
    alternatives = first.get("suggested_alternatives")
    alternatives_text = ""
    if alternatives:
        if isinstance(alternatives, (list, tuple)):
            alternatives_text = " Alternativas: " + "; ".join(str(a) for a in alternatives)

    # Construir justificación a partir de la evidencia
    justification = _finding_justification(code, detection)

    explanation_text = (
        f"PgPilot detectó el anti-pattern '{human_name}' "
        f"(confianza {detection.confidence:.0%}). "
        f"{justification}"
        f"{alternatives_text}"
    )

    return {
        "kind": "finding",
        "code": code,
        "table": table,
        "column": column,
        "index_method": "",
        "index_name": "",
        "create_index_sql": suggested_sql,
        "justification": justification,
        "expected_impact": (
            "Revisar la query para corregir este anti-pattern. "
            "Consultar la evidencia del detector para más detalles."
        ),
        "selectivity": None,
        "sandbox_verdict": None,
        "sandbox_reason": None,
        "sandbox_plan_comparison": None,
        "explanation": {
            "text": explanation_text,
            "suggested_rewrite": first.get("suggested_rewrite"),
            "confidence": detection.confidence,
            "source": "template",
        },
    }


def _finding_justification(code: str, detection: Detection) -> str:
    """Genera una justificación legible para un finding según su código."""
    matches = detection.evidence.get("matches", [])
    first = matches[0] if matches else {}
    count = len(matches)

    justifications: dict[str, str] = {
        "D2": (
            f"Las estadísticas de la tabla {first.get('table', '?')} están "
            f"desactualizadas: el planner estimó {first.get('plan_rows', '?')} "
            f"filas pero se encontraron {first.get('actual_rows', '?')} "
            f"(ratio {first.get('ratio', '?')}x, dirección: "
            f"{first.get('direction', '?')}). Ejecutar ANALYZE."
        ),
        "D3": (
            f"El nodo Sort derramó a disco ({first.get('sort_space_type', 'Disk')}, "
            f"{first.get('sort_space_used_kb', '?')} KB). "
            f"Método: {first.get('sort_method', '?')}. "
            f"Considerar aumentar work_mem o crear un índice sobre la sort key."
        ),
        "D4": (
            f"Patrón LIKE con wildcard al inicio en la columna "
            f"'{first.get('column', '?')}' de {first.get('table', '?')}. "
            f"Este patrón impide el uso de índices btree regulares."
        ),
        "D5": (
            f"Función '{first.get('function', '?')}' aplicada sobre una columna "
            f"en el filtro WHERE de {first.get('table', '?')}. "
            f"Impide el uso de índices btree; considerar un índice funcional."
        ),
        "D6": (
            f"OR cruzando tablas/alias distintos en el filtro: "
            f"{', '.join(first.get('tables', []))}. "
            f"Considerar reescribir como UNION."
        ),
        "D7": (
            f"Subquery correlacionada (SubPlan) detectada: "
            f"{first.get('subplan_name', '?')}. "
            f"Se evalúa una vez por cada fila de la query externa. "
            f"Considerar reescribir como JOIN o EXISTS."
        ),
        "D8": (
            f"Nested Loop con outer grande: "
            f"{first.get('outer_rows', '?')} filas "
            f"({first.get('outer_rows_source', 'plan')}). "
            f"Considerar Hash Join o Merge Join."
        ),
        "D9": (
            f"SELECT * detectado sobre {first.get('table', '?')}. "
            + (
                "Hay oportunidad de Index Only Scan si se seleccionan solo "
                "las columnas necesarias."
                if first.get("index_only_candidate")
                else "Seleccionar solo las columnas necesarias mejora "
                "el rendimiento y la claridad."
            )
        ),
        "D10": (
            f"Index Scan sobre {first.get('table', '?')} "
            f"(índice {first.get('index_name', '?')}) con heap fetches. "
            f"Considerar un índice cubriente (INCLUDE) para pasar a Index Only Scan."
        ),
        "D11": (
            f"Cast implícito sobre la columna '{first.get('column', '?')}' "
            f"en {first.get('table', '?')} "
            f"(tipo: {first.get('cast_type', '?')}). "
            f"El cast impide el uso del índice {first.get('index_name', '?')}."
        ),
        "D12": (
            f"CTE '{first.get('cte_name', '?')}' materializada innecesariamente "
            f"(referenciada {first.get('reference_count', 1)} vez). "
            f"Agregar NOT MATERIALIZED para permitir inlining."
        ),
        "D19": (
            f"HAVING sin función de agregación sobre "
            f"{first.get('from_table', '?')}. "
            f"Mover el filtro a WHERE para reducir las filas antes de "
            f"la agregación."
        ),
        "D20": (
            f"IN (SELECT ...) no correlacionado detectado. "
            f"Tabla interna: {first.get('inner_table', '?')}. "
            f"Considerar reescribir como EXISTS para mejor rendimiento."
        ),
        "D21": (
            f"NOT IN con subquery sobre columna nullable: "
            f"'{first.get('inner_column', '?')}' de "
            f"{first.get('inner_table', '?')}. "
            f"Riesgo de bug silencioso (NULL trap). "
            f"Reescribir como NOT EXISTS."
        ),
        "D22": (
            f"count(*) sobre tabla completa "
            f"{first.get('table', '?')} "
            f"({first.get('estimated_rows', '?'):,} filas estimadas). "
            f"Considerar pg_class.reltuples para conteos aproximados."
            if isinstance(first.get("estimated_rows"), (int, float))
            else f"count(*) sobre tabla completa {first.get('table', '?')}. "
            f"Considerar pg_class.reltuples para conteos aproximados."
        ),
    }

    default = (
        f"Se encontraron {count} ocurrencia(s) del anti-pattern "
        f"'{_DETECTOR_NAMES.get(code, code)}'."
    )
    return justifications.get(code, default)


def _result(
    detections: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    """Empaqueta la respuesta con el flag de degradación parcial (E8)."""
    return {
        "detections": detections,
        "recommendations": recommendations,
        "errors": errors,
        "partial": bool(errors),
    }


def _record(errors: list[dict[str, str]], stage: str, exc: BaseException) -> None:
    """Loggea la excepción real (server-side) y agrega al payload un error
    *sin* detalles internos.

    Debe llamarse desde dentro de un bloque `except` (usa `log.exception`,
    que captura el traceback activo). El mensaje que ve el frontend sale
    de `_STAGE_MESSAGES` — nunca `str(exc)` (R: no filtrar nombres de
    tabla, paths, stack traces al cliente; misma política que
    `AnalyzeError`).
    """
    log.exception("Etapa '%s' del pipeline /analyze falló: %r", stage, exc)
    if any(e["stage"] == stage for e in errors):
        # Una etapa por-recomendación (validate/explain) puede fallar para
        # varias recomendaciones; el frontend solo necesita saberlo una vez.
        return
    errors.append(
        {
            "stage": stage,
            "message": _STAGE_MESSAGES.get(stage, "Una etapa del análisis falló."),
        }
    )


def _run_explain(pool: ConnectionPool, query: str) -> Any:
    """`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>` y devuelve el JSON.

    Traduce los errores de Postgres a `AnalyzeError` con status HTTP
    apropiado: read-only rechazado → 403, syntax/no existe → 400,
    timeout → 504, otros (incl. fallos inesperados del pool) → 500. Esto
    es lo único que el endpoint HTTP necesita atrapar — del resto se
    encarga la pipeline (E8 aísla cada etapa posterior).
    """
    explain_sql = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query
    try:
        with pool.connection() as conn:
            cur = conn.execute(explain_sql)
            row = cur.fetchone()
    except psycopg.errors.QueryCanceled as exc:
        raise AnalyzeError(504, f"EXPLAIN excedió el statement_timeout configurado: {exc}") from exc
    except psycopg.errors.ReadOnlySqlTransaction as exc:
        # R7: el usuario intentó mutar la BD. Rebote intencional.
        raise AnalyzeError(
            403,
            "PgPilot solo acepta queries de lectura (la conexión a AppDB es read-only por R7).",
        ) from exc
    except psycopg.errors.SyntaxError as exc:
        raise AnalyzeError(400, f"Postgres rechazó la query por sintaxis: {exc}") from exc
    except psycopg.Error as exc:
        # Otros errores de Postgres (tabla no existe, permiso denegado, etc.)
        # — traducimos a 400 porque casi siempre es input del usuario.
        raise AnalyzeError(400, f"Postgres rechazó la query: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — E8: nada de stack traces crudos
        # Fallo inesperado (timeout del pool, objeto roto, etc.): el detalle
        # se loggea; el cliente ve un 500 genérico, no la excepción interna.
        log.exception("Error inesperado ejecutando EXPLAIN contra AppDB: %r", exc)
        raise AnalyzeError(500, "Error inesperado al ejecutar EXPLAIN contra AppDB.") from exc

    if row is None:
        # No debería pasar — EXPLAIN siempre devuelve una fila — pero defensivo.
        raise AnalyzeError(500, "EXPLAIN no devolvió filas (estado inesperado).")
    return row[0]


def _safe_sandbox_validate(
    sandbox_pool: ConnectionPool | None,
    snapshot: dict[str, Any],
    query: str,
    rec: Any,
    errors: list[dict[str, str]],
) -> ValidationResult | None:
    """Llama a `validate_index_recommendation` cuando hay sandbox y atrapa
    cualquier excepción. Sandbox caído ≠ pipeline rota (R5 + E8).

    - `sandbox_pool is None` (sandbox no configurado) → `None`, sin error:
      es un modo de operación válido, no un fallo.
    - el sandbox existe pero explota → `None` + entrada `validate` en
      `errors` (degradación parcial visible para el frontend).
    """
    if sandbox_pool is None:
        return None
    try:
        return validate_index_recommendation(sandbox_pool, snapshot, query, rec)
    except Exception as exc:  # noqa: BLE001 — E8
        # No matamos el análisis por un sandbox flaky. El frontend verá
        # `sandbox_verdict=None`, `partial=True` y el error de la etapa.
        _record(errors, "validate", exc)
        return None


def _safe_explain(
    *,
    detection: Detection,
    plan: ExplainResult,
    rec: Any,
    sanitized: SanitizedQuery | None,
    snapshot: dict[str, Any],
    sandbox_pool: ConnectionPool | None,
    request_id: str | None,
    errors: list[dict[str, str]],
) -> Explanation:
    """Devuelve la `Explanation` de una recomendación aislando la etapa de
    explicación (LLM) — E8.

    `explain_recommendation` ya absorbe los fallos *esperables* del LLM
    (apagado, red caída, JSON inválido, cross-validation fallida) cayendo
    a plantilla. Lo que su docstring advierte que SÍ propaga ("bug
    interno, snapshot corrupto") se atrapa aquí: recordamos el error,
    caemos a plantilla, y si hasta eso falla devolvemos una explicación
    mínima — así las detecciones y recomendaciones determinísticas
    siempre llegan al frontend aunque el LLM (o su validación) explote.

    Si `sanitized is None` (la sanitización falló) NO se llama al LLM —
    R4 prohíbe mandarle la query con literales. Se va directo a plantilla.
    """
    if sanitized is not None:
        try:
            return explain_recommendation(
                detection,
                plan,
                rec,
                sanitized,
                snapshot=snapshot,
                sandbox_pool=sandbox_pool,
                request_id=request_id,
            )
        except Exception as exc:  # noqa: BLE001 — E8
            _record(errors, "explain", exc)

    # Respaldo determinístico (R5). Se llega aquí porque (a) la
    # sanitización falló y el LLM se omite por R4, o (b)
    # `explain_recommendation` explotó. Si hubo (b), `errors` ya tiene una
    # entrada "explain"; si hubo (a), tiene una entrada "sanitize" — no
    # duplicamos.
    try:
        return explain_from_template(detection, rec)
    except Exception as exc:  # noqa: BLE001 — E8
        log.exception("La plantilla de explicación también falló: %r", exc)
        return _fallback_explanation()


def _fallback_explanation() -> Explanation:
    """Explicación mínima de último recurso (cuando hasta la plantilla
    determinística falló). Apunta al usuario a los datos del motor, que
    siguen siendo válidos."""
    return Explanation(
        explanation=(
            "No se pudo generar la explicación de esta recomendación. "
            "Los datos del motor (SQL del índice, justificación e impacto "
            "estimado) siguen siendo válidos — revísalos en el detalle."
        ),
        suggested_rewrite=None,
        confidence=0.0,
        source="template",
    )


def _verdict_or_none(v: ValidationResult | None) -> str | None:
    return v.verdict if v else None


def _reason_or_none(v: ValidationResult | None) -> str | None:
    return v.reason if v else None


def _plan_comparison_or_none(
    v: ValidationResult | None,
) -> dict[str, Any] | None:
    """Empaqueta el contraste antes/después que el frontend usa para C11 + E7.

    `None` cuando no hubo validación de sandbox (pool ausente o explosión
    atrapada por R5/E8) o cuando la validación no produjo datos comparables
    (ej. `verdict="skipped_no_sandbox_signal"` sobre una recomendación
    de ANALYZE — `node_type_before/after` quedan `None`).

    El sub-objeto lleva, por corrida, el tipo de nodo de scan sobre la
    tabla, su `total_cost` y `plan_rows` (filas estimadas por el
    planner). El frontend (E7) deriva de aquí el resumen ejecutivo
    ("redujo costo estimado de X a Y (Zx mejora)") y la transición de
    tipo de nodo. No incluimos tiempos: el EXPLAIN del sandbox corre
    sin `ANALYZE` (tablas vacías por R6 — un `EXPLAIN ANALYZE` no
    informaría), así que no hay tiempo real que reportar.
    """
    if v is None:
        return None
    if v.node_type_before is None and v.node_type_after is None:
        return None
    return {
        "node_type_before": v.node_type_before,
        "node_type_after": v.node_type_after,
        "cost_before": v.cost_before,
        "cost_after": v.cost_after,
        "plan_rows_before": v.plan_rows_before,
        "plan_rows_after": v.plan_rows_after,
    }


def _serialize_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Vuelve a `dict` cualquier `Mapping` raro que C1 use (defensivo)
    para que la respuesta sea JSON-serializable. Hoy `evidence` ya es
    dict puro pero mantenemos la frontera explícita."""
    return {"matches": list(evidence.get("matches", []))}

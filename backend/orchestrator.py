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
4. **Detectar** anti-patterns con `motor.detect_seq_scan_on_large_table`
   (C1). Si no hay detección, devolvemos arrays vacíos (status 200).
5. **Recomendar** índices con `motor.recommend_for_seq_scan_on_large_table`
   (C2).
6. **Validar** cada recomendación en sandbox cuando hay `sandbox_pool`
   con `sandbox.validate_index_recommendation` (C3). Si el sandbox no
   está disponible, dejamos `sandbox_verdict=None` (no bloquea — el
   producto debe funcionar sin sandbox para Demo Day).
7. **Explicar** cada recomendación con `ia.explain_recommendation` (C4-C7),
   que internamente loggea via C8.

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

- **R1**: el motor decide. Sólo después de que C1 dispara llamamos al LLM.
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
    detect_seq_scan_on_large_table,
    parse_explain,
    recommend_for_seq_scan_on_large_table,
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
    "partial": bool}`. Cuando el detector no dispara, ambas listas son
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

    # --- Etapa: detector ---------------------------------------------
    try:
        detection = detect_seq_scan_on_large_table(plan, snapshot)
        if not detection.found:
            return _result([], [], errors)
        detections_out = [
            {
                "type": "seq_scan_on_large_table",
                "found": True,
                "confidence": detection.confidence,
                "evidence": _serialize_evidence(detection.evidence),
            }
        ]
    except Exception as exc:  # noqa: BLE001 — E8
        _record(errors, "detect", exc)
        return _result([], [], errors)

    # --- Etapa: recomendador -----------------------------------------
    try:
        recommendations = list(recommend_for_seq_scan_on_large_table(detection, snapshot))
    except Exception as exc:  # noqa: BLE001 — E8
        _record(errors, "recommend", exc)
        return _result(detections_out, [], errors)

    recommendations_out: list[dict[str, Any]] = []
    for rec in recommendations:
        # Etapas por-recomendación: validación de sandbox y explicación.
        # Cada una está aislada; el fallo de una no afecta a la otra ni a
        # las siguientes recomendaciones.
        sandbox_validation = _safe_sandbox_validate(sandbox_pool, snapshot, query, rec, errors)
        explanation = _safe_explain(
            detection=detection,
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

    return _result(detections_out, recommendations_out, errors)


# --- helpers privados ---------------------------------------------


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


def _plan_comparison_or_none(v: ValidationResult | None) -> dict[str, Any] | None:
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

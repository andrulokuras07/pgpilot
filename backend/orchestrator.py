"""Orquestador del endpoint /analyze — C9.

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

Reglas vivas:

- **R1**: el motor decide. Sólo después de que C1 dispara llamamos al LLM.
- **R3**: cada recomendación lleva su `sandbox_verdict` para que el
  frontend pueda mostrar la columna "validado por sandbox" en la
  tarjeta. Las explicaciones del LLM ya pasaron por cross-validation
  dentro de `explain_recommendation`.
- **R4**: el LLM solo recibe `sanitized_query`; AppDB recibe la query
  original.
- **R5**: si el LLM está apagado, sandbox no disponible, etc., la
  pipeline degrada elegante.
- **R7**: AppDB read-only (forzado por `/conector`). El usuario podría
  mandar `UPDATE` o `DROP`, pero la sesión lo rechaza.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from ia import explain_recommendation, sanitize
from motor import (
    detect_seq_scan_on_large_table,
    parse_explain,
    recommend_for_seq_scan_on_large_table,
)
from sandbox import ValidationResult, validate_index_recommendation


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


def analyze_query(
    *,
    query: str,
    appdb_pool: ConnectionPool,
    snapshot: dict[str, Any],
    sandbox_pool: ConnectionPool | None = None,
    request_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Corre la pipeline completa y devuelve el dict que va al frontend.

    El shape devuelto coincide con el `AnalyzeResponse` del backend
    (estable desde B13): `{"detections": [...], "recommendations": [...]}`.
    Cuando el detector no dispara, ambas listas son vacías y el endpoint
    responde 200 (no es un error que la query no tenga anti-patterns).

    `request_id` se propaga al log de C8 para correlación con el log de
    requests HTTP del backend (uvicorn / nginx).
    """
    sanitized = sanitize(query)
    raw_plan = _run_explain(appdb_pool, query)
    plan = parse_explain(raw_plan)

    detection = detect_seq_scan_on_large_table(plan, snapshot)
    if not detection.found:
        return {"detections": [], "recommendations": []}

    detections_out = [
        {
            "type": "seq_scan_on_large_table",
            "found": True,
            "confidence": detection.confidence,
            "evidence": _serialize_evidence(detection.evidence),
        }
    ]

    recommendations_out: list[dict[str, Any]] = []
    for rec in recommend_for_seq_scan_on_large_table(detection, snapshot):
        sandbox_validation = _safe_sandbox_validate(sandbox_pool, snapshot, query, rec)
        explanation = explain_recommendation(
            detection,
            plan,
            rec,
            sanitized,
            snapshot=snapshot,
            sandbox_pool=sandbox_pool,
            request_id=request_id,
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

    return {"detections": detections_out, "recommendations": recommendations_out}


# --- helpers privados ---------------------------------------------


def _run_explain(pool: ConnectionPool, query: str) -> Any:
    """`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>` y devuelve el JSON.

    Traduce los errores de Postgres a `AnalyzeError` con status HTTP
    apropiado: read-only rechazado → 403, syntax/no existe → 400,
    timeout → 504, otros → 500. Esto es lo único que el endpoint HTTP
    necesita atrapar — del resto se encarga la pipeline.
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

    if row is None:
        # No debería pasar — EXPLAIN siempre devuelve una fila — pero defensivo.
        raise AnalyzeError(500, "EXPLAIN no devolvió filas (estado inesperado).")
    return row[0]


def _safe_sandbox_validate(
    sandbox_pool: ConnectionPool | None,
    snapshot: dict[str, Any],
    query: str,
    rec: Any,
) -> ValidationResult | None:
    """Llama a `validate_index_recommendation` cuando hay sandbox y atrapa
    cualquier excepción. Sandbox caído ≠ pipeline rota (R5).
    """
    if sandbox_pool is None:
        return None
    try:
        return validate_index_recommendation(sandbox_pool, snapshot, query, rec)
    except Exception:
        # No matamos el análisis por un sandbox flaky. El frontend verá
        # `sandbox_verdict=None` y la prosa de la plantilla no
        # mencionará validación estructural.
        return None


def _verdict_or_none(v: ValidationResult | None) -> str | None:
    return v.verdict if v else None


def _reason_or_none(v: ValidationResult | None) -> str | None:
    return v.reason if v else None


def _plan_comparison_or_none(v: ValidationResult | None) -> dict[str, Any] | None:
    """Empaqueta el contraste antes/después que el frontend usa para C11 + E7.

    `None` cuando no hubo validación de sandbox (pool ausente o explosión
    atrapada por R5) o cuando la validación no produjo datos comparables
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

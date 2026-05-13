"""Tests del orquestador `backend.orchestrator.analyze_query` — C9.

Verifican la pipeline `query → EXPLAIN → detect → recomendar →
validar sandbox → explicar` sin levantar uvicorn ni AppDB. Las
dependencias externas (pool de AppDB, sandbox, LLM) se mockean.

El "hecho cuando" del backlog C9 ("POST a /analyze con una query con
seq scan devuelve un objeto con detección, recomendación validada, y
explicación del LLM") se cubre acá en su forma más fuerte: la pipeline
con un plan que dispara C1, snapshot con tabla grande, sandbox que
valida, LLM que responde válido → todos los campos llenos.

Actualizado para la arquitectura multi-detector: el orquestador ahora
corre los 18 detectores del motor, cada uno aislado (E8). Los tests
usan queries sin `SELECT *` para evitar que D9 dispare como ruido,
salvo cuando se quiere probar detección múltiple explícitamente.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import httpx
import psycopg
import pytest

from backend.orchestrator import AnalyzeError, _compute_validations, analyze_query

# --- fakes minimalistas --------------------------------------------


class _FakeCursor:
    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _FakeConnection:
    def __init__(self, behaviour: Any) -> None:
        self._behaviour = behaviour

    def execute(self, sql: str) -> _FakeCursor:
        if isinstance(self._behaviour, BaseException):
            raise self._behaviour
        if callable(self._behaviour):
            return _FakeCursor(self._behaviour(sql))
        return _FakeCursor(self._behaviour)


class FakePool:
    """Pool minimal con `connection()` como context manager. `behaviour`
    puede ser:
    - una row a devolver (lista/dict que `EXPLAIN` produciría)
    - un callable `(sql) -> row`
    - una excepción a lanzar al ejecutar.
    """

    def __init__(self, behaviour: Any) -> None:
        self._behaviour = behaviour

    @contextmanager
    def connection(self) -> Iterator[_FakeConnection]:
        yield _FakeConnection(self._behaviour)


# --- fixtures -------------------------------------------------------


SEQ_SCAN_PLAN = [
    {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 12345.0,
            "Plan Rows": 5000,
            "Plan Width": 50,
            "Filter": "(author_id = 42)",
            "Rows Removed by Filter": 495_000,
        }
    }
]

INDEX_SCAN_PLAN = [
    {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "posts",
            "Startup Cost": 0.0,
            "Total Cost": 8.5,
            "Plan Rows": 1,
            "Plan Width": 50,
            "Index Name": "posts_pkey",
            "Index Cond": "(id = 1)",
        }
    }
]


@pytest.fixture
def snapshot() -> dict[str, Any]:
    """Snapshot con `posts` grande e índice btree sobre `author_id`,
    para que C1 dispare 'índice presente pero ignorado' (escenario
    canónico de seq_scan_on_large_table)."""
    return {
        "schema": {
            "public.posts": {
                "schema": "public",
                "name": "posts",
                "columns": [
                    {"name": "id"},
                    {"name": "author_id"},
                    {"name": "title"},
                ],
                "indexes": [
                    {
                        "name": "posts_pkey",
                        "columns": ["id"],
                        "method": "btree",
                        "is_unique": True,
                        "is_primary": True,
                    },
                    {
                        "name": "idx_posts_author_id",
                        "columns": ["author_id"],
                        "method": "btree",
                        "is_unique": False,
                        "is_primary": False,
                    },
                ],
            }
        },
        "sizes": {
            "public.posts": {
                "estimated_rows": 500_000,
                "total_bytes": 100_000_000,
                "category": "large",
            }
        },
        "stats": {
            "public.posts": {
                "author_id": {
                    "has_stats": True,
                    "n_distinct": 1000.0,
                    "null_frac": 0.0,
                    "most_common_vals": None,
                    "correlation": 0.1,
                }
            }
        },
    }


@pytest.fixture
def disable_llm(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Desactiva el LLM y manda los logs C8 a tmp_path para no
    contaminar `logs/`. Aplica a TODOS los tests de este archivo."""
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("PGPILOT_LLM_LOG_PATH", str(tmp_path / "log.jsonl"))


@pytest.fixture(autouse=True)
def _autouse_disable_llm(disable_llm: None) -> None:
    return None


# --- happy path: no detection -------------------------------------


def test_analyze_query_sin_deteccion_devuelve_arrays_vacios(
    snapshot: dict[str, Any],
) -> None:
    """Query con Index Scan y sin SELECT * → ningún detector dispara."""
    pool = FakePool(INDEX_SCAN_PLAN)

    out = analyze_query(
        query="SELECT id FROM posts WHERE id = 1",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    # E8: shape estable con `errors`/`partial`. Sin fallos → ambos vacíos.
    assert out == {
        "detections": [],
        "recommendations": [],
        "errors": [],
        "partial": False,
    }


# --- happy path: detection + recommendation + explanation ---------


def test_analyze_query_con_deteccion_devuelve_estructura_completa(
    snapshot: dict[str, Any],
) -> None:
    """**C9 hecho-cuando**: query con seq scan → detección, recomendación
    validada, explicación. Sin LLM (LLM_ENABLED=false), la prosa viene de
    plantilla — sigue cumpliendo el contrato.

    Usa query sin SELECT * para aislar solo C1."""
    pool = FakePool(SEQ_SCAN_PLAN)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    # Detección — solo C1 dispara con esta query
    assert len(out["detections"]) == 1
    det = out["detections"][0]
    assert det["type"] == "seq_scan_on_large_table"
    assert det["code"] == "C1"
    assert det["found"] is True
    assert det["confidence"] == 1.0
    assert det["evidence"]["matches"][0]["table"] == "public.posts"

    # Recomendación formal (C1 → analyze, porque el índice ya existe)
    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert len(formal_recs) == 1
    rec = formal_recs[0]
    assert rec["kind"] == "analyze"  # índice ya existe → ANALYZE, no CREATE
    assert rec["table"] == "public.posts"
    assert rec["column"] == "author_id"
    assert rec["index_method"] == "btree"
    assert rec["create_index_sql"]
    assert rec["selectivity"] is not None
    assert "justification" in rec
    assert "expected_impact" in rec

    # Sin sandbox_pool → verdict null y sin comparativo C11
    assert rec["sandbox_verdict"] is None
    assert rec["sandbox_reason"] is None
    assert rec["sandbox_plan_comparison"] is None

    # Explanation (sin LLM → plantilla)
    assert rec["explanation"]["source"] == "template"
    assert "public.posts" in rec["explanation"]["text"]
    assert rec["explanation"]["confidence"] > 0.0
    assert rec["explanation"]["suggested_rewrite"] is None

    # E8: pipeline completa, sin etapas caídas.
    assert out["errors"] == []
    assert out["partial"] is False


def test_analyze_query_multiple_detectores_disparan(
    snapshot: dict[str, Any],
) -> None:
    """Query con SELECT * + Seq Scan dispara C1 y D9. Verifica que el
    orquestador emite ambas detecciones y combina recomendaciones
    formales (C1) con findings (D9)."""
    pool = FakePool(SEQ_SCAN_PLAN)

    out = analyze_query(
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    # Al menos C1 y D9 deben disparar
    codes = {d["code"] for d in out["detections"]}
    assert "C1" in codes
    assert "D9" in codes

    # Debe haber recomendaciones formales Y findings
    kinds = {r["kind"] for r in out["recommendations"]}
    assert "analyze" in kinds or "create_index" in kinds  # formal de C1
    assert "finding" in kinds  # D9 sin recomendador → finding


def test_analyze_query_con_sandbox_incluye_verdict(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Cuando hay sandbox_pool, el orquestador llama
    `validate_index_recommendation` y propaga el verdict al payload."""
    pool = FakePool(SEQ_SCAN_PLAN)

    # Mockeamos validate_index_recommendation para no levantar Docker.
    from sandbox import ValidationResult

    def fake_validate(*args: Any, **kwargs: Any) -> ValidationResult:
        return ValidationResult(
            verdict="validated",
            reason="el índice btree(author_id) reduce Seq Scan a Index Scan en el sandbox.",
            node_type_before="Seq Scan",
            node_type_after="Index Scan",
            cost_before=12345.0,
            cost_after=42.0,
            plan_rows_before=500_000,
            plan_rows_after=2_500,
        )

    monkeypatch.setattr("backend.orchestrator.validate_index_recommendation", fake_validate)

    sentinel_sandbox = object()

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
        sandbox_pool=sentinel_sandbox,
    )

    # First formal recommendation (C1)
    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert len(formal_recs) >= 1
    rec = formal_recs[0]
    assert rec["sandbox_verdict"] == "validated"
    assert "Index Scan" in rec["sandbox_reason"]

    # C11 + E7: el comparativo lleva tipos de nodo, costos y filas
    # estimadas para que el frontend pueda renderizar "Seq Scan
    # (cost=12345, ~500k filas) → Index Scan (cost=42, ~2.5k filas)" y
    # derivar el resumen ejecutivo.
    comparison = rec["sandbox_plan_comparison"]
    assert comparison is not None
    assert comparison["node_type_before"] == "Seq Scan"
    assert comparison["node_type_after"] == "Index Scan"
    assert comparison["cost_before"] == 12345.0
    assert comparison["cost_after"] == 42.0
    assert comparison["plan_rows_before"] == 500_000
    assert comparison["plan_rows_after"] == 2_500


def test_analyze_query_sandbox_skipped_no_signal_no_emite_comparison(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Cuando el sandbox devuelve `skipped_no_sandbox_signal` (caso ANALYZE
    sobre tablas vacías), `node_type_before/after` son `None` y no hay
    comparativo C11 que mostrar — el frontend renderea sin el panel."""
    pool = FakePool(SEQ_SCAN_PLAN)

    from sandbox import ValidationResult

    def fake_validate(*args: Any, **kwargs: Any) -> ValidationResult:
        return ValidationResult(
            verdict="skipped_no_sandbox_signal",
            reason="recomendación ANALYZE no es validable en sandbox.",
            node_type_before=None,
            node_type_after=None,
            cost_before=None,
            cost_after=None,
        )

    monkeypatch.setattr("backend.orchestrator.validate_index_recommendation", fake_validate)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
        sandbox_pool=object(),
    )

    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert len(formal_recs) >= 1
    rec = formal_recs[0]
    assert rec["sandbox_verdict"] == "skipped_no_sandbox_signal"
    assert rec["sandbox_plan_comparison"] is None


def test_analyze_query_sandbox_que_explota_no_rompe_la_pipeline(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Si el sandbox falla (Docker caído, schema corrupto), la pipeline
    sigue: `sandbox_verdict=None`, status 200, y E8 marca la etapa
    `validate` en `errors` con `partial=True`. R5 + E8 a nivel sandbox."""
    pool = FakePool(SEQ_SCAN_PLAN)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("sandbox docker is down")

    monkeypatch.setattr("backend.orchestrator.validate_index_recommendation", boom)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
        sandbox_pool=object(),  # truthy → activa el path
    )

    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert len(formal_recs) >= 1
    assert formal_recs[0]["sandbox_verdict"] is None
    assert formal_recs[0]["sandbox_reason"] is None
    assert formal_recs[0]["sandbox_plan_comparison"] is None

    # E8: degradación parcial visible, pero la detección y la recomendación
    # determinística siguen presentes (con su explicación).
    assert out["partial"] is True
    assert "validate" in [e["stage"] for e in out["errors"]]
    assert len(out["detections"]) >= 1
    assert formal_recs[0]["create_index_sql"]
    assert formal_recs[0]["explanation"]["text"]


def test_analyze_query_sandbox_no_configurado_no_es_error(
    snapshot: dict[str, Any],
) -> None:
    """Sin `sandbox_pool` (modo válido por R5), no hay verdict pero
    tampoco hay error de etapa: `partial=False`, `errors=[]`."""
    pool = FakePool(SEQ_SCAN_PLAN)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
        sandbox_pool=None,
    )

    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert formal_recs[0]["sandbox_verdict"] is None
    assert out["errors"] == []
    assert out["partial"] is False


# --- happy path: con LLM (mockeado) -------------------------------


def test_analyze_query_con_llm_real_mockeado_marca_source_llm(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Si `LLM_ENABLED=true` y la API key existe, la prosa de la
    explicación viene del LLM (con `source="llm"`). Verifica que el
    orquestador propaga la `Explanation` con su source."""
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "explanation": "Plan tiene Seq Scan sobre 500k filas.",
                                "suggested_rewrite": None,
                                "confidence": 0.88,
                            }
                        ),
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    pool = FakePool(SEQ_SCAN_PLAN)
    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert len(formal_recs) >= 1
    rec = formal_recs[0]
    assert rec["explanation"]["source"] == "llm"
    assert "Seq Scan" in rec["explanation"]["text"]
    assert rec["explanation"]["confidence"] == 0.88


# --- E8: aislamiento de errores por etapa -------------------------


def test_analyze_query_llm_que_explota_devuelve_deterministico_y_flag(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """**E8 hecho-cuando**: si el LLM (la etapa de explicación) revienta de
    forma inesperada, /analyze sigue devolviendo la detección y la
    recomendación determinística — con la explicación de plantilla como
    respaldo — más `partial=True` y la etapa `explain` en `errors`.
    """
    pool = FakePool(SEQ_SCAN_PLAN)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the LLM layer blew up unexpectedly")

    # Rompemos la etapa de explicación entera (no un error 'esperable' del
    # LLM, que `explain_recommendation` ya absorbe — un bug crudo).
    monkeypatch.setattr("backend.orchestrator.explain_recommendation", boom)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    # Lo determinístico sobrevive intacto.
    assert len(out["detections"]) >= 1
    c1_dets = [d for d in out["detections"] if d["code"] == "C1"]
    assert len(c1_dets) == 1
    assert c1_dets[0]["type"] == "seq_scan_on_large_table"

    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert len(formal_recs) >= 1
    rec = formal_recs[0]
    assert rec["create_index_sql"]
    assert rec["justification"]
    assert rec["expected_impact"]
    # La explicación cae a plantilla (R5) en vez de propagar la excepción.
    assert rec["explanation"]["source"] == "template"
    assert rec["explanation"]["text"]
    # Flag de degradación parcial.
    assert out["partial"] is True
    assert "explain" in [e["stage"] for e in out["errors"]]
    # El mensaje al frontend es genérico (no filtra el detalle interno).
    explain_errors = [e for e in out["errors"] if e["stage"] == "explain"]
    assert "blew up" not in explain_errors[0]["message"]


def test_analyze_query_parser_que_explota_devuelve_vacio_con_flag(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Si el parser del plan revienta, no hay nada que detectar: arrays
    vacíos + `partial=True` + etapa `parse` en `errors`. No crashea."""
    pool = FakePool(SEQ_SCAN_PLAN)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("plan JSON has an unexpected shape")

    monkeypatch.setattr("backend.orchestrator.parse_explain", boom)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    assert out["detections"] == []
    assert out["recommendations"] == []
    assert out["partial"] is True
    assert [e["stage"] for e in out["errors"]] == ["parse"]


def test_analyze_query_un_detector_que_explota_no_mata_a_los_demas(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """E8 por detector: si C1 explota, los demás detectores siguen
    corriendo. Con SELECT *, D9 debería disparar normalmente aunque
    C1 haya fallado. El error de C1 aparece en `errors`."""
    pool = FakePool(SEQ_SCAN_PLAN)

    import backend.orchestrator as orch

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("detector hit a corrupt snapshot")

    # Reemplazar solo C1 en _DETECTORS (las refs se capturan al import)
    patched = [(code, boom if code == "C1" else fn, sql) for code, fn, sql in orch._DETECTORS]
    monkeypatch.setattr(orch, "_DETECTORS", patched)

    out = analyze_query(
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    # C1 falló pero D9 debería haber disparado (SELECT *)
    assert out["partial"] is True
    assert "detect" in [e["stage"] for e in out["errors"]]

    # D9 sigue viva — hay al menos una detección
    codes = {d["code"] for d in out["detections"]}
    assert "D9" in codes
    assert "C1" not in codes  # C1 explotó, no debería estar


def test_analyze_query_todos_detectores_explotan_devuelve_vacio(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Si TODOS los detectores explotan, no hay detecciones: arrays
    vacíos + partial=True + detect en errors."""
    pool = FakePool(SEQ_SCAN_PLAN)

    import backend.orchestrator as orch

    # Reemplazar _DETECTORS con una lista donde todo explota
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("everything is broken")

    broken_detectors = [(code, boom, sql) for code, _, sql in orch._DETECTORS]
    monkeypatch.setattr(orch, "_DETECTORS", broken_detectors)

    out = analyze_query(
        query="SELECT id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    assert out["detections"] == []
    assert out["recommendations"] == []
    assert out["partial"] is True
    assert "detect" in [e["stage"] for e in out["errors"]]


def test_analyze_query_recomendador_que_explota_mantiene_deteccion(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Si el recomendador revienta, la detección sobrevive pero no hay
    recomendaciones formales: `partial=True` + etapa `recommend`.
    Los findings de detectores sin recomendador sí aparecen."""
    pool = FakePool(SEQ_SCAN_PLAN)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("recommender failed to compute selectivity")

    monkeypatch.setattr("backend.orchestrator.recommend", boom)

    out = analyze_query(
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    assert len(out["detections"]) >= 1
    # Formal recs vacías (recommend() explotó)
    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert formal_recs == []
    # Findings de D9 etc. sí aparecen (no dependen del recomendador)
    findings = [r for r in out["recommendations"] if r["kind"] == "finding"]
    assert len(findings) >= 1  # al menos D9
    assert out["partial"] is True
    assert "recommend" in [e["stage"] for e in out["errors"]]


def test_analyze_query_sanitize_que_explota_omite_llm_pero_sigue(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Si la sanitización revienta, NO se llama al LLM (R4 — no podemos
    arriesgar mandarle literales): las explicaciones caen a plantilla y
    la etapa `sanitize` aparece en `errors`. La detección/recomendación
    determinística sigue presente."""
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    llm_calls: list[Any] = []

    def fake_post(*args: Any, **kwargs: Any) -> Any:
        llm_calls.append((args, kwargs))
        raise AssertionError("el LLM no debe llamarse si la sanitización falló")

    monkeypatch.setattr(httpx, "post", fake_post)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("sanitizer regex exploded")

    monkeypatch.setattr("backend.orchestrator.sanitize", boom)

    pool = FakePool(SEQ_SCAN_PLAN)
    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    assert llm_calls == []  # R4: el LLM jamás se tocó
    assert len(out["detections"]) >= 1
    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    assert len(formal_recs) >= 1
    rec = formal_recs[0]
    assert rec["create_index_sql"]
    assert rec["explanation"]["source"] == "template"
    assert out["partial"] is True
    assert "sanitize" in [e["stage"] for e in out["errors"]]


# --- findings (detectores sin recomendador) ------------------------


def test_finding_tiene_estructura_correcta(
    snapshot: dict[str, Any],
) -> None:
    """Un finding (detector sin recomendador) tiene los campos necesarios
    para que el frontend lo rendere sin romperse."""
    pool = FakePool(SEQ_SCAN_PLAN)

    out = analyze_query(
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    findings = [r for r in out["recommendations"] if r["kind"] == "finding"]
    assert len(findings) >= 1  # al menos D9 por SELECT *

    f = findings[0]
    # Campos que el frontend espera
    assert "kind" in f
    assert "table" in f
    assert "column" in f
    assert "create_index_sql" in f  # puede estar vacío
    assert "justification" in f
    assert "expected_impact" in f
    assert "selectivity" in f  # None para findings
    assert "sandbox_verdict" in f  # None para findings
    assert "sandbox_plan_comparison" in f  # None para findings
    assert "explanation" in f
    assert f["explanation"]["source"] == "template"
    assert f["explanation"]["text"]  # no vacío
    assert f["sandbox_verdict"] is None
    assert f["sandbox_plan_comparison"] is None


# --- mapeo de errores Postgres → AnalyzeError ----------------------


def test_run_explain_traduce_syntax_error_a_400(snapshot: dict[str, Any]) -> None:
    pool = FakePool(psycopg.errors.SyntaxError("syntax error at or near 'FROOM'"))

    with pytest.raises(AnalyzeError) as exc_info:
        analyze_query(query="SELECT * FROOM posts", appdb_pool=pool, snapshot=snapshot)

    assert exc_info.value.status_code == 400
    assert "sintaxis" in exc_info.value.message.lower()


def test_run_explain_traduce_read_only_a_403(snapshot: dict[str, Any]) -> None:
    pool = FakePool(psycopg.errors.ReadOnlySqlTransaction("cannot execute UPDATE"))

    with pytest.raises(AnalyzeError) as exc_info:
        analyze_query(query="UPDATE posts SET x=1", appdb_pool=pool, snapshot=snapshot)

    assert exc_info.value.status_code == 403
    assert "read-only" in exc_info.value.message.lower()


def test_run_explain_traduce_query_canceled_a_504(snapshot: dict[str, Any]) -> None:
    pool = FakePool(psycopg.errors.QueryCanceled("canceling statement due to statement timeout"))

    with pytest.raises(AnalyzeError) as exc_info:
        analyze_query(query="SELECT pg_sleep(99)", appdb_pool=pool, snapshot=snapshot)

    assert exc_info.value.status_code == 504


def test_run_explain_traduce_otro_psycopg_error_a_400(snapshot: dict[str, Any]) -> None:
    pool = FakePool(psycopg.errors.UndefinedTable("relation 'inexistente' does not exist"))

    with pytest.raises(AnalyzeError) as exc_info:
        analyze_query(query="SELECT * FROM inexistente", appdb_pool=pool, snapshot=snapshot)

    assert exc_info.value.status_code == 400


def test_run_explain_sin_filas_levanta_500(snapshot: dict[str, Any]) -> None:
    pool = FakePool(None)  # cur.fetchone() → None

    with pytest.raises(AnalyzeError) as exc_info:
        analyze_query(query="SELECT 1", appdb_pool=pool, snapshot=snapshot)

    assert exc_info.value.status_code == 500


def test_run_explain_error_inesperado_traduce_a_500(snapshot: dict[str, Any]) -> None:
    """E8: un fallo NO-Postgres en la extracción (pool roto, timeout del
    pool, etc.) no propaga un stack trace crudo — se traduce a un 500
    genérico, igual que el resto de la etapa de extracción."""
    pool = FakePool(RuntimeError("connection pool is broken"))

    with pytest.raises(AnalyzeError) as exc_info:
        analyze_query(query="SELECT 1", appdb_pool=pool, snapshot=snapshot)

    assert exc_info.value.status_code == 500
    assert "broken" not in exc_info.value.message  # no filtra el detalle interno


# --- E9: 4 indicadores de validación R3 por recomendación ---------


def test_validations_analyze_pasa_schema_y_sintaxis_sandbox_na(
    snapshot: dict[str, Any],
) -> None:
    """E9 hecho-cuando — caso ANALYZE (índice ya existe, sin sandbox).

    La tarjeta debe llevar las 4 validaciones. Para ANALYZE,
    ``no_duplicate_index`` y ``sandbox_improves`` son N/A por
    construcción; ``schema_ok`` y ``syntax_valid`` deben pasar.
    """
    pool = FakePool(SEQ_SCAN_PLAN)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    formal_recs = [r for r in out["recommendations"] if r["kind"] != "finding"]
    rec = formal_recs[0]
    assert rec["kind"] == "analyze"

    validations = rec["validations"]
    assert set(validations) == {
        "schema_ok",
        "no_duplicate_index",
        "syntax_valid",
        "sandbox_improves",
    }
    assert validations["schema_ok"] is True
    assert validations["syntax_valid"] is True
    assert validations["no_duplicate_index"] is None  # ANALYZE no propone índice nuevo
    assert validations["sandbox_improves"] is None  # sin sandbox configurado


def test_validations_sandbox_validated_marca_improves_true(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Con sandbox que valida (Seq Scan → Index Scan), el indicador #4
    queda en True."""
    pool = FakePool(SEQ_SCAN_PLAN)

    from sandbox import ValidationResult

    def fake_validate(*args: Any, **kwargs: Any) -> ValidationResult:
        return ValidationResult(
            verdict="validated",
            reason="cambió a Index Scan",
            node_type_before="Seq Scan",
            node_type_after="Index Scan",
            cost_before=12345.0,
            cost_after=42.0,
            plan_rows_before=500_000,
            plan_rows_after=2_500,
        )

    monkeypatch.setattr("backend.orchestrator.validate_index_recommendation", fake_validate)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
        sandbox_pool=object(),
    )

    rec = [r for r in out["recommendations"] if r["kind"] != "finding"][0]
    assert rec["validations"]["sandbox_improves"] is True


def test_validations_sandbox_discarded_marca_improves_false(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Cuando el sandbox descarta (planner ignora el cambio), el
    indicador #4 queda en False — el frontend pintaría el indicador rojo
    y el usuario sabe que la recomendación NO se confirmó."""
    pool = FakePool(SEQ_SCAN_PLAN)

    from sandbox import ValidationResult

    def fake_validate(*args: Any, **kwargs: Any) -> ValidationResult:
        return ValidationResult(
            verdict="discarded",
            reason="planner siguió en Seq Scan",
            node_type_before="Seq Scan",
            node_type_after="Seq Scan",
            cost_before=12345.0,
            cost_after=12345.0,
            plan_rows_before=500_000,
            plan_rows_after=500_000,
        )

    monkeypatch.setattr("backend.orchestrator.validate_index_recommendation", fake_validate)

    out = analyze_query(
        query="SELECT id, author_id FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
        sandbox_pool=object(),
    )

    rec = [r for r in out["recommendations"] if r["kind"] != "finding"][0]
    assert rec["validations"]["sandbox_improves"] is False


def test_validations_findings_tambien_llevan_los_4_indicadores(
    snapshot: dict[str, Any],
) -> None:
    """Cada tarjeta de recomendación (formal o finding) debe llevar
    el bloque ``validations`` con las 4 claves. Para findings sin
    índice propuesto, ``no_duplicate_index`` y ``sandbox_improves`` son
    N/A (None)."""
    pool = FakePool(SEQ_SCAN_PLAN)

    out = analyze_query(
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    findings = [r for r in out["recommendations"] if r["kind"] == "finding"]
    assert findings, "Esperaba al menos un finding (D9 select_star)"
    for finding in findings:
        validations = finding["validations"]
        assert set(validations) == {
            "schema_ok",
            "no_duplicate_index",
            "syntax_valid",
            "sandbox_improves",
        }
        # findings no proponen CREATE INDEX → indicador #2 siempre N/A
        assert validations["no_duplicate_index"] is None
        # findings no pasan por sandbox → indicador #4 siempre N/A
        assert validations["sandbox_improves"] is None


def test_compute_validations_directo_cubre_casos_de_falla() -> None:
    """Tests directos del helper para los casos que el motor no produce
    naturalmente (índice duplicado, SQL roto, tabla fuera del snapshot).

    Los tests anteriores cubren los casos felices vía la pipeline real;
    estos cubren las ramas negativas — críticas para que la UI marque
    rojo cuando una recomendación NO debería mostrarse.
    """
    snapshot = {
        "schema": {
            "public.posts": {
                "schema": "public",
                "name": "posts",
                "columns": [{"name": "id"}, {"name": "author_id"}],
                "indexes": [
                    {
                        "name": "idx_posts_author_id",
                        "columns": ["author_id"],
                        "method": "btree",
                        "is_unique": False,
                        "is_primary": False,
                    }
                ],
            }
        },
    }

    # 1. Índice duplicado → no_duplicate_index=False (rojo)
    rec_duplicado = {
        "kind": "create_index",
        "table": "public.posts",
        "column": "author_id",
        "index_method": "btree",
        "create_index_sql": "CREATE INDEX idx_posts_author_id_v2 ON public.posts (author_id);",
    }
    validations = _compute_validations(rec_duplicado, snapshot, sandbox_verdict=None)
    assert validations["schema_ok"] is True
    assert validations["no_duplicate_index"] is False
    assert validations["syntax_valid"] is True

    # 2. SQL sintácticamente inválido → syntax_valid=False (rojo)
    rec_sql_roto = {
        "kind": "create_index",
        "table": "public.posts",
        "column": "id",
        "index_method": "btree",
        "create_index_sql": "CREATE !! INDEX rota ON public.posts (",
    }
    validations = _compute_validations(rec_sql_roto, snapshot, sandbox_verdict=None)
    assert validations["syntax_valid"] is False

    # 3. Tabla no existe en el snapshot → schema_ok=False (rojo)
    rec_tabla_fantasma = {
        "kind": "create_index",
        "table": "public.no_existe",
        "column": "x",
        "index_method": "btree",
        "create_index_sql": "CREATE INDEX foo ON public.no_existe (x);",
    }
    validations = _compute_validations(rec_tabla_fantasma, snapshot, sandbox_verdict=None)
    assert validations["schema_ok"] is False

    # 4. Columna no existe en el snapshot → schema_ok=False (rojo)
    rec_col_fantasma = {
        "kind": "create_index",
        "table": "public.posts",
        "column": "no_existe",
        "index_method": "btree",
        "create_index_sql": "CREATE INDEX foo ON public.posts (no_existe);",
    }
    validations = _compute_validations(rec_col_fantasma, snapshot, sandbox_verdict=None)
    assert validations["schema_ok"] is False

    # 5. sandbox_verdict="skipped_no_sandbox_signal" → sandbox_improves=None (N/A)
    rec_skipped = {
        "kind": "analyze",
        "table": "public.posts",
        "column": "author_id",
        "create_index_sql": "ANALYZE public.posts;",
    }
    validations = _compute_validations(
        rec_skipped, snapshot, sandbox_verdict="skipped_no_sandbox_signal"
    )
    assert validations["sandbox_improves"] is None

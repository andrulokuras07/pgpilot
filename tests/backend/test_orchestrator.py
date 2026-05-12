"""Tests del orquestador `backend.orchestrator.analyze_query` — C9.

Verifican la pipeline `query → EXPLAIN → detect → recomendar →
validar sandbox → explicar` sin levantar uvicorn ni AppDB. Las
dependencias externas (pool de AppDB, sandbox, LLM) se mockean.

El "hecho cuando" del backlog C9 ("POST a /analyze con una query con
seq scan devuelve un objeto con detección, recomendación validada, y
explicación del LLM") se cubre acá en su forma más fuerte: la pipeline
con un plan que dispara C1, snapshot con tabla grande, sandbox que
valida, LLM que responde válido → todos los campos llenos.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import httpx
import psycopg
import pytest

from backend.orchestrator import AnalyzeError, analyze_query

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
    pool = FakePool(INDEX_SCAN_PLAN)

    out = analyze_query(
        query="SELECT * FROM posts WHERE id = 1", appdb_pool=pool, snapshot=snapshot
    )

    assert out == {"detections": [], "recommendations": []}


# --- happy path: detection + recommendation + explanation ---------


def test_analyze_query_con_deteccion_devuelve_estructura_completa(
    snapshot: dict[str, Any],
) -> None:
    """**C9 hecho-cuando**: query con seq scan → detección, recomendación
    validada, explicación. Sin LLM (LLM_ENABLED=false), la prosa viene de
    plantilla — sigue cumpliendo el contrato."""
    pool = FakePool(SEQ_SCAN_PLAN)

    out = analyze_query(
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    # Detección
    assert len(out["detections"]) == 1
    det = out["detections"][0]
    assert det["type"] == "seq_scan_on_large_table"
    assert det["found"] is True
    assert det["confidence"] == 1.0
    assert det["evidence"]["matches"][0]["table"] == "public.posts"

    # Recomendación con todos los campos contractuales
    assert len(out["recommendations"]) == 1
    rec = out["recommendations"][0]
    assert rec["kind"] == "analyze"  # índice ya existe → ANALYZE, no CREATE
    assert rec["table"] == "public.posts"
    assert rec["column"] == "author_id"
    assert rec["index_method"] == "btree"
    assert rec["create_index_sql"]
    assert rec["selectivity"] is not None
    assert "justification" in rec
    assert "expected_impact" in rec

    # Sin sandbox_pool → verdict null
    assert rec["sandbox_verdict"] is None
    assert rec["sandbox_reason"] is None

    # Explanation (sin LLM → plantilla)
    assert rec["explanation"]["source"] == "template"
    assert "public.posts" in rec["explanation"]["text"]
    assert rec["explanation"]["confidence"] > 0.0
    assert rec["explanation"]["suggested_rewrite"] is None


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
        )

    monkeypatch.setattr("backend.orchestrator.validate_index_recommendation", fake_validate)

    sentinel_sandbox = object()

    out = analyze_query(
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
        sandbox_pool=sentinel_sandbox,
    )

    rec = out["recommendations"][0]
    assert rec["sandbox_verdict"] == "validated"
    assert "Index Scan" in rec["sandbox_reason"]


def test_analyze_query_sandbox_que_explota_no_rompe_la_pipeline(
    monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    """Si el sandbox falla (Docker caído, schema corrupto), la pipeline
    sigue: `sandbox_verdict=None`, status 200. R5 a nivel sandbox."""
    pool = FakePool(SEQ_SCAN_PLAN)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("sandbox docker is down")

    monkeypatch.setattr("backend.orchestrator.validate_index_recommendation", boom)

    out = analyze_query(
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
        sandbox_pool=object(),  # truthy → activa el path
    )

    assert len(out["recommendations"]) == 1
    assert out["recommendations"][0]["sandbox_verdict"] is None
    assert out["recommendations"][0]["sandbox_reason"] is None


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
        query="SELECT * FROM posts WHERE author_id = 42",
        appdb_pool=pool,
        snapshot=snapshot,
    )

    rec = out["recommendations"][0]
    assert rec["explanation"]["source"] == "llm"
    assert "Seq Scan" in rec["explanation"]["text"]
    assert rec["explanation"]["confidence"] == 0.88


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

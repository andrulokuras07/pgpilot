"""Tests del logger estructurado de interacciones LLM — C8.

Cubren:

- Helpers puros (`build_base_record`, `llm_payload`, `final_shown_payload`).
- Persistencia: `log_llm_interaction` escribe JSON line, crea directorio
  padre, agrega timestamp.
- Toggle por entorno: `PGPILOT_LLM_LOG_DISABLED=true` apaga el logger.
- Resiliencia: si el path es inválido, `log_llm_interaction` devuelve
  `None` sin propagar OSError (criterio R5: el log no rompe pipeline).
- Integración con `explain_recommendation`: cada outcome (llm_ok,
  llm_disabled, llm_error, llm_invalid_response, cross_validation_failed)
  produce su línea correspondiente.

El "hecho cuando" del backlog C8 ("después de un análisis, existe un
log JSON con todos los campos") se verifica al final, en el test de
integración happy path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ia import (
    Explanation,
    SanitizedQuery,
    explain_recommendation,
    is_logging_enabled,
    log_llm_interaction,
    resolve_log_path,
    sanitize,
)
from ia.cross_validator import CrossValidationResult
from ia.logs import (
    DEFAULT_LOG_PATH,
    build_base_record,
    final_shown_payload,
    llm_payload,
    response_to_text,
)
from ia.validator import LLMResponseSchema
from motor import Detection, Recommendation, parse_explain

# --- helpers puros -------------------------------------------------


def test_resolve_log_path_usa_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGPILOT_LLM_LOG_PATH", "/tmp/whatever.jsonl")
    assert resolve_log_path() == Path("/tmp/whatever.jsonl")


def test_resolve_log_path_default_si_no_hay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGPILOT_LLM_LOG_PATH", raising=False)
    assert resolve_log_path() == Path(DEFAULT_LOG_PATH)


def test_is_logging_enabled_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGPILOT_LLM_LOG_DISABLED", raising=False)
    assert is_logging_enabled() is True


@pytest.mark.parametrize("flag", ["true", "TRUE", "True", " true "])
def test_is_logging_enabled_false_si_env_es_true(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    monkeypatch.setenv("PGPILOT_LLM_LOG_DISABLED", flag)
    assert is_logging_enabled() is False


@pytest.mark.parametrize("flag", ["false", "0", "no", ""])
def test_is_logging_enabled_true_para_otros_valores(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    monkeypatch.setenv("PGPILOT_LLM_LOG_DISABLED", flag)
    assert is_logging_enabled() is True


def test_build_base_record_contiene_campos_esperados() -> None:
    detection = Detection(
        found=True,
        confidence=1.0,
        evidence={
            "matches": [{"table": "public.posts", "column": "author_id", "estimated_rows": 500_000}]
        },
    )
    rec = Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id",
        create_index_sql="CREATE INDEX idx_posts_author_id ON public.posts (author_id);",
        justification="x",
        expected_impact="y",
        selectivity=0.001,
    )
    sanitized = sanitize("SELECT * FROM posts WHERE author_id = 42")

    record = build_base_record(detection, rec, sanitized, request_id="req-abc")

    assert record["request_id"] == "req-abc"
    assert record["detection"]["found"] is True
    assert record["detection"]["matches_count"] == 1
    assert record["detection"]["first_match_table"] == "public.posts"
    assert record["recommendation"]["kind"] == "create_index"
    assert record["recommendation"]["index_name"] == "idx_posts_author_id"
    assert "$LITERAL_2_1" in record["sanitized_sql"]
    assert record["placeholders_count"] == 1


def test_build_base_record_genera_request_id_si_no_se_pasa() -> None:
    detection = Detection(found=False, confidence=0.0, evidence={"matches": []})
    rec = Recommendation(
        kind="analyze",
        table="public.x",
        column="y",
        index_method="btree",
        index_name="idx_x_y",
        create_index_sql="ANALYZE public.x;",
        justification="",
        expected_impact="",
        selectivity=None,
    )
    sanitized = SanitizedQuery(sql="SELECT 1", literals={})

    a = build_base_record(detection, rec, sanitized)
    b = build_base_record(detection, rec, sanitized)

    assert a["request_id"] != b["request_id"]
    assert len(a["request_id"]) >= 16


def test_llm_payload_con_raw_response_trunca_a_4000() -> None:
    huge = "x" * 10_000
    payload = llm_payload(called=True, raw_response=huge)
    assert payload["raw_response_length"] == 10_000
    assert len(payload["raw_response_excerpt"]) == 4000


def test_llm_payload_con_cross_incluye_reasons() -> None:
    cross = CrossValidationResult(
        passed=False,
        reasons=["columna no existe", "índice duplicado"],
        sandbox_verdict="discarded",
    )
    payload = llm_payload(called=True, raw_response="{}", pydantic_passed=True, cross=cross)
    assert payload["cross_validation_passed"] is False
    assert payload["cross_reasons"] == ["columna no existe", "índice duplicado"]
    assert payload["sandbox_verdict"] == "discarded"


def test_final_shown_payload_trunca_explicacion_y_marca_source() -> None:
    expl = Explanation(
        explanation="A" * 1000,
        suggested_rewrite="SELECT 1",
        confidence=0.85,
        source="llm",
    )
    payload = final_shown_payload(expl)
    assert payload["source"] == "llm"
    assert payload["confidence"] == 0.85
    assert payload["has_suggested_rewrite"] is True
    assert len(payload["explanation_excerpt"]) == 200


def test_response_to_text_re_serializa() -> None:
    response = LLMResponseSchema(explanation="hola", suggested_rewrite=None, confidence=0.5)
    text = response_to_text(response)
    parsed = json.loads(text)
    assert parsed["explanation"] == "hola"
    assert parsed["confidence"] == 0.5


# --- persistencia --------------------------------------------------


def test_log_llm_interaction_escribe_jsonl(llm_log_path: Path) -> None:
    log_llm_interaction({"outcome": "llm_ok", "extra": "valor"})

    assert llm_log_path.exists()
    contents = llm_log_path.read_text(encoding="utf-8").splitlines()
    assert len(contents) == 1
    record = json.loads(contents[0])
    assert record["outcome"] == "llm_ok"
    assert record["extra"] == "valor"
    assert "timestamp" in record  # se agrega adentro
    # Z o +00:00 — datetime.isoformat con timezone.utc
    assert "T" in record["timestamp"]


def test_log_llm_interaction_apendea_lineas_independientes(llm_log_path: Path) -> None:
    log_llm_interaction({"outcome": "llm_ok"})
    log_llm_interaction({"outcome": "llm_disabled"})
    log_llm_interaction({"outcome": "llm_error"})

    lines = llm_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["outcome"] == "llm_ok"
    assert json.loads(lines[1])["outcome"] == "llm_disabled"
    assert json.loads(lines[2])["outcome"] == "llm_error"


def test_log_llm_interaction_crea_directorio_padre(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nested = tmp_path / "nested" / "dirs" / "log.jsonl"
    monkeypatch.setenv("PGPILOT_LLM_LOG_PATH", str(nested))
    assert not nested.parent.exists()

    returned = log_llm_interaction({"outcome": "llm_ok"})

    assert returned == nested
    assert nested.exists()


def test_log_llm_interaction_disabled_devuelve_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "log.jsonl"
    monkeypatch.setenv("PGPILOT_LLM_LOG_PATH", str(log_path))
    monkeypatch.setenv("PGPILOT_LLM_LOG_DISABLED", "true")

    returned = log_llm_interaction({"outcome": "llm_ok"})

    assert returned is None
    assert not log_path.exists()


def test_log_llm_interaction_oserror_devuelve_none_sin_propagar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si el path es invalido o el filesystem falla, NO debe propagar."""
    bad = tmp_path / "no_se_puede_escribir"
    bad.mkdir()
    bad.chmod(0o400)  # solo lectura
    inside = bad / "log.jsonl"
    monkeypatch.setenv("PGPILOT_LLM_LOG_PATH", str(inside))

    returned = log_llm_interaction({"outcome": "llm_ok"})

    assert returned is None
    bad.chmod(0o700)  # cleanup permite que pytest borre tmp_path


# --- integración con explain_recommendation ------------------------


@pytest.fixture
def detection() -> Detection:
    return Detection(
        found=True,
        confidence=1.0,
        evidence={
            "matches": [
                {
                    "table": "public.posts",
                    "column": "author_id",
                    "estimated_rows": 500_000,
                    "index_name": None,
                }
            ]
        },
    )


@pytest.fixture
def plan() -> Any:
    return parse_explain(
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "posts",
                "Startup Cost": 0.0,
                "Total Cost": 1234.0,
                "Plan Rows": 5000,
                "Plan Width": 50,
                "Filter": "(author_id = 42)",
            }
        }
    )


@pytest.fixture
def recommendation() -> Recommendation:
    return Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id",
        create_index_sql="CREATE INDEX idx_posts_author_id ON public.posts (author_id);",
        justification="500k filas, sin índice utilizable.",
        expected_impact="Seq Scan → Index Scan.",
        selectivity=0.002,
    )


@pytest.fixture
def sanitized_query() -> SanitizedQuery:
    return sanitize("SELECT * FROM posts WHERE author_id = 42")


@pytest.fixture
def snapshot() -> dict[str, Any]:
    return {
        "schema": {
            "public.posts": {
                "columns": [{"name": "id"}, {"name": "author_id"}, {"name": "title"}],
                "indexes": [{"name": "posts_pkey", "columns": ["id"], "method": "btree"}],
            }
        },
        "sizes": {},
        "stats": {},
    }


def _read_log_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _http_response_with(payload: dict[str, Any]) -> httpx.Response:
    body = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    return httpx.Response(200, json=body)


def test_explain_recommendation_loggea_outcome_llm_disabled(
    monkeypatch: pytest.MonkeyPatch,
    llm_log_path: Path,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    monkeypatch.setenv("LLM_ENABLED", "false")

    explain_recommendation(
        detection,
        plan,
        recommendation,
        sanitized_query,
        snapshot=snapshot,
        request_id="req-disabled",
    )

    lines = _read_log_lines(llm_log_path)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["outcome"] == "llm_disabled"
    assert rec["request_id"] == "req-disabled"
    assert rec["llm"]["called"] is False
    assert rec["final_shown"]["source"] == "template"


def test_explain_recommendation_loggea_outcome_llm_error(
    monkeypatch: pytest.MonkeyPatch,
    llm_log_path: Path,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def boom(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", boom)

    explain_recommendation(
        detection,
        plan,
        recommendation,
        sanitized_query,
        snapshot=snapshot,
        request_id="req-net",
    )

    lines = _read_log_lines(llm_log_path)
    assert len(lines) == 1
    assert lines[0]["outcome"] == "llm_error"
    assert lines[0]["llm"]["called"] is True
    assert "connection refused" in lines[0]["llm"]["error"]
    assert lines[0]["final_shown"]["source"] == "template"


def test_explain_recommendation_loggea_outcome_llm_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    llm_log_path: Path,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "no es json"}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    explain_recommendation(
        detection,
        plan,
        recommendation,
        sanitized_query,
        snapshot=snapshot,
    )

    lines = _read_log_lines(llm_log_path)
    assert len(lines) == 1
    assert lines[0]["outcome"] == "llm_invalid_response"
    assert lines[0]["llm"]["pydantic_passed"] is False
    assert lines[0]["llm"]["raw_response_excerpt"].startswith("no es json")
    assert lines[0]["final_shown"]["source"] == "template"


def test_explain_recommendation_loggea_outcome_cross_validation_failed(
    monkeypatch: pytest.MonkeyPatch,
    llm_log_path: Path,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    """C6 falla porque el LLM propone una columna inexistente."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return _http_response_with(
            {
                "explanation": "Voy a inventar.",
                "suggested_rewrite": "SELECT inexistente FROM posts WHERE author_id = 1",
                "confidence": 0.9,
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    explain_recommendation(
        detection,
        plan,
        recommendation,
        sanitized_query,
        snapshot=snapshot,
    )

    lines = _read_log_lines(llm_log_path)
    assert len(lines) == 1
    assert lines[0]["outcome"] == "cross_validation_failed"
    assert lines[0]["llm"]["pydantic_passed"] is True
    assert lines[0]["llm"]["cross_validation_passed"] is False
    assert any("inexistente" in r for r in lines[0]["llm"]["cross_reasons"])
    assert lines[0]["final_shown"]["source"] == "template"


def test_explain_recommendation_loggea_outcome_llm_ok_con_todos_los_campos(
    monkeypatch: pytest.MonkeyPatch,
    llm_log_path: Path,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    """**C8 hecho-cuando**: después de un análisis, existe un log JSON
    con todos los campos esperados (detection, recommendation, prompt
    sanitizado, raw response, validaciones, sugerencia final)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LLM_ENABLED", raising=False)

    def fake_post(*args: Any, **kwargs: Any) -> httpx.Response:
        return _http_response_with(
            {
                "explanation": "Explicación válida del LLM",
                "suggested_rewrite": None,
                "confidence": 0.93,
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    explain_recommendation(
        detection,
        plan,
        recommendation,
        sanitized_query,
        snapshot=snapshot,
        request_id="req-feliz",
    )

    lines = _read_log_lines(llm_log_path)
    assert len(lines) == 1
    rec = lines[0]

    # Identidad y tiempo
    assert rec["request_id"] == "req-feliz"
    assert "timestamp" in rec
    assert rec["outcome"] == "llm_ok"

    # Detection serializada
    assert rec["detection"]["found"] is True
    assert rec["detection"]["matches_count"] == 1
    assert rec["detection"]["first_match_table"] == "public.posts"

    # Recommendation serializada
    assert rec["recommendation"]["kind"] == "create_index"
    assert rec["recommendation"]["index_name"] == "idx_posts_author_id"
    assert rec["recommendation"]["selectivity"] == 0.002

    # Sanitized SQL (sin literales originales — R4)
    assert "42" not in rec["sanitized_sql"]
    assert "$LITERAL_2_1" in rec["sanitized_sql"]
    assert rec["placeholders_count"] == 1

    # LLM respondió y validó
    assert rec["llm"]["called"] is True
    assert rec["llm"]["pydantic_passed"] is True
    assert rec["llm"]["cross_validation_passed"] is True
    assert "Explicación válida" in rec["llm"]["raw_response_excerpt"]

    # Final shown
    assert rec["final_shown"]["source"] == "llm"
    assert rec["final_shown"]["confidence"] == 0.93
    assert rec["final_shown"]["has_suggested_rewrite"] is False
    assert "Explicación válida" in rec["final_shown"]["explanation_excerpt"]


def test_explain_recommendation_no_loggea_si_logging_apagado(
    monkeypatch: pytest.MonkeyPatch,
    llm_log_path: Path,
    detection: Detection,
    plan: Any,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    snapshot: dict[str, Any],
) -> None:
    monkeypatch.setenv("PGPILOT_LLM_LOG_DISABLED", "true")
    monkeypatch.setenv("LLM_ENABLED", "false")

    explain_recommendation(
        detection,
        plan,
        recommendation,
        sanitized_query,
        snapshot=snapshot,
    )

    assert not llm_log_path.exists()

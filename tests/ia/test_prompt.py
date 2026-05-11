"""Tests del prompt builder C4.

Cubrimos:
- Forma del prompt: system + 1 user-turn + schema esperado.
- R4 defensa en profundidad: rechazo de strings crudos como sanitized_query.
- Privacidad: ningún literal original aparece en el prompt aunque
  haya sido sanitizado antes.
- Inclusión de los hechos del motor (detección, recomendación, plan,
  query sanitizada, índice de placeholders por tipo).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ia import (
    LLMPrompt,
    SanitizedQuery,
    build_explanation_prompt,
    sanitize,
)
from motor import Detection, Recommendation, parse_explain


def _plan() -> Any:
    return parse_explain(
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "posts",
                "Startup Cost": 0.0,
                "Total Cost": 100.0,
                "Plan Rows": 1000,
                "Plan Width": 24,
                "Filter": "(author_id = 5)",
            }
        }
    )


def _detection() -> Detection:
    return Detection(
        found=True,
        confidence=1.0,
        evidence={
            "matches": [
                {
                    "table": "public.posts",
                    "column": "author_id",
                    "estimated_rows": 500_000,
                    "rows_removed_by_filter": 166663,
                    "index_name": None,
                    "filter": "(author_id = 5)",
                }
            ]
        },
    )


def _recommendation() -> Recommendation:
    return Recommendation(
        kind="create_index",
        table="public.posts",
        column="author_id",
        index_method="btree",
        index_name="idx_posts_author_id",
        create_index_sql='CREATE INDEX "idx_posts_author_id" ON "public"."posts" ("author_id");',
        justification="Tabla grande sin índice utilizable.",
        expected_impact="Seq Scan → Index Scan.",
        selectivity=0.0002,
    )


# --- forma del prompt ----------------------------------------------


def test_prompt_tiene_system_y_un_user_turn() -> None:
    sanitized = sanitize("SELECT * FROM posts WHERE author_id = 5")
    prompt = build_explanation_prompt(_detection(), _plan(), _recommendation(), sanitized)

    assert isinstance(prompt, LLMPrompt)
    assert "Postgres" in prompt.system
    assert len(prompt.messages) == 1
    assert prompt.messages[0]["role"] == "user"


def test_prompt_expone_schema_esperado_para_C5() -> None:
    """El schema de salida (JSON con explanation/suggested_rewrite/confidence)
    viaja en el LLMPrompt para que C5 (Pydantic) sepa qué validar."""
    sanitized = sanitize("SELECT * FROM posts WHERE author_id = 5")
    prompt = build_explanation_prompt(_detection(), _plan(), _recommendation(), sanitized)

    schema = prompt.expected_output_schema
    assert set(schema["required"]) == {"explanation", "suggested_rewrite", "confidence"}
    assert schema["properties"]["confidence"]["minimum"] == 0.0
    assert schema["properties"]["confidence"]["maximum"] == 1.0


def test_prompt_incluye_hechos_del_motor() -> None:
    """El user-turn debe contener detección, recomendación, plan y query
    sanitizada. Es lo que el LLM necesita para explicar y proponer
    sin inventar."""
    sanitized = sanitize("SELECT * FROM posts WHERE author_id = 5")
    prompt = build_explanation_prompt(_detection(), _plan(), _recommendation(), sanitized)

    content = prompt.messages[0]["content"]
    # Mejor que substring genérico: parseamos el JSON embebido.
    json_start = content.index("{")
    json_end = content.rindex("}") + 1
    payload = json.loads(content[json_start:json_end])

    assert payload["detection"]["found"] is True
    assert payload["recommendation"]["kind"] == "create_index"
    assert payload["recommendation"]["index_name"] == "idx_posts_author_id"
    assert payload["plan_summary"]["nodes"][0]["node_type"] == "Seq Scan"
    assert "$LITERAL" in payload["sanitized_query"]
    assert isinstance(payload["literal_placeholders"], dict)


# --- privacidad (R4) ------------------------------------------------


def test_rechaza_string_crudo_como_query() -> None:
    """Defensa en profundidad: si el caller intenta mandar un string en
    vez de un SanitizedQuery, el builder revienta. Esto cierra una vía
    accidental de filtrar SQL con literales al LLM."""
    with pytest.raises(TypeError, match="SanitizedQuery"):
        build_explanation_prompt(
            _detection(),
            _plan(),
            _recommendation(),
            "SELECT * FROM posts WHERE author_id = 5",  # type: ignore[arg-type]
        )


def test_ningun_literal_original_aparece_en_el_prompt() -> None:
    """Privacidad end-to-end: sanitizamos una query con email + número,
    construimos el prompt, y verificamos que ni el email ni el número
    original aparecen en ninguna parte del prompt serializado."""
    raw = "SELECT * FROM posts WHERE email = 'admin@empresa.com' AND id = 42"
    sanitized = sanitize(raw)

    prompt = build_explanation_prompt(_detection(), _plan(), _recommendation(), sanitized)

    serialized = json.dumps(
        {"system": prompt.system, "messages": prompt.messages},
        ensure_ascii=False,
    )
    assert "admin@empresa.com" not in serialized
    assert "'admin@empresa.com'" not in serialized
    # El número 42 podría aparecer por coincidencia en otros campos
    # (selectividad, costs, etc.), así que NO chequeamos `"42"` literal.
    # Sí verificamos que la query sanitizada usa placeholders en lugar
    # de los valores reales. El sanitizador trata `'admin@empresa.com'`
    # como STRING completo (gana el patrón de comillas, no el de email
    # interno) — eso es comportamiento correcto y suficiente para R4.
    assert "WHERE email = $LITERAL" in serialized
    assert "AND id = $LITERAL" in serialized


def test_placeholder_index_incluye_tipo_no_valor() -> None:
    """`literal_placeholders` mapea placeholder → tipo, NUNCA al valor
    original. Esto es necesario para que el LLM sepa qué tipo de dato
    espera sin filtrar el dato real."""
    sanitized = sanitize("SELECT * FROM x WHERE a = 5 AND b = 'foo'")
    prompt = build_explanation_prompt(_detection(), _plan(), _recommendation(), sanitized)

    content = prompt.messages[0]["content"]
    payload = json.loads(content[content.index("{") : content.rindex("}") + 1])
    placeholders = payload["literal_placeholders"]

    # Las claves son `$LITERAL_<i>_<j>`; los valores son tipos.
    for key, value in placeholders.items():
        assert key.startswith("$LITERAL_")
        assert value in {"string", "number", "date", "uuid", "email"}
        # Nada que se parezca al valor original.
        assert value != "foo"
        assert value != "5"


# --- pure-function sanity check ------------------------------------


def test_prompt_es_deterministico() -> None:
    """Mismas entradas → mismo prompt (json.dumps con sort_keys=True).
    Importante para futuras pruebas con golden snapshots y para que
    Anthropic pueda cachear prompt prefixes."""
    sanitized = sanitize("SELECT * FROM posts WHERE author_id = 5")
    a = build_explanation_prompt(_detection(), _plan(), _recommendation(), sanitized)
    b = build_explanation_prompt(_detection(), _plan(), _recommendation(), sanitized)
    assert a == b


def test_sanitized_query_dataclass_aceptado() -> None:
    """Construir un SanitizedQuery a mano (no via sanitize()) también
    debe funcionar — el contrato es el tipo, no la procedencia."""
    sanitized = SanitizedQuery(sql="SELECT 1", literals={})
    prompt = build_explanation_prompt(_detection(), _plan(), _recommendation(), sanitized)
    assert isinstance(prompt, LLMPrompt)

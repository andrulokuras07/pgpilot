"""Integración real end-to-end de `/analyze` con LLM + sandbox vivos.

Regresión del Bug 1 (Demo Day): antes del fix, la pipeline con LLM y
sandbox activos retornaba `partial=true` con un error en la etapa
``explain`` porque `cross_validate` le pasaba al sandbox la SQL
sanitizada (`$LITERAL_X_Y`), y Postgres rechazaba la sintaxis.

Este test corre la pipeline completa contra AppDB, el sandbox y el LLM
reales. Skipea automáticamente si falta cualquier dependencia:

- ANTHROPIC_API_KEY (LLM real)
- AppDB y sandbox levantados (variables APPDB_*/SANDBOX_*)

Markers: ``integration`` + ``llm`` (ambos requeridos).

Uso típico:
    docker compose up appdb sandbox -d
    ANTHROPIC_API_KEY=sk-... \\
    APPDB_HOST=localhost APPDB_PORT=5434 APPDB_DB=appdb \\
    APPDB_USER=app_user APPDB_PASSWORD=app_pass \\
    SANDBOX_HOST=localhost SANDBOX_PORT=5435 SANDBOX_DB=sandbox \\
    SANDBOX_USER=sandbox_user SANDBOX_PASSWORD=sandbox_pass \\
    LLM_ENABLED=true \\
    .venv/bin/pytest tests/integration/test_analyze_llm_with_sandbox.py -v
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.getenv("ANTHROPIC_API_KEY"),
        reason="Sin ANTHROPIC_API_KEY: integración con LLM real se omite.",
    ),
    pytest.mark.skipif(
        not os.getenv("APPDB_HOST"),
        reason="Sin APPDB_HOST: AppDB no configurada para integración.",
    ),
    pytest.mark.skipif(
        not os.getenv("SANDBOX_HOST"),
        reason="Sin SANDBOX_HOST: sandbox no configurado para integración.",
    ),
]


def test_analyze_con_llm_y_sandbox_no_filtra_placeholders_al_sandbox() -> None:
    """`/analyze` con Q01 (Seq Scan sobre `posts`) y la stack completa
    debe devolver explicación del LLM, sandbox=validated y SIN errores.

    Antes del fix de Bug 1, esto devolvía ``partial=true`` y
    ``explanation.source="template"`` porque el sandbox recibía la
    SQL sanitizada con `$LITERAL_X_Y` y Postgres respondía con un
    SyntaxError, que la pipeline trataba como falla de la etapa
    ``explain``.
    """
    # Importar acá para no levantar el lifespan en otros tests del módulo.
    from backend.main import app

    with TestClient(app) as client:
        resp = client.post(
            "/analyze",
            json={"query": "SELECT * FROM posts WHERE author_id = 5000"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["errors"] == [], (
        f"Esperaba errors=[], recibí: {body['errors']}. Bug 1 vivo: el sandbox sigue "
        "recibiendo SQL con placeholders y la etapa explain está fallando."
    )
    assert body["partial"] is False

    formal_recs = [r for r in body["recommendations"] if r.get("kind") != "finding"]
    assert formal_recs, "Esperaba al menos una recomendación formal del motor"

    rec = formal_recs[0]
    assert rec["explanation"]["source"] == "llm", (
        f"Esperaba explanation.source='llm', recibí {rec['explanation']['source']!r}. "
        "Si quedó en 'template' con LLM_ENABLED=true, revisar la pipeline."
    )
    assert rec["sandbox_verdict"] == "validated", (
        f"Esperaba sandbox_verdict='validated', recibí {rec['sandbox_verdict']!r}. "
        "Bug 1 vivo: el sandbox no pudo evaluar la recomendación."
    )

    # Bug 2 — el placeholder del sanitizador no debe filtrarse a la prosa.
    assert "$LITERAL" not in rec["explanation"]["text"], (
        f"La prosa del LLM aún contiene placeholders del sanitizador: "
        f"{rec['explanation']['text']!r}"
    )

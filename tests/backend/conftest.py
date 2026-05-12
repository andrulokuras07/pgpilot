"""Fixtures compartidas para los tests del backend.

`client` mantiene el contrato pre-C9: TestClient con un orquestador
stubeado que devuelve arrays vacíos. Esto preserva los tests de B13/B14
(contrato del endpoint y CORS) sin necesidad de levantar AppDB.

Tests que ejerciten la pipeline real usan `client_with_orchestrator`
(monkeypatchean `analyze_query` con su propia función) o llaman
`backend.orchestrator.analyze_query` directamente.

Tests que verifiquen el comportamiento "AppDB no configurada" usan
`unconfigured_client` — sin app.state poblado.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_STATE_KEYS = ("appdb_pool", "snapshot", "sandbox_pool")


def _clear_state() -> None:
    for key in _STATE_KEYS:
        if hasattr(app.state, key):
            delattr(app.state, key)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient con state mínimo y `analyze_query` stubeado a vacío.

    Es lo que los tests pre-C9 esperaban implícitamente del stub de B13.
    Sigue cubriendo CORS, validación 422 y healthcheck sin requerir
    AppDB ni IA real.
    """

    def _stub_analyze_query(**kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        return {"detections": [], "recommendations": []}

    monkeypatch.setattr("backend.main.analyze_query", _stub_analyze_query)
    app.state.appdb_pool = object()  # truthy sentinel
    app.state.snapshot = {"schema": {}, "sizes": {}, "stats": {}}
    app.state.sandbox_pool = None
    try:
        yield TestClient(app)
    finally:
        _clear_state()


@pytest.fixture
def unconfigured_client() -> Iterator[TestClient]:
    """TestClient sin AppDB configurada — para verificar 503."""
    _clear_state()
    try:
        yield TestClient(app)
    finally:
        _clear_state()

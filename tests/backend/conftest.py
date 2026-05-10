"""Fixtures compartidas para los tests del backend."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client() -> TestClient:
    """Cliente HTTP en proceso, sin levantar uvicorn."""
    return TestClient(app)

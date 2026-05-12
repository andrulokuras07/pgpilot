"""Fixtures compartidas para los tests del módulo `ia`.

`_scoped_llm_log_path` es autouse: redirige el archivo de logs C8 a un
tmp_path por test. Esto:

- Evita que los tests existentes (C4–C7) escriban en `logs/` del repo.
- Permite que los tests de C8 lean el archivo via la fixture explícita
  `llm_log_path`.
- Aísla cada test (sin contaminación cruzada).

Cualquier test que necesite el comportamiento "logs apagados" puede
sobreescribir con `monkeypatch.setenv("PGPILOT_LLM_LOG_DISABLED", "true")`.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scoped_llm_log_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    log_path = tmp_path / "llm_log.jsonl"
    monkeypatch.setenv("PGPILOT_LLM_LOG_PATH", str(log_path))
    monkeypatch.delenv("PGPILOT_LLM_LOG_DISABLED", raising=False)
    return log_path


@pytest.fixture
def llm_log_path(_scoped_llm_log_path: Path) -> Path:
    """Alias explícito para tests que leen el archivo de logs."""
    return _scoped_llm_log_path

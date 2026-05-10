"""Backend FastAPI de PgPilot.

Orquesta los módulos del proyecto y expone la API HTTP. Por ahora solo
expone /analyze como stub (B13). Ver backend/CLAUDE.md.
"""

from backend.main import app

__all__ = ["app"]

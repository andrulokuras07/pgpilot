"""Aplicación FastAPI de PgPilot.

Punto de entrada del backend. Define los endpoints y la configuración de
CORS para que el frontend (Vite, localhost:5173) pueda llamarlo.

Por ahora /analyze es un stub que devuelve listas vacías. Se conectará al
motor real en C9. Ver backend/CLAUDE.md.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="PgPilot", version="0.1.0")

# CORS: solo el frontend en dev (localhost:5173). En producción se
# ajustará desde un settings module.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class AnalyzeRequest(BaseModel):
    """Body que el frontend envía al endpoint /analyze."""

    query: str = Field(..., min_length=1, description="SQL crudo a analizar")


class AnalyzeResponse(BaseModel):
    """Forma de la respuesta de /analyze. Estable desde B13: el contrato
    no cambia cuando se conecte al motor real, solo se llenan las listas.
    """

    detections: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """Stub: devuelve la estructura final con listas vacías.

    El motor determinístico se conectará aquí en C9. La firma del request
    y la respuesta son las definitivas.
    """
    _ = req.query
    return AnalyzeResponse()


@app.get("/health")
def health() -> dict[str, str]:
    """Healthcheck simple para verificar que el backend está vivo."""
    return {"status": "ok"}

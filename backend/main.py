"""Aplicación FastAPI de PgPilot.

Punto de entrada del backend. Define el endpoint `/analyze`
(orquestación completa, ver `backend.orchestrator`) y la
configuración de CORS para el frontend (Vite, localhost:5173).

Estado actual:
- B13: stub de /analyze (superado por C9).
- C9: /analyze conecta a AppDB, corre EXPLAIN, ejecuta detector C1,
  recomienda índices con C2, valida en sandbox (C3 cuando hay), y
  pasa por la capa IA (C4-C7) que loggea via C8.
- B14: CORS permite `http://localhost:5173`.

Ver `backend/CLAUDE.md` para el contrato del endpoint y cómo extender.
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.orchestrator import AnalyzeError, analyze_query
from conector import (
    ConnectionConfig,
    SchemaSnapshot,
    create_pool,
    extract_snapshot,
)
from sandbox import SandboxConfig, cleanup_zombie_schemas, create_sandbox_pool
from workload import parse_pg_stat_statements, score_workload

log = logging.getLogger("pgpilot.backend")


def _appdb_pool_from_env() -> Any | None:
    """Lee `APPDB_*` del entorno y abre el pool. Devuelve `None` si no hay
    configuración (entornos de test, despliegue inicial sin AppDB)."""
    host = os.getenv("APPDB_HOST")
    if not host:
        return None
    return create_pool(
        ConnectionConfig(
            host=host,
            port=int(os.getenv("APPDB_PORT", "5434")),
            dbname=os.getenv("APPDB_DB", "appdb"),
            user=os.getenv("APPDB_USER", "app_user"),
            password=os.getenv("APPDB_PASSWORD", ""),
        )
    )


def _sandbox_pool_from_env() -> Any | None:
    """Lee `SANDBOX_*` del entorno y abre el pool del sandbox. Sandbox
    es opcional: si no se configura, /analyze sigue funcionando sin la
    columna `sandbox_verdict`."""
    host = os.getenv("SANDBOX_HOST")
    if not host:
        return None
    return create_sandbox_pool(
        SandboxConfig(
            host=host,
            port=int(os.getenv("SANDBOX_PORT", "5435")),
            dbname=os.getenv("SANDBOX_DB", "sandbox"),
            user=os.getenv("SANDBOX_USER", "sandbox_user"),
            password=os.getenv("SANDBOX_PASSWORD", ""),
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Abre los pools y extrae el snapshot al startup.

    Decisión de diseño: el snapshot se extrae UNA vez al startup y se
    cachea en `app.state`. Esto evita el overhead de re-extraer schema +
    sizes + stats en cada request /analyze (varios cientos de ms en
    AppDB v1). Si el schema cambia en runtime, hay que reiniciar el
    backend (aceptable para Demo Day; un endpoint /refresh-snapshot
    queda como E-ticket).

    Si AppDB no está disponible al startup, /analyze responde 503 con
    mensaje claro — no crasheamos el proceso, así el frontend puede
    ver al menos /health y los desarrolladores pueden iterar sin AppDB
    arriba.
    """
    appdb_pool: Any | None = None
    sandbox_pool: Any | None = None
    snapshot: SchemaSnapshot | None = None

    try:
        appdb_pool = _appdb_pool_from_env()
        if appdb_pool is not None:
            snapshot = extract_snapshot(appdb_pool)
            log.info(
                "AppDB conectada y snapshot extraído (%d tablas).",
                len(snapshot.get("schema", {})),
            )
        else:
            log.warning(
                "APPDB_HOST no configurado; /analyze responderá 503 hasta que se "
                "definan las variables de entorno APPDB_*.",
            )
    except Exception as exc:
        log.error("No se pudo inicializar AppDB pool/snapshot: %r", exc)
        appdb_pool = None
        snapshot = None

    try:
        sandbox_pool = _sandbox_pool_from_env()
        if sandbox_pool is not None:
            zombies = cleanup_zombie_schemas(sandbox_pool)
            if zombies:
                log.info(
                    "Limpiados %d schemas zombies del sandbox: %s",
                    len(zombies),
                    ", ".join(zombies),
                )
            log.info("Sandbox pool conectado.")
        else:
            log.info(
                "SANDBOX_HOST no configurado; /analyze omitirá la validación "
                "estructural (sandbox_verdict será null).",
            )
    except Exception as exc:
        log.warning("No se pudo inicializar sandbox pool: %r", exc)
        sandbox_pool = None

    app.state.appdb_pool = appdb_pool
    app.state.snapshot = snapshot
    app.state.sandbox_pool = sandbox_pool

    try:
        yield
    finally:
        if appdb_pool is not None:
            appdb_pool.close()
        if sandbox_pool is not None:
            sandbox_pool.close()


app = FastAPI(title="PgPilot", version="0.1.0", lifespan=lifespan)

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
    """Forma de la respuesta de /analyze.

    Estable desde B13 al nivel de claves top-level. C9 enriqueció el
    contenido de cada item (recommendations trae `explanation`,
    `sandbox_verdict`, `create_index_sql`, etc.). E8 añadió `errors` y
    `partial`: cuando alguna etapa del pipeline falla, el endpoint
    devuelve lo que sí pudo calcular y marca la degradación en vez de
    crashear. Ver `backend/orchestrator.analyze_query` para el shape
    exacto de cada elemento.
    """

    detections: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "Etapas del pipeline que fallaron (degradación parcial, E8). "
            "Cada entrada: {stage, message}. Vacío en el caso normal."
        ),
    )
    partial: bool = Field(
        default=False,
        description="True si alguna etapa del pipeline falló y la respuesta es parcial (E8).",
    )


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Orquesta la pipeline completa para una query del frontend.

    503 si AppDB no se inicializó al startup. 4xx/504 si Postgres
    rechaza la query o el EXPLAIN expira (ver `orchestrator._run_explain`
    para el mapeo). 200 con `partial=true` cuando alguna etapa interna
    falló pero la pipeline siguió (E8). 500 genérico (sin stack trace,
    detalle loggeado) si algo inesperado revienta fuera del orquestador.
    """
    appdb_pool = getattr(request.app.state, "appdb_pool", None)
    snapshot = getattr(request.app.state, "snapshot", None)
    sandbox_pool = getattr(request.app.state, "sandbox_pool", None)

    if appdb_pool is None or snapshot is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "AppDB no está configurada. Setea APPDB_HOST/PORT/DB/USER/PASSWORD "
                "y reinicia el backend."
            ),
        )

    request_id = uuid.uuid4().hex
    try:
        body = analyze_query(
            query=req.query,
            appdb_pool=appdb_pool,
            snapshot=snapshot,
            sandbox_pool=sandbox_pool,
            request_id=request_id,
        )
        return AnalyzeResponse(**body)
    except AnalyzeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001 — E8: red de seguridad final
        # El orquestador ya aísla cada etapa, pero un bug fuera de su
        # alcance (construcción del response model, un import, etc.) no
        # debe devolver un stack trace ni colgar el endpoint. El detalle
        # se loggea; el cliente ve un 500 genérico.
        log.exception("Error no manejado en /analyze (request_id=%s): %r", request_id, exc)
        raise HTTPException(status_code=500, detail="Error interno al analizar la query.") from exc


class WorkloadEntry(BaseModel):
    query: str
    calls: int
    total_exec_time: float
    mean_exec_time: float
    rows: int
    score: float
    rank: int


class WorkloadResponse(BaseModel):
    top: list[WorkloadEntry] = Field(default_factory=list)


@app.post("/workload", response_model=WorkloadResponse)
async def workload(request: Request) -> WorkloadResponse:
    """Recibe un archivo pg_stat_statements (CSV o JSON) y devuelve top 10."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(status_code=422, detail="Se requiere un archivo 'file'.")
        raw = (await upload.read()).decode("utf-8", errors="replace")
    else:
        raw = (await request.body()).decode("utf-8", errors="replace")

    if not raw.strip():
        raise HTTPException(status_code=422, detail="El archivo está vacío.")

    try:
        entries = parse_pg_stat_statements(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo parsear el archivo: {exc}",
        ) from exc

    if not entries:
        return WorkloadResponse(top=[])

    scored = score_workload(entries, top_n=10)
    return WorkloadResponse(top=[WorkloadEntry(**s.__dict__) for s in scored])


@app.get("/health")
def health() -> dict[str, str]:
    """Healthcheck simple para verificar que el backend está vivo."""
    return {"status": "ok"}

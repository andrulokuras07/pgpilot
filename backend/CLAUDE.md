# Módulo `backend` — API HTTP de PgPilot

FastAPI que orquesta los módulos del proyecto y expone los endpoints que consume el frontend. Es el único módulo que conoce a todos los demás (`/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`); los módulos no se conocen entre sí.

**Lo que NO hace:** lógica de detección, parsing de SQL, llamadas al LLM. Eso vive en los módulos correspondientes; el backend solo orquesta.

---

## Estado actual

- ✅ B13 — endpoint `/analyze` stub con CORS para `localhost:5173`
- ✅ C8 — logs estructurados (vive en `ia/logs.py`; el backend genera
  un `request_id` por petición y lo propaga para correlación)
- ✅ C9 — `/analyze` orquesta la pipeline real (parser + C1 + C2 + C3 + C4-C7)
- ⬜ E3 — endpoint `/workload`

---

## Cómo correrlo en desarrollo

```bash
# Desde la raíz del repo
APPDB_HOST=localhost APPDB_PORT=5434 APPDB_DB=appdb \
APPDB_USER=app_user APPDB_PASSWORD=app_pass \
SANDBOX_HOST=localhost SANDBOX_PORT=5435 SANDBOX_DB=sandbox \
SANDBOX_USER=sandbox_user SANDBOX_PASSWORD=sandbox_pass \
ANTHROPIC_API_KEY=sk-... \
.venv/bin/uvicorn backend.main:app --reload --port 8000
```

El backend queda en `http://localhost:8000`. Healthcheck rápido:

```bash
curl http://localhost:8000/health
```

**Variables de entorno reconocidas:**

- `APPDB_HOST/PORT/DB/USER/PASSWORD` — pool a la BD del cliente.
  Si falta `APPDB_HOST`, /analyze responde 503 (el resto del backend
  sigue vivo: /health responde 200).
- `SANDBOX_HOST/PORT/DB/USER/PASSWORD` — pool al sandbox. Opcional;
  sin él, `recommendations[].sandbox_verdict` queda en `null` y la
  pipeline funciona igual (R5).
- `ANTHROPIC_API_KEY` y `LLM_ENABLED` — consumidos por `ia/llm.py`.
- `PGPILOT_LLM_LOG_PATH` y `PGPILOT_LLM_LOG_DISABLED` — consumidos
  por `ia/logs.py` (C8).

El snapshot de schema se extrae UNA vez al startup (lifespan) y se
cachea en `app.state.snapshot`. Para refrescarlo hay que reiniciar
el proceso. Un endpoint `/refresh-snapshot` queda como E-ticket.

---

## API pública

### `POST /analyze`

Recibe un SQL crudo y devuelve detecciones + recomendaciones (C9).

**Request:**

```json
{ "query": "SELECT ..." }
```

`query` es obligatorio y no puede ser vacío (`min_length=1`); FastAPI
responde 422 si falta o está vacío.

**Response (C9, sin detecciones):**

```json
{ "detections": [], "recommendations": [] }
```

**Response (C9, con detección de C1):**

```jsonc
{
  "detections": [
    {
      "type": "seq_scan_on_large_table",
      "found": true,
      "confidence": 1.0,
      "evidence": { "matches": [{"table": "public.posts", "column": "author_id", ...}] }
    }
  ],
  "recommendations": [
    {
      "kind": "create_index",                  // o "analyze"
      "table": "public.posts",
      "column": "author_id",
      "index_method": "btree",
      "index_name": "idx_posts_author_id",
      "create_index_sql": "CREATE INDEX ...",
      "justification": "...",
      "expected_impact": "...",
      "selectivity": 0.002,
      "sandbox_verdict": "validated",          // null si no hay sandbox
      "sandbox_reason": "Index Scan ...",      // null si no hay sandbox
      "explanation": {
        "text": "PgPilot detectó un Seq Scan ...",
        "suggested_rewrite": null,             // o un SQL alternativo del LLM
        "confidence": 0.88,
        "source": "llm"                        // o "template"
      }
    }
  ]
}
```

El frontend (B14/C10) consume `recommendations[].explanation.text` para
la tarjeta y `recommendations[].create_index_sql` para el botón "copiar
SQL". `sandbox_verdict` controla la insignia "validado en sandbox".
`explanation.source` decide si mostrar la etiqueta "explicación
generada sin IA".

**Códigos de error:**

- `422` — body inválido (sin `query` o `query` vacía).
- `503` — AppDB no configurada al startup. El cliente ve la lista de
  env vars que faltan.
- `400` — Postgres rechazó la query (sintaxis, tabla inexistente,
  permiso denegado).
- `403` — el usuario intentó una mutación (UPDATE/INSERT/DROP). La
  conexión es read-only por R7.
- `504` — EXPLAIN excedió el `statement_timeout` (5s por default).
- `500` — estado inesperado interno (no debería pasar).

### `GET /health`

Healthcheck simple. Devuelve `{"status": "ok"}` con HTTP 200. No depende de AppDB ni del LLM.

---

## CORS

Solo se permite el origen `http://localhost:5173` (Vite dev). Métodos: `GET`, `POST`, `OPTIONS`. Header `Content-Type` permitido. `allow_credentials` deshabilitado (no necesitamos cookies).

Para producción habrá que mover la lista de orígenes a un settings module (env var). Por ahora hardcoded en `backend/main.py`.

---

## Cómo agregar un endpoint nuevo

1. Define los modelos `Pydantic` para request y response en `backend/main.py` (o en un módulo separado si crece).
2. Agrega el handler con `@app.<método>("/ruta")` y type hints completos en parámetros y return (R8).
3. Agrega tests en `tests/backend/`. Mínimo: happy path + un caso de validación (422). Si afecta CORS, también prueba el origen del frontend.
4. Si el endpoint orquesta un módulo, importa la API pública del módulo (`from motor import parse_explain`, etc.). Nunca dupliques lógica.

---

## Tests

`tests/backend/`:

- `test_analyze.py` — contrato del endpoint (200 con stub, validación
  422, healthcheck, 503 sin AppDB, propagación del payload del
  orquestador, traducción de `AnalyzeError` a status, propagación de
  pools del state, generación de `request_id`).
- `test_cors.py` — preflight desde `localhost:5173`, header en POST
  real, bloqueo a orígenes no permitidos.
- `test_orchestrator.py` — tests directos de
  `backend.orchestrator.analyze_query` con `FakePool`. Cubre: no
  detección → arrays vacíos, detección → estructura completa, sandbox
  populando `verdict`, sandbox que explota → `verdict=None` sin
  romper pipeline, LLM mockeado marca `source="llm"`, mapeo de
  errores Postgres a `AnalyzeError` (400/403/504/500). El "hecho
  cuando" de C9 vive en
  `test_analyze_query_con_deteccion_devuelve_estructura_completa`.

Son unit (usan `fastapi.testclient.TestClient` y un `FakePool`
inline, sin levantar uvicorn ni necesitar AppDB).

```bash
.venv/bin/python -m pytest tests/backend/ -v
```

`conftest.py` provee dos fixtures de `TestClient`:

- `client` — state mínimo poblado con sentinels y `analyze_query`
  monkeypatcheado a `{"detections": [], "recommendations": []}`.
  Lo usan los tests pre-C9 (CORS, validación, healthcheck) sin
  requerir AppDB.
- `unconfigured_client` — sin nada poblado en `app.state`. Sirve
  para verificar el 503 que C9 levanta cuando `APPDB_HOST` no está
  definida.

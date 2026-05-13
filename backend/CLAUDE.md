# Módulo `backend` — API HTTP de PgPilot

FastAPI que orquesta los módulos del proyecto y expone los endpoints que consume el frontend. Es el único módulo que conoce a todos los demás (`/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`); los módulos no se conocen entre sí.

**Lo que NO hace:** lógica de detección, parsing de SQL, llamadas al LLM. Eso vive en los módulos correspondientes; el backend solo orquesta.

---

## Estado actual

- ✅ B13 — endpoint `/analyze` stub con CORS para `localhost:5173`
- ✅ C8 — logs estructurados (vive en `ia/logs.py`; el backend genera
  un `request_id` por petición y lo propaga para correlación)
- ✅ C9 — `/analyze` orquesta la pipeline real (parser + C1 + C2 + C3 + C4-C7)
- ✅ C11 — `/analyze` añade `sandbox_plan_comparison` por recomendación
  (datos del `ValidationResult` que el frontend usa para el before/after)
- ✅ E3 — endpoint `POST /workload` (recibe CSV/JSON, devuelve top 10)
- ✅ E5 — cleanup de schemas zombies del sandbox al startup
- ✅ E7 — `sandbox_plan_comparison` enriquecido: añade `plan_rows_before`/
  `plan_rows_after` (filas estimadas por el planner antes/después) al
  sub-objeto, para el comparativo enriquecido + resumen ejecutivo del
  frontend
- ✅ E8 — aislamiento de errores en `/analyze`: cada etapa del
  orquestador (sanitize · extracción · parser · detector · recomendador ·
  validación de sandbox · explicación/LLM) va en su `try/except`. Si una
  etapa falla, las demás siguen lo que puedan y el endpoint devuelve
  resultados parciales (200) con `errors[]` (`{stage, message}`) y
  `partial=true`, en vez de crashear. La extracción (EXPLAIN) es la única
  etapa "terminal" → sigue mapeando a `AnalyzeError`/4xx/504/500. Red de
  seguridad final en el handler: cualquier excepción inesperada fuera del
  orquestador → 500 genérico (detalle loggeado, nunca filtrado al cliente)

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
{ "detections": [], "recommendations": [], "errors": [], "partial": false }
```

`errors` y `partial` (E8) están siempre presentes: `errors` vacío y
`partial=false` en el caso normal.

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
      "sandbox_plan_comparison": {             // null si no hay sandbox o
        "node_type_before": "Seq Scan",        //   si la validación fue
        "node_type_after": "Index Scan",       //   "skipped_no_sandbox_signal"
        "cost_before": 12345.0,                //   (ej. recomendación
        "cost_after": 42.0,                    //   tipo ANALYZE)
        "plan_rows_before": 500000,            // E7: filas estimadas por
        "plan_rows_after": 2500                //   el planner antes/después
      },
      "explanation": {
        "text": "PgPilot detectó un Seq Scan ...",
        "suggested_rewrite": null,             // o un SQL alternativo del LLM
        "confidence": 0.88,
        "source": "llm"                        // o "template"
      }
    }
  ],
  "errors": [],          // E8 — etapas caídas: [{stage, message}]
  "partial": false       // E8 — true ⇔ errors no vacío
}
```

**Response (E8, degradación parcial):** si una etapa interna falla, el
endpoint sigue devolviendo `200` con lo que sí pudo calcular más el flag.
Ejemplo (la explicación/LLM revienta de forma inesperada — `explain_recommendation`
ya absorbe sus fallos esperables; esto es un bug crudo): las detecciones
y la recomendación determinística siguen ahí, la explicación cae a la
plantilla (`source="template"`), y:

```jsonc
{
  "detections": [ /* … */ ],
  "recommendations": [ /* … con explanation de plantilla */ ],
  "errors": [
    { "stage": "explain",
      "message": "No se pudo generar la explicación enriquecida de una recomendación; se muestra la versión determinística." }
  ],
  "partial": true
}
```

`stage` ∈ `sanitize | parse | detect | recommend | validate | explain`.
`message` es genérico a propósito (E8 sigue la política de `AnalyzeError`:
no se filtran nombres de tabla, paths ni stack traces al cliente; el
detalle real va al log server-side). Si `sanitize` falla, además, el LLM
NO se llama para ninguna recomendación (R4) y todas las explicaciones
salen de plantilla.

El frontend (B14/C10) consume `recommendations[].explanation.text` para
la tarjeta y `recommendations[].create_index_sql` para el botón "copiar
SQL". `sandbox_verdict` controla la insignia "validado en sandbox".
`explanation.source` decide si mostrar la etiqueta "explicación
generada sin IA". `sandbox_plan_comparison` alimenta el panel
before/after de C11+E7: lleva `node_type_before/after`, `cost_before/
after` y `plan_rows_before/after` (filas estimadas por el planner) por
corrida; el frontend deriva de ahí el titular de transición de tipo de
nodo y el resumen ejecutivo automático ("redujo el costo estimado de X
a Y — Zx mejora estimada en sandbox"). No incluye tiempos: el EXPLAIN
del sandbox corre sin `ANALYZE` (tablas vacías por R6). Cuando viene
`null` (sandbox apagado o `verdict="skipped_no_sandbox_signal"` por
recomendación tipo ANALYZE), la tarjeta muestra un mensaje neutral en
lugar del comparativo.

**Códigos de error:**

- `422` — body inválido (sin `query` o `query` vacía).
- `503` — AppDB no configurada al startup. El cliente ve la lista de
  env vars que faltan.
- `400` — Postgres rechazó la query (sintaxis, tabla inexistente,
  permiso denegado).
- `403` — el usuario intentó una mutación (UPDATE/INSERT/DROP). La
  conexión es read-only por R7.
- `504` — EXPLAIN excedió el `statement_timeout` (5s por default).
- `500` — estado inesperado interno. Tras E8 esto solo ocurre si la
  extracción (EXPLAIN) revienta de forma no-Postgres o si algo
  inesperado falla **fuera** del orquestador (el detalle se loggea; el
  cliente ve "Error interno al analizar la query."). Los fallos de
  etapas internas (parser, detector, recomendador, sandbox, LLM) NO
  producen 500 — devuelven `200` con `partial=true` (ver arriba).

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
  pools del state, generación de `request_id`). E8: propagación de
  `errors`/`partial` del orquestador y el 500 genérico (sin stack trace,
  sin filtrar detalles) ante un fallo inesperado fuera del orquestador.
- `test_cors.py` — preflight desde `localhost:5173`, header en POST
  real, bloqueo a orígenes no permitidos.
- `test_orchestrator.py` — tests directos de
  `backend.orchestrator.analyze_query` con `FakePool`. Cubre: no
  detección → arrays vacíos (con `errors=[]`, `partial=false`),
  detección → estructura completa, sandbox populando `verdict`, sandbox
  no configurado ≠ error, LLM mockeado marca `source="llm"`, mapeo de
  errores Postgres a `AnalyzeError` (400/403/504/500), y un fallo
  no-Postgres en la extracción → 500. **E8 — aislamiento por etapa:**
  romper `parse_explain`, el detector, el recomendador, `sanitize`, el
  sandbox o `explain_recommendation` → la pipeline sigue lo que puede,
  devuelve resultados parciales con la etapa en `errors` y `partial=true`,
  nunca crashea. El "hecho cuando" de C9 vive en
  `test_analyze_query_con_deteccion_devuelve_estructura_completa`; el de
  E8 en `test_analyze_query_llm_que_explota_devuelve_deterministico_y_flag`
  (LLM roto → detecciones + recomendaciones determinísticas + flag).

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

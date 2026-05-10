# Módulo `backend` — API HTTP de PgPilot

FastAPI que orquesta los módulos del proyecto y expone los endpoints que consume el frontend. Es el único módulo que conoce a todos los demás (`/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`); los módulos no se conocen entre sí.

**Lo que NO hace:** lógica de detección, parsing de SQL, llamadas al LLM. Eso vive en los módulos correspondientes; el backend solo orquesta.

---

## Estado actual

- ✅ B13 — endpoint `/analyze` stub con CORS para `localhost:5173`
- ⬜ C9 — conectar `/analyze` al motor real (parser + detectores + recomendador)
- ⬜ E3 — endpoint `/workload`
- ⬜ C8 — logs estructurados de interacciones con el LLM

---

## Cómo correrlo en desarrollo

```bash
# Desde la raíz del repo
.venv/bin/uvicorn backend.main:app --reload --port 8000
```

El backend queda en `http://localhost:8000`. Healthcheck rápido:

```bash
curl http://localhost:8000/health
```

---

## API pública

### `POST /analyze`

Recibe un SQL crudo y devuelve detecciones + recomendaciones.

**Request:**

```json
{ "query": "SELECT ..." }
```

**Response:**

```json
{
  "detections": [],
  "recommendations": []
}
```

`query` es obligatorio y no puede ser vacío (`min_length=1`); FastAPI responde 422 si falta o está vacío.

**Stub vs real:** B13 entrega listas vacías. El contrato del request y la respuesta es definitivo: cuando C9 conecte el motor, solo se llenarán los arrays. El frontend (B14) no necesita cambiar para soportarlo.

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

- `test_analyze.py` — contrato del endpoint (200 con stub, validación 422, healthcheck).
- `test_cors.py` — preflight desde `localhost:5173`, header en POST real, bloqueo a orígenes no permitidos.

Son unit (usan `fastapi.testclient.TestClient`, sin levantar uvicorn ni necesitar AppDB).

```bash
.venv/bin/python -m pytest tests/backend/ -v
```

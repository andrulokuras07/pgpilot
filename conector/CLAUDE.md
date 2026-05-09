# conector — módulo de conexión a la BD del cliente

## Propósito

Encapsula toda la comunicación con la BD que PgPilot analiza (AppDB en
desarrollo, BD del cliente en producción). Garantiza por construcción
que ninguna conexión emitida puede mutar la BD: cumple R7 (read-only
forzado) y la regla operativa de timeout duro de 5s.

**Lo que NO hace este módulo:** parsear SQL, evaluar planes, hablar
con el LLM, ejecutar nada contra el sandbox. Solo entrega conexiones
psycopg seguras.

## API pública

Exportado en `conector/__init__.py`:

### `ConnectionConfig` (dataclass frozen)
Parámetros para abrir el pool:
- `host: str`
- `port: int`
- `dbname: str`
- `user: str`
- `password: str`
- `statement_timeout_ms: int = 5000` — timeout aplicado por sesión
- `min_pool_size: int = 1`
- `max_pool_size: int = 4`

### `create_pool(config: ConnectionConfig) -> ConnectionPool`
Devuelve un `psycopg_pool.ConnectionPool` ya abierto. Cada conexión
del pool tiene aplicado en su sesión:
- `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`
- `SET statement_timeout = <statement_timeout_ms>`

Cualquier INSERT/UPDATE/DELETE/DDL/TRUNCATE en una conexión obtenida
del pool falla con `psycopg.errors.ReadOnlySqlTransaction`
(SQLSTATE `25006`).

### Uso típico
```python
from conector import ConnectionConfig, create_pool

pool = create_pool(ConnectionConfig(
    host="localhost", port=5434, dbname="appdb",
    user="app_user", password="app_pass",
))

with pool.connection() as conn:
    rows = conn.execute("SELECT count(*) FROM users").fetchone()

pool.close()
```

## Estructura interna

```
conector/
├── __init__.py     # exporta ConnectionConfig y create_pool
├── config.py       # dataclass ConnectionConfig
├── pool.py         # create_pool() con configure callback
└── CLAUDE.md       # este archivo
```

## Cómo extender

- **Nuevo parámetro de sesión** (ej: `search_path`, `application_name`):
  agregarlo como campo en `ConnectionConfig` con default sensato y
  emitir el `SET` correspondiente dentro del `configure` callback de
  `pool.py`. Mantener `commit()` al final.
- **Soporte de modo offline** (B6, en backlog): NO va aquí. Va en un
  módulo paralelo (ej: `conector/offline.py`) que no necesita pool
  porque parsea desde un dump. La API pública debe seguir devolviendo
  el mismo dict de metadata para que B5 (cache) no distinga origen.
- **Extractor de schema, pg_stats, tamaños** (B2-B4): no modifican
  este archivo. Crearán nuevas funciones `get_schema(pool)`,
  `get_table_sizes(pool)`, etc. en archivos propios del módulo.

## Decisiones específicas del módulo

- **Read-only se fuerza por SESSION CHARACTERISTICS**, no per-transacción.
  Más robusto: imposible olvidarlo en un código nuevo. Se aplica en
  el `configure` callback que psycopg_pool corre una sola vez por
  conexión nueva del pool.
- **`statement_timeout` es de sesión, no per-query.** Si un caller
  necesita más tiempo para una query específica (no debería en este
  proyecto), tendría que abrir su propio `SET LOCAL statement_timeout`
  dentro de una transacción explícita.
- **Pool abierto al construir** (`open=True`). Si AppDB está caída,
  la excepción aparece al instante en lugar de en la primera query.

## Tests

Los tests viven en `tests/conector/`:
- `test_pool.py`: cuatro tests de integración (marcados con
  `@pytest.mark.integration`) que verifican SELECT, rechazo de INSERT,
  rechazo de DDL, y aborto por `statement_timeout`.

**Cómo correrlos:**
```bash
# Requisito: AppDB levantado (docker compose up appdb)
pip install -r requirements.txt
pytest tests/conector
```

Variables de entorno opcionales (defaults en `.env.example`):
`APPDB_HOST`, `APPDB_PORT`, `APPDB_DB`, `APPDB_USER`, `APPDB_PASSWORD`.

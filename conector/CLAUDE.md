# conector — módulo de conexión a la BD del cliente

## Propósito

Encapsula toda la comunicación con la BD que PgPilot analiza (AppDB en
desarrollo, BD del cliente en producción). Garantiza por construcción
que ninguna conexión emitida puede mutar la BD: cumple R7 (read-only
forzado) y la regla operativa de timeout duro de 5s. Además expone
extractores que leen la metadata necesaria para que el motor decida:
estructura del schema y tamaños de tabla.

**Lo que NO hace este módulo:** parsear SQL, evaluar planes, hablar
con el LLM, ejecutar nada contra el sandbox. Solo entrega conexiones
psycopg seguras y dicts con metadata.

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

### `get_schema(pool, schemas=("public",)) -> dict[str, TableSchema]`
Extractor de schema (B2). Devuelve un dict indexado por
`"<schema>.<tabla>"`. Cada entrada es un `TableSchema` (TypedDict)
con:
- `schema: str`, `name: str`
- `columns: list[ColumnInfo]` con `name`, `data_type` (formato
  `format_type`, ej. `"character varying(50)"`), `is_nullable`,
  `ordinal_position`
- `indexes: list[IndexInfo]` con `name`, `columns` (en orden del
  índice), `method` (`btree`, `gin`, etc.), `is_unique`, `is_primary`
- `foreign_keys: list[ForeignKeyInfo]` con `name`, `columns`,
  `referenced_schema`, `referenced_table`, `referenced_columns`

Las queries van contra `pg_catalog` (no `information_schema`) para
preservar orden de columnas en índices y manejar correctamente FKs
compuestos.

### `get_table_sizes(pool, schemas=("public",)) -> dict[str, TableSize]`
Extractor de tamaños (B3). Devuelve un dict con la misma forma de
clave que `get_schema`. Cada entrada es un `TableSize` con:
- `estimated_rows: int` — `pg_class.reltuples`. Si Postgres reporta
  `-1` (sin ANALYZE), se normaliza a `0` y `category="unknown"`.
- `total_bytes: int` — `pg_total_relation_size` (heap + índices + toast)
- `category: SizeCategory` — `"small" | "medium" | "large" | "unknown"`

También exporta `categorize(estimated_rows: int) -> SizeCategory` como
función pura para tests y para que `/motor` clasifique sin ir a la BD.
Thresholds: `SMALL_ROWS_THRESHOLD = 100_000`,
`LARGE_ROWS_THRESHOLD = 1_000_000`.

### Uso típico
```python
from conector import (
    ConnectionConfig, create_pool, get_schema, get_table_sizes,
)

pool = create_pool(ConnectionConfig(
    host="localhost", port=5434, dbname="appdb",
    user="app_user", password="app_pass",
))

schema = get_schema(pool)
sizes = get_table_sizes(pool)

posts = schema["public.posts"]
posts_size = sizes["public.posts"]

pool.close()
```

## Estructura interna

```
conector/
├── __init__.py     # exporta API pública del módulo
├── config.py       # dataclass ConnectionConfig
├── pool.py         # create_pool() con configure callback
├── schema.py       # get_schema() + TypedDicts de metadata (B2)
├── sizes.py        # get_table_sizes() + categorize() (B3)
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
- **Extractor de pg_stats** (B4, pendiente): no modifica
  `schema.py`. Crear `conector/stats.py` con
  `get_column_stats(pool)` que devuelva por columna `n_distinct`,
  `null_frac`, `most_common_vals`, `correlation`, manejando el caso
  "tabla sin ANALYZE" con un valor explícito.
- **Nuevo campo en el schema extraído** (ej. exclusion constraints,
  índices con expresiones): agregar el campo al `TypedDict`
  correspondiente en `schema.py` y extender la query SQL. Mantener la
  forma del dict estable porque B5 hashea esto.

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
- **Las claves de los dicts de metadata son `"<schema>.<tabla>"`,**
  no solo el nombre de la tabla. Esto evita colisiones cuando hay
  tablas homónimas en schemas distintos y permite que `/motor`
  intersecte `get_schema` y `get_table_sizes` por la misma clave.
- **`reltuples = -1` se reporta como `estimated_rows = 0` con
  `category = "unknown"`.** El motor debe tratar `"unknown"` distinto
  de `"small"`: una tabla sin ANALYZE no es seguro afirmar que sea
  chica. No silenciamos el caso, lo marcamos.
- **Las queries de metadata no usan regex sobre nombres ni hardcodean
  tablas.** Operan sobre `pg_catalog` con un filtro de schemas
  parametrizado. Esto cumple R14 y protege el bonus de AppDB v2.

## Tests

Los tests viven en `tests/conector/`:
- `test_pool.py`: cuatro tests de integración que verifican SELECT,
  rechazo de INSERT, rechazo de DDL y aborto por `statement_timeout`.
- `test_schema.py`: siete tests de integración que verifican que
  `get_schema` devuelve las tablas, columnas, índices y FKs esperados
  de AppDB. Incluye un test que confirma la ausencia de índice en
  `posts.author_id` (Q01 plantada).
- `test_sizes.py`: cuatro tests de unidad de `categorize` (puros) más
  tres tests de integración de `get_table_sizes` que verifican
  consistencia entre `estimated_rows` y `category`.

Los tests de integración están marcados con `@pytest.mark.integration`
y requieren AppDB levantado.

**Cómo correrlos:**
```bash
# Solo unit tests (no necesitan AppDB)
pytest tests/conector -m "not integration"

# Todo (requiere docker compose up appdb)
pip install -r requirements.txt
pytest tests/conector
```

Variables de entorno opcionales (defaults en `.env.example`):
`APPDB_HOST`, `APPDB_PORT`, `APPDB_DB`, `APPDB_USER`, `APPDB_PASSWORD`.

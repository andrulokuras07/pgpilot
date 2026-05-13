# conector — módulo de conexión a la BD del cliente

> **Doc externo:** la guía de uso orientada a personas fuera del equipo
> vive en `docs/conector.md` (E10). Si cambias firmas o comportamiento
> de la API pública listada abajo, actualiza también ese archivo en el
> mismo commit (R15) para no dejar el doc externo divergido.

## Propósito

Encapsula toda la comunicación con la BD que PgPilot analiza (AppDB en
desarrollo, BD del cliente en producción). Garantiza por construcción
que ninguna conexión emitida puede mutar la BD: cumple R7 (read-only
forzado) y la regla operativa de timeout duro de 5s. Además expone
extractores que leen la metadata necesaria para que el motor decida:
estructura del schema, tamaños de tabla, estadísticas por columna,
cache local y modo offline (bundle JSON sin conexión viva).

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

### `get_column_stats(pool, schemas=("public",)) -> dict[str, dict[str, ColumnStats]]`
Extractor de estadísticas por columna (B4). La estructura es
`{"<schema>.<tabla>": {"<columna>": ColumnStats, ...}, ...}`. Cada
`ColumnStats` (TypedDict) incluye:
- `has_stats: bool` — `False` cuando la columna no tiene fila en
  `pg_stats` (tabla nunca `ANALYZE`-ada). En ese caso los demás campos
  son `None`.
- `n_distinct: float | None` — convención Postgres: positivo = conteo
  absoluto, negativo = ratio respecto al total de filas.
- `null_frac: float | None` — fracción de NULLs (0..1).
- `most_common_vals: list[str] | None` — los MCV serializados a texto
  vía `most_common_vals::text::text[]`.
- `correlation: float | None` — correlación física vs lógica (-1..1).
  Puede ser `None` aun con `has_stats=True` para tipos no ordenables.

Las claves coinciden con `get_schema` y `get_table_sizes`, lo que
permite intersectarlas por la misma `"<schema>.<tabla>"`.

### `SchemaSnapshot` (TypedDict)
Snapshot consolidado producido por `extract_snapshot`:
- `schema: dict[str, TableSchema]` — salida de `get_schema`
- `sizes: dict[str, TableSize]` — salida de `get_table_sizes`
- `stats: dict[str, dict[str, ColumnStats]]` — salida de
  `get_column_stats`

Mismo formato lo persisten el cache (B5) y los bundles offline (B6).

### `extract_snapshot(pool, schemas=("public",)) -> SchemaSnapshot`
Combina B2 + B3 + B4 en una sola llamada. Función pura (no toca
disco).

### `get_snapshot(pool, schemas, *, fingerprint=None, cache_dir=Path("cache"), force_refresh=False) -> SchemaSnapshot`
High-level orchestrator del cache (B5):
- Si `fingerprint` es `None`, equivale a `extract_snapshot` (no toca
  disco).
- Si `fingerprint` es dado y existe `cache/{fingerprint}.json` y
  `force_refresh=False`, lee y devuelve el cache. Garantiza <100ms
  de latencia en cache hit (verificado en `test_cache.py`).
- Si no existe o `force_refresh=True`, extrae fresco y persiste.

### `compute_fingerprint(host, port, dbname, schemas) -> str`
Hash md5 de la identidad de la BD (no del contenido). Es lo que se
usa como nombre de archivo del cache. No depende del orden de
`schemas`.

### `compute_content_hash(snapshot) -> str`
Hash md5 del snapshot serializado en JSON canónico (`sort_keys=True`).
Sirve para detectar drift entre dos extracciones de la misma BD.

### `save_snapshot(snapshot, fingerprint, cache_dir=Path("cache"), schemas=("public",)) -> Path`
Persiste un snapshot en `cache/{fingerprint}.json`. Crea el directorio
si no existe. El archivo escrito contiene `fingerprint`,
`content_hash`, `extracted_at`, `schemas` y `snapshot`.

### `load_snapshot(fingerprint, cache_dir=Path("cache")) -> SchemaSnapshot | None`
Lee un snapshot cacheado. `None` si no existe.

### `invalidate_cache(cache_dir=Path("cache"), fingerprint=None) -> int`
Borra archivos. `fingerprint=None` borra todos los `*.json` del
directorio. Devuelve cuántos eliminó. No falla si no hay nada que
borrar.

### `export_bundle(pool, path, schemas, *, host, port, dbname) -> Path`
Modo offline (B6). Extrae snapshot y lo escribe a `path` como bundle
JSON portable. Mismo formato que el cache. El cliente corre esta
función en su entorno y comparte el archivo; PgPilot no necesita
acceso vivo a la BD del cliente.

`host`, `port`, `dbname` se reciben explícitos (no se leen del pool)
para permitir anonimización por parte del cliente (ej.
`dbname="redacted"`).

### `load_bundle(path) -> SchemaSnapshot`
Carga un bundle producido por `export_bundle` y devuelve el
`SchemaSnapshot`. Operación puramente offline: no toca pool ni red.

### `validate_bundle(path) -> bool`
Recalcula `content_hash` del bundle y lo compara con el campo
guardado. Detecta tampering o corrupción en tránsito.

### Uso típico
```python
from pathlib import Path

from conector import (
    ConnectionConfig, create_pool,
    get_schema, get_table_sizes, get_column_stats,
    extract_snapshot, get_snapshot, compute_fingerprint,
    export_bundle, load_bundle,
)

pool = create_pool(ConnectionConfig(
    host="localhost", port=5434, dbname="appdb",
    user="app_user", password="app_pass",
))

# Flujo individual (B2 + B3 + B4)
schema = get_schema(pool)
sizes = get_table_sizes(pool)
stats = get_column_stats(pool)

# Flujo combinado con cache (B5)
fp = compute_fingerprint("localhost", 5434, "appdb", ("public",))
snap = get_snapshot(pool, fingerprint=fp, cache_dir=Path("cache"))
posts_stats = snap["stats"]["public.posts"]["author_id"]

# Flujo offline (B6) — el cliente exporta y nos comparte el archivo
export_bundle(pool, Path("client_bundle.json"),
              host="localhost", port=5434, dbname="appdb")
remote = load_bundle(Path("client_bundle.json"))

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
├── stats.py        # get_column_stats() + ColumnStats (B4)
├── types.py        # SchemaSnapshot (compartido cache + offline)
├── cache.py        # extract_snapshot, get_snapshot, hashes, I/O (B5)
├── offline.py      # export_bundle, load_bundle, validate_bundle (B6)
└── CLAUDE.md       # este archivo
```

## Cómo extender

- **Nuevo parámetro de sesión** (ej: `search_path`, `application_name`):
  agregarlo como campo en `ConnectionConfig` con default sensato y
  emitir el `SET` correspondiente dentro del `configure` callback de
  `pool.py`. Mantener `commit()` al final.
- **Nuevo campo en el schema extraído** (ej. exclusion constraints,
  índices con expresiones): agregar el campo al `TypedDict`
  correspondiente en `schema.py` y extender la query SQL. Mantener la
  forma del dict estable porque `compute_content_hash` (B5) hashea esto;
  cualquier cambio invalida los caches existentes (correctamente).
- **Nuevo extractor (paralelo a stats/sizes/schema)**: archivo nuevo en
  `conector/`, función pura `get_X(pool, schemas)`, sumar al
  `extract_snapshot` de `cache.py` y agregar el dict al
  `SchemaSnapshot` en `types.py`. Tests con marker `integration`.
- **Parser real de `pg_dump --schema-only` para B6**: el modo offline
  actual acepta un bundle JSON, no SQL crudo. Si en el futuro un
  cliente prefiere darnos el dump SQL, crear `conector/offline_pg_dump.py`
  con un parser sqlglot que produzca el mismo `SchemaSnapshot`.
  Mantener `load_bundle` actual como entrada canónica.

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
- **`pg_stats` se consulta vía LEFT JOIN contra `pg_attribute`**
  (`stats.py`). Garantiza una entrada por columna existente, con
  `has_stats=False` cuando no hay fila en `pg_stats`. Nunca silenciamos
  "sin ANALYZE": el motor lo distingue de `null_frac=0`.
- **El cache se nombra por `fingerprint` (identidad de la BD), no por
  `content_hash`**. El backlog literal pedía `cache/{hash}.json`, pero
  eso requiere re-extraer para saber qué archivo leer. Guardamos el
  `content_hash` dentro del JSON para detección de drift; el nombre del
  archivo identifica la BD. Justificación detallada en `PROGRESS.md`
  2026-05-09.
- **El modo offline acepta un bundle JSON, no `pg_dump` SQL crudo**.
  Mismo formato que el cache. El cliente corre `export_bundle()` en su
  entorno y nos comparte el archivo. Razonamiento técnico y trade-offs
  en `PROGRESS.md` 2026-05-09 (decisión "Modo offline: bundle JSON vs
  pg_dump").
- **Cache directory es `cache/` por default y está en `.gitignore`**.
  Cada dev regenera el cache con su propia BD; no se versiona.

## Tests

Los tests viven en `tests/conector/`:
- `test_pool.py`: cuatro tests de integración (SELECT, rechazo de
  INSERT, rechazo de DDL, aborto por `statement_timeout`).
- `test_schema.py`: siete tests de integración que verifican que
  `get_schema` devuelve las tablas, columnas, índices y FKs esperados
  de AppDB. Incluye un test que confirma la ausencia de índice en
  `posts.author_id` (Q01 plantada).
- `test_sizes.py`: cuatro unit tests de `categorize` más tres de
  integración de `get_table_sizes`.
- `test_stats.py`: siete tests de integración de `get_column_stats`
  (cobertura de tablas, rangos válidos de `null_frac`/`correlation`,
  manejo de `has_stats=False`, consistencia de claves con `get_schema`).
- `test_cache.py`: 10 unit tests puros (fingerprint, content_hash,
  save/load, invalidate) más 4 de integración (extract_snapshot,
  cache hit <100ms, force_refresh, sin fingerprint no toca disco).
- `test_offline.py`: 4 tests de integración (export+load equivalentes
  a extract en vivo, metadata del bundle, detección de tampering,
  load sin pool).

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

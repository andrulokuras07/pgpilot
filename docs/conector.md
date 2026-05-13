# Módulo `conector` — guía de uso

> **Audiencia:** developers fuera del equipo de PgPilot que quieran
> entender, evaluar o reutilizar el módulo `/conector` en sus propios
> flujos contra Postgres.
>
> **Resumen en una línea:** el conector entrega conexiones psycopg
> **forzadas a read-only** contra la BD del cliente, y extrae snapshots
> de metadata (schema + tamaños + estadísticas) listos para que un
> analizador de queries decida sin ejecutar nada peligroso.

---

## 1. ¿Qué hace este módulo?

`conector/` cumple **tres responsabilidades** y nada más:

1. **Conexiones seguras** a una BD Postgres del cliente
   (`ConnectionConfig` + `create_pool`). Por construcción son read-only
   y tienen un `statement_timeout` corto. Es imposible mutar la BD
   usando este pool — Postgres rechaza la operación a nivel de sesión.
2. **Extracción de metadata** (`get_schema`, `get_table_sizes`,
   `get_column_stats`) que produce diccionarios tipados con todo lo
   necesario para razonar sobre planes de ejecución: columnas, tipos,
   índices, FKs, tamaños y estadísticas por columna.
3. **Persistencia local** (cache `cache/{fingerprint}.json`) y **modo
   offline** (`export_bundle` / `load_bundle`): el cliente puede
   ejecutar el extractor en su entorno y compartir un JSON portable
   con PgPilot sin abrir nunca una conexión hacia nuestra
   infraestructura.

**Lo que NO hace:** parsear SQL, evaluar planes, hablar con un LLM o
abrir conexiones hacia otras BDs además de la del cliente. Esas
responsabilidades viven en `/motor`, `/ia` y `/sandbox` del producto
principal.

---

## 2. Requisitos e instalación

- **Python 3.11+**.
- **Postgres 12+** en la BD del cliente (probado contra 16).
- Dependencias declaradas en `requirements.txt` de la raíz del repo;
  las relevantes para este módulo son:

  ```text
  psycopg[binary]>=3.1,<4
  psycopg-pool>=3.2,<4
  ```

Instalación desde la raíz del repo, ya en un virtualenv:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # macOS / Linux
# o, en PowerShell:
.venv\Scripts\pip install -r requirements.txt
```

No hay variables de entorno requeridas por el módulo en sí — la
configuración se pasa explícitamente al constructor de
`ConnectionConfig`. Si tu flujo prefiere env vars (por ejemplo para
inyectar credenciales en CI), tú las lees y se las pasas al
`ConnectionConfig`.

---

## 3. Inicio rápido

Diez líneas funcionales contra una BD Postgres local:

```python
from conector import ConnectionConfig, create_pool, extract_snapshot

pool = create_pool(
    ConnectionConfig(
        host="localhost", port=5432, dbname="mi_app",
        user="readonly_user", password="…",
    )
)

snapshot = extract_snapshot(pool, schemas=("public",))
print(snapshot["schema"]["public.posts"]["columns"])
print(snapshot["sizes"]["public.posts"])
print(snapshot["stats"]["public.posts"]["author_id"])

pool.close()
```

Las claves del snapshot son siempre `"<schema>.<tabla>"` para evitar
colisiones entre schemas distintos.

---

## 4. Garantías de seguridad

Estas dos garantías son contractuales — si las rompes, el módulo deja
de servir y la BD del cliente queda expuesta. Por eso vienen
hardcodeadas en `create_pool`, no como opciones.

### 4.1. Read-only forzado

Cada conexión que entrega el pool aplica al instante de obtenerla:

```sql
SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;
```

Cualquier `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `CREATE`,
`ALTER`, `DROP` o `COMMENT ON` falla con
`psycopg.errors.ReadOnlySqlTransaction` (SQLSTATE `25006`).
**No hay flag para apagar esto.**

Demostración rápida:

```python
with pool.connection() as conn:
    conn.execute("SELECT 1")                       # OK
    conn.execute("INSERT INTO posts VALUES (1)")   # raises ReadOnlySqlTransaction
```

### 4.2. Timeout por sesión

Cada conexión aplica también:

```sql
SET statement_timeout = <statement_timeout_ms>;   -- default: 5000
```

Cualquier statement que exceda ese tiempo es abortado por Postgres
con `psycopg.errors.QueryCanceled` (SQLSTATE `57014`). Esto protege
contra extracciones que se demoren más de lo esperado en BDs muy
grandes (raro — las queries de metadata son baratas) y, sobre todo,
contra clientes maliciosos que monten una BD lenta a propósito.

Si tu caso de uso necesita más tiempo de manera puntual,
**no apagues el default**: abre una transacción explícita con
`SET LOCAL statement_timeout = …` para esa query específica.

---

## 5. API de referencia

### 5.1. Conexión

#### `ConnectionConfig` (frozen dataclass)

| Campo | Tipo | Default | Descripción |
|---|---|---|---|
| `host` | `str` | — | Host de Postgres. |
| `port` | `int` | — | Puerto TCP. |
| `dbname` | `str` | — | Nombre de la base. |
| `user` | `str` | — | Usuario con permisos `SELECT`. |
| `password` | `str` | — | Password (pasarla en claro está OK aquí; el módulo no la persiste). |
| `statement_timeout_ms` | `int` | `5000` | Timeout aplicado por sesión. |
| `min_pool_size` | `int` | `1` | Conexiones mínimas en el pool. |
| `max_pool_size` | `int` | `4` | Conexiones máximas en el pool. |

#### `create_pool(config: ConnectionConfig) -> psycopg_pool.ConnectionPool`

Devuelve un pool ya abierto (`open=True`). Cada conexión del pool
aplica las dos garantías de la sección 4 a través del `configure`
callback de psycopg, una sola vez al crear la conexión.

Si la BD está caída o el password es incorrecto, la excepción se
levanta **al construir el pool**, no en la primera query. Esto te
permite fallar temprano y con un mensaje claro.

Cierra el pool con `pool.close()` cuando termines (idealmente desde un
`try/finally` o un context manager propio).

---

### 5.2. Extracción de metadata (operaciones individuales)

Todas reciben un pool y una tupla de schemas a inspeccionar (default
`("public",)`). Devuelven dicts indexados por `"<schema>.<tabla>"`.

#### `get_schema(pool, schemas=("public",)) -> dict[str, TableSchema]`

Estructura del schema. Cada entrada `TableSchema` contiene:

```python
{
    "schema": "public",
    "name": "posts",
    "columns": [
        {
            "name": "id",
            "data_type": "integer",           # output de pg_catalog.format_type
            "is_nullable": False,
            "ordinal_position": 1,
        },
        # …
    ],
    "indexes": [
        {
            "name": "posts_pkey",
            "columns": ["id"],                # en el orden del índice
            "method": "btree",                # btree, gin, gist, …
            "is_unique": True,
            "is_primary": True,
        },
        # …
    ],
    "foreign_keys": [
        {
            "name": "posts_author_fk",
            "columns": ["author_id"],
            "referenced_schema": "public",
            "referenced_table": "users",
            "referenced_columns": ["id"],
        },
    ],
}
```

Las queries van contra `pg_catalog`, no `information_schema`. Esto
**preserva el orden de columnas en índices compuestos** y maneja
correctamente las FKs compuestas, cosas que `information_schema`
pierde.

#### `get_table_sizes(pool, schemas=("public",)) -> dict[str, TableSize]`

Tamaños estimados de cada tabla, leídos de `pg_class`:

```python
{
    "estimated_rows": 523_412,          # pg_class.reltuples
    "total_bytes": 256_000_000,         # heap + índices + toast
    "category": "large",                # small | medium | large | unknown
}
```

Si `reltuples == -1` (la tabla nunca fue analizada con `ANALYZE`),
el módulo normaliza a `estimated_rows=0` y `category="unknown"`. No se
silencia el caso — un analizador downstream debería tratar `"unknown"`
distinto de `"small"`.

Thresholds expuestos como constantes para que tus reglas puedan
reproducir la clasificación sin tocar la BD:

```python
from conector import SMALL_ROWS_THRESHOLD, LARGE_ROWS_THRESHOLD, categorize

SMALL_ROWS_THRESHOLD       # 100_000
LARGE_ROWS_THRESHOLD       # 1_000_000
categorize(50_000)         # "small"
categorize(523_412)        # "medium"  (entre los dos thresholds)
categorize(5_000_000)      # "large"
categorize(-1)             # "unknown"
```

#### `get_column_stats(pool, schemas=("public",)) -> dict[str, dict[str, ColumnStats]]`

Estadísticas por columna desde `pg_stats`. La estructura es
`{"<schema>.<tabla>": {"<columna>": ColumnStats}}`. Cada `ColumnStats`:

```python
{
    "has_stats": True,                  # False si la tabla no fue ANALYZE-ada
    "n_distinct": 1234.0,               # convención Postgres (ver abajo)
    "null_frac": 0.02,                  # 0..1
    "most_common_vals": ["A", "B"],     # MCV serializados a texto
    "correlation": 0.93,                # -1..1, puede ser None
}
```

**Convención de `n_distinct` (heredada de Postgres):**

- Valor **positivo**: número absoluto de valores distintos en la columna.
- Valor **negativo**: ratio de cardinalidad respecto al total de filas
  (`-1.0` = todas distintas, `-0.5` = la mitad son distintas).

**Cuando `has_stats=False`** (sin `ANALYZE`), los otros campos son
`None`. No es lo mismo que `null_frac=0.0`: distinguir esto importa
para no inventar selectividades.

---

### 5.3. Snapshot consolidado

#### `SchemaSnapshot` (TypedDict)

```python
{
    "schema": dict[str, TableSchema],
    "sizes":  dict[str, TableSize],
    "stats":  dict[str, dict[str, ColumnStats]],
}
```

Las claves de los tres sub-dicts son las mismas — puedes intersectar
por `"<schema>.<tabla>"` sin más.

#### `extract_snapshot(pool, schemas=("public",)) -> SchemaSnapshot`

Combina `get_schema` + `get_table_sizes` + `get_column_stats` en una
sola llamada. No toca disco; función pura desde el punto de vista del
caller.

---

### 5.4. Cache local

El cache evita re-extraer la metadata en cada análisis. Hit típico:
**<100 ms** (verificado en `test_cache.py`). Miss: lo que tarde la
extracción contra la BD (segundos en BDs grandes).

#### `compute_fingerprint(host, port, dbname, schemas) -> str`

Hash md5 de la **identidad de la BD** (no del contenido). Independiente
del orden de `schemas` (se ordena internamente). Es lo que se usa como
nombre de archivo del cache.

```python
from conector import compute_fingerprint

fp = compute_fingerprint("db.prod", 5432, "myapp", ("public", "billing"))
# 'a3f9b7c2…'
```

#### `get_snapshot(pool, schemas=("public",), *, fingerprint=None, cache_dir=Path("cache"), force_refresh=False) -> SchemaSnapshot`

Orquestador del cache.

| `fingerprint` | `force_refresh` | Comportamiento |
|---|---|---|
| `None` | cualquiera | No toca disco. Equivale a `extract_snapshot`. |
| `"abc…"` | `False` | Si `cache/abc….json` existe, devuelve el cacheado. Si no, extrae y guarda. |
| `"abc…"` | `True`  | Ignora el cache, extrae fresco y sobrescribe el archivo. |

Uso típico:

```python
fp = compute_fingerprint("localhost", 5432, "myapp", ("public",))
snap = get_snapshot(pool, fingerprint=fp)   # primera vez: extrae y guarda
snap = get_snapshot(pool, fingerprint=fp)   # segunda vez: cache hit (<100ms)
```

#### `compute_content_hash(snapshot) -> str`

Hash md5 del snapshot serializado en JSON canónico (`sort_keys=True`).
Cambia si **cualquier** dato del snapshot cambia (schema, tamaños,
stats). Útil para detectar drift entre extracciones:

```python
fp = compute_fingerprint(...)
viejo = load_snapshot(fp)
nuevo = extract_snapshot(pool)
if compute_content_hash(viejo) != compute_content_hash(nuevo):
    print("La BD cambió desde el último cache.")
```

#### `save_snapshot(snapshot, fingerprint, cache_dir=Path("cache"), schemas=("public",)) -> Path`

Persiste un snapshot al disco. Crea el directorio si no existe.
Devuelve la ruta escrita. El JSON guardado incluye `fingerprint`,
`content_hash`, `extracted_at` (UTC ISO-8601), `schemas` y `snapshot`.

#### `load_snapshot(fingerprint, cache_dir=Path("cache")) -> SchemaSnapshot | None`

Lee un cache local. `None` si no existe. **No valida frescura** — si
necesitas asegurarte de que la BD no cambió, recalcula
`compute_content_hash` y compara, o llama `get_snapshot` con
`force_refresh=True`.

#### `invalidate_cache(cache_dir=Path("cache"), fingerprint=None) -> int`

Borra archivos `.json` del directorio. Devuelve cuántos eliminó.

- `fingerprint=None` → borra **todos** los caches.
- `fingerprint="abc…"` → borra solo ese.

No falla si el directorio o el archivo no existen.

```python
from conector import invalidate_cache

invalidate_cache(fingerprint=fp)       # borra solo ese
invalidate_cache()                     # borra todos
```

---

### 5.5. Modo offline (bundle JSON portable)

Este es el flujo cuando **no quieres dar acceso de red** a la BD del
cliente. El cliente corre el exportador en su entorno y comparte un
único archivo JSON portable.

```
   Cliente (con acceso a su BD)              PgPilot
   ┌──────────────────────────┐         ┌──────────────┐
   │  export_bundle(pool, …)  │  →→→    │ load_bundle  │
   │  → bundle.json (~MBs)    │ archivo │  → snapshot  │
   └──────────────────────────┘         └──────────────┘
```

**El bundle es exactamente el mismo formato que el cache de la 5.4.**
Eso significa que el snapshot que devuelve `load_bundle` es
indistinguible (a nivel de tipos) del que devuelve `extract_snapshot`
o `get_snapshot`.

#### `export_bundle(pool, path, schemas=("public",), *, host, port, dbname) -> Path`

Extrae snapshot y lo serializa al `path` indicado.

`host`, `port`, `dbname` se pasan **explícitos** (no se leen del pool)
para permitir anonimización por parte del cliente:

```python
export_bundle(
    pool, Path("client_bundle.json"),
    schemas=("public",),
    host="redacted", port=0, dbname="redacted",   # nada útil para identificar
)
```

#### `load_bundle(path) -> SchemaSnapshot`

Carga un bundle producido por `export_bundle`. Operación 100% offline:
no toca pool ni red.

#### `validate_bundle(path) -> bool`

Recalcula `content_hash` del snapshot del bundle y lo compara con el
campo `content_hash` guardado en el archivo. `True` si coincide,
`False` si fue manipulado o corrompido en tránsito.

```python
from conector import validate_bundle

if not validate_bundle(Path("client_bundle.json")):
    raise RuntimeError("El bundle no pasa integridad — descártalo.")
```

---

## 6. Errores y excepciones

| Excepción | Cuándo | Cómo manejarla |
|---|---|---|
| `psycopg.errors.OperationalError` | BD inalcanzable / autenticación falla al construir el pool. | Reintentar con backoff o reportar al usuario. |
| `psycopg.errors.ReadOnlySqlTransaction` | El caller intentó escribir contra la BD. | **No la atrapes** — es una señal de bug. |
| `psycopg.errors.QueryCanceled` | Un statement excedió `statement_timeout_ms`. | Subir el timeout puntualmente con `SET LOCAL`, o investigar por qué la query de metadata tardó tanto. |
| `psycopg.errors.UndefinedTable` / `UndefinedColumn` | Schema inexistente o nombre mal pasado. | Validar el input antes de llamar. |
| `FileNotFoundError` | `load_bundle(Path)` con archivo inexistente. | Verificar la ruta del cliente. |
| `json.JSONDecodeError` | Bundle / cache corrupto. | Borrar y re-extraer, o pedir un nuevo bundle al cliente. |

---

## 7. Ejemplos completos

### 7.1. Pipeline online con cache

```python
from pathlib import Path

from conector import (
    ConnectionConfig, create_pool,
    compute_fingerprint, get_snapshot,
)

pool = create_pool(ConnectionConfig(
    host="db.empresa.local", port=5432, dbname="appdb",
    user="readonly_pgpilot", password="…",
))

try:
    fp = compute_fingerprint("db.empresa.local", 5432, "appdb", ("public",))
    snapshot = get_snapshot(
        pool,
        schemas=("public",),
        fingerprint=fp,
        cache_dir=Path(".pgpilot_cache"),
    )
    # snapshot["schema"], snapshot["sizes"], snapshot["stats"] disponibles
finally:
    pool.close()
```

### 7.2. Flujo cliente → PgPilot sin acceso de red

**En la máquina del cliente** (acceso a su BD):

```python
from pathlib import Path
from conector import ConnectionConfig, create_pool, export_bundle

pool = create_pool(ConnectionConfig(
    host="db.interna", port=5432, dbname="produccion",
    user="readonly_consultor", password="…",
))
try:
    export_bundle(
        pool, Path("/tmp/empresa_bundle.json"),
        schemas=("public", "billing"),
        host="redacted", port=0, dbname="redacted",
    )
finally:
    pool.close()

# El cliente nos comparte /tmp/empresa_bundle.json por el canal que prefiera.
```

**En la máquina de PgPilot** (sin acceso a la BD del cliente):

```python
from pathlib import Path
from conector import load_bundle, validate_bundle

bundle_path = Path("/inbox/empresa_bundle.json")
assert validate_bundle(bundle_path), "Bundle corrupto o manipulado"

snapshot = load_bundle(bundle_path)
# snapshot ya está listo — mismo shape que un extract_snapshot en vivo.
```

### 7.3. Refrescar el cache cuando la BD cambia

```python
from conector import (
    compute_fingerprint, compute_content_hash,
    load_snapshot, get_snapshot,
)

fp = compute_fingerprint("db.empresa.local", 5432, "appdb", ("public",))
cached = load_snapshot(fp)

# Forzar refresh si pasaron más de 24h o si el cliente avisó de cambios
fresh = get_snapshot(pool, fingerprint=fp, force_refresh=True)

if cached and compute_content_hash(cached) != compute_content_hash(fresh):
    print("La metadata cambió desde el último análisis.")
```

---

## 8. Limitaciones conocidas

- **No soporta autenticación por certificado** todavía. Usa `host`,
  `port`, `dbname`, `user`, `password` por construcción. Si necesitas
  TLS mutuo o SCRAM con keytab, pásalo vía `conninfo` extendido en
  `pool.py` (requiere un fork local del módulo o un PR upstream).
- **No persiste el password.** Si quieres reusar el pool entre
  procesos, tu wrapper se encarga del secreto.
- **`get_column_stats` puede saltarse columnas exóticas.** Tipos no
  ordenables (`json`, `jsonb`, arrays, geometrías) pueden tener
  `correlation=None` aun con `has_stats=True`. No es un bug; es la
  forma honesta de reportar lo que Postgres calcula.
- **El modo offline no acepta `pg_dump` SQL crudo.** Solo bundles JSON
  producidos por `export_bundle`. Soportar `pg_dump` requiere un
  parser custom para `ALTER TABLE OWNER`, `COMMENT ON`, extensions y
  el formato `anyarray` de `pg_stats.most_common_vals` — está documentado
  como ticket separado (`conector/offline_pg_dump.py`).
- **No hay TTL automático en el cache.** Si la BD del cliente cambia
  todos los días, tu wrapper debería borrar el cache (o pasar
  `force_refresh=True`) en el momento adecuado.
- **Schemas pasados son tuplas ordenables.** Si una BD usa nombres con
  caracteres especiales que rompen el orden lexicográfico ascendente,
  el `fingerprint` puede dividirse entre extracciones — usa siempre el
  mismo orden cuando llames `compute_fingerprint`.

---

## 9. Tests y CI

Los tests viven en `tests/conector/`. Se dividen en:

- **Unit** (sin Docker): `test_sizes.py::categorize`, los hashes y
  cache I/O en memoria de `test_cache.py`, validaciones puras de
  `test_offline.py`. Corren en menos de 1 segundo.

  ```bash
  pytest tests/conector -m "not integration"
  ```

- **Integration** (requieren Postgres levantado): el resto. Marcados
  con `@pytest.mark.integration`. Necesitan AppDB en `localhost:5434`
  con el seed cargado.

  ```bash
  docker compose up -d appdb
  pytest tests/conector
  ```

Variables de entorno opcionales (defaults en `.env.example` del repo):

```env
APPDB_HOST=localhost
APPDB_PORT=5434
APPDB_DB=appdb
APPDB_USER=app_user
APPDB_PASSWORD=app_pass
```

Suite del módulo: 43/43 verde al cierre de la fase 1.

---

## 10. Cómo extender

Las direcciones más comunes para extender el módulo, en orden de
dificultad:

1. **Parámetros nuevos de sesión** (`application_name`, `search_path`):
   añadirlos como campos opcionales en `ConnectionConfig` y emitir el
   `SET` correspondiente dentro del `configure` callback de `pool.py`.
   Recuerda terminar con `commit()` para que persistan.
2. **Más campos en el schema extraído** (constraints `EXCLUDE`,
   índices con expresiones, predicados parciales): añadir el campo al
   `TypedDict` correspondiente en `schema.py` y extender la query
   contra `pg_catalog`. Cualquier cambio invalida los caches
   anteriores — el `content_hash` lo detecta.
3. **Un extractor nuevo en paralelo a schema/sizes/stats** (por
   ejemplo, métricas de `pg_stat_user_tables`): un archivo nuevo en
   `conector/`, función pura `get_X(pool, schemas)`, agregarlo a
   `extract_snapshot` y al TypedDict `SchemaSnapshot`. Tests con
   `@pytest.mark.integration`.
4. **Parser de `pg_dump --schema-only`** para enriquecer el modo
   offline: `conector/offline_pg_dump.py` con un parser sqlglot. El
   objetivo es producir el mismo `SchemaSnapshot` que `extract_snapshot`,
   pero a partir de un dump SQL crudo. Es trabajo no trivial y por
   eso está fuera del alcance de B6.

---

## 11. Referencias

- Código fuente: `conector/` en la raíz del repo.
- Notas internas para mantenedores: `conector/CLAUDE.md`.
- Decisiones técnicas que dieron forma al módulo (cache nombrado por
  fingerprint, modo offline JSON vs `pg_dump`, separación
  `extract_snapshot` / `get_snapshot`): `PROGRESS.md`, entradas del
  2026-05-09.

Si encuentras algo confuso o falta documentar un escenario, abrí un
issue en el repo de PgPilot.

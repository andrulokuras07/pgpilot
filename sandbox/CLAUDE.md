# sandbox — Postgres efímero para validar planes

## Propósito

`/sandbox` monta schemas temporales en una segunda BD de Postgres
(distinta a la del cliente) y corre `EXPLAIN` ahí. Sirve para que
el motor pueda probar el plan de una query antes/después de aplicar
una recomendación de índice — sin tocar la BD del cliente, sin
copiar datos y sin riesgo de ejecutar la query.

**Lo que NO hace este módulo:**
- No habla con la BD del cliente (eso vive en `/conector`).
- No parsea EXPLAIN ni decide nada sobre el plan (eso vive en `/motor`).
- No habla con el LLM (eso vive en `/ia`).
- No serializa output al frontend (eso vive en `/backend`).

**Reglas vivas en este módulo:**
- **R6:** sandbox monta tablas vacías y falsea stats; prohibido copiar
  filas de la BD del cliente.
- **R9:** las funciones públicas son self-contained — cada llamada
  monta y dropea su propio schema, no comparte estado entre llamadas.
- **Timeout duro 5s** (regla operativa): aplicado a nivel de pool y
  reforzado por-llamada en `explain_in_sandbox`.

## Stack

- **Postgres 18** en el contenedor `sandbox` (puerto 5435 en
  desarrollo). Bumpeo deliberado: AppDB se queda en 16, sandbox sube a
  18 para tener `pg_restore_relation_stats`, función que persiste
  stats falseadas en `pg_class` con la validación nativa. Decisión
  documentada en `PROGRESS.md` 2026-05-10.
- `psycopg` 3.x con `psycopg_pool.ConnectionPool` (mismo stack que
  `/conector`, distinto pool).

## API pública

Exportado en `sandbox/__init__.py`:

### `SandboxConfig` (frozen dataclass)
Parámetros para abrir el pool:
- `host: str`, `port: int`, `dbname: str`, `user: str`, `password: str`
- `statement_timeout_ms: int = 5000` — timeout aplicado por sesión
- `min_pool_size: int = 1`, `max_pool_size: int = 4`

### `create_sandbox_pool(config) -> ConnectionPool`
Pool de conexiones al sandbox. Cada conexión queda con
`statement_timeout` aplicado a nivel de sesión. **No** se fuerza
read-only: el sandbox necesita DDL para montar y desmontar schemas.
La regla R7 (read-only forzado) NO aplica aquí porque sandbox es BD
propia de PgPilot, no del cliente.

### `setup_sandbox_schema(pool, snapshot, *, schema_name=None) -> str`
Monta un schema temporal con las tablas y stats del snapshot.
Devuelve el nombre del schema (autogenerado `analysis_<uuid_hex>` si
no se pasa).

Lo que hace, en orden, dentro de una sola transacción:
1. `CREATE SCHEMA analysis_xxx`.
2. Para cada tabla del snapshot:
   - `CREATE TABLE` con las columnas y tipos del snapshot
     (output de `format_type` tal cual). Respeta `NOT NULL` pero NO
     replica FOREIGN KEYs (no afectan al planner de SELECTs y
     complican el orden).
   - `CREATE INDEX` para cada índice del snapshot, conservando
     nombre, método (`btree`/`gin`/`gist`), unicidad y orden de
     columnas.
3. Para cada tabla con `category != "unknown"`:
   - `pg_restore_relation_stats(schemaname, relname, relpages,
     reltuples)` para falsear el tamaño. `relpages ≈ rows / 100`.

### `drop_sandbox_schema(pool, schema_name) -> None`
`DROP SCHEMA IF EXISTS ... CASCADE`. Idempotente.

### `validate_index_recommendation(pool, snapshot, query, recommendation, *, timeout_seconds=5.0, schema_name=None) -> ValidationResult`
Validador C3. Recibe una `motor.Recommendation` y la prueba en el
sandbox antes de devolvérsela al frontend. Flujo:
1. Si `recommendation.kind == "analyze"`: retorna verdict
   `"skipped_no_sandbox_signal"` sin tocar el pool (un ANALYZE sobre
   tablas vacías no informa — la prosa del motor pasa sin aval del
   sandbox).
2. Monta schema con `setup_sandbox_schema`.
3. `EXPLAIN (FORMAT JSON)` de `query` → plan_before.
4. `CREATE INDEX <recommendation.index_name>_c3 ON <schema>.<tabla>
   USING <method> (<column>)` en el schema temporal. El sufijo `_c3`
   evita colisión si la recomendación apuntase a un nombre ya existente
   en el schema (defensivo).
5. EXPLAIN otra vez → plan_after.
6. Compara con `verdict_from_plans`; dropea el schema en `finally`.

Diseño: el discriminador es el **tipo de nodo** sobre la tabla
recomendada, no el costo absoluto. En el sandbox las tablas están
vacías y `pg_class.relpages`/`reltuples` falseados conviven con el
tamaño físico del archivo, que el planner consulta y empuja costos a
~0.

**Truco para forzar la señal de tipo de nodo:** el EXPLAIN "after"
corre con `SET LOCAL enable_seqscan = off`. Verificado empíricamente
(2026-05-11) que sin este flag el planner prefiere Seq Scan aun con
el índice presente (costo=0 por archivo vacío), perdiendo la señal
estructural. Con el flag, el planner emite `Index Scan` cuando el
índice es aplicable y mantiene `Seq Scan` con `Disabled: true` cuando
no lo es (caso "índice irrelevante al filtro" — sigue siendo Seq Scan
porque no hay alternativa). Esto preserva el contraste positivo vs.
negativo que C3 necesita.

**Semántica acotada de `validated`:** dado el truco anterior, "validated"
no significa "el planner elegirá este índice en producción", significa
"el índice es **estructuralmente aplicable** al filtro de la query".
Falta validar selectividad real para afirmar lo primero — eso requiere
filas sintéticas o stats por columna (`pg_restore_attribute_stats`)
y queda como trabajo futuro. Para Demo Day v1 esta semántica es
suficiente: descarta los CREATE INDEX absurdos (mal columna, mal
método) sin pretender más de lo que el sandbox vacío puede afirmar.

### `ValidationResult` (frozen dataclass)
- `verdict: "validated" | "discarded" | "skipped_no_sandbox_signal"`
- `reason: str` — prosa para el usuario y para logs.
- `node_type_before`, `node_type_after: str | None` — tipos del nodo
  de scan sobre la tabla en cada corrida. `None` si la query no la
  tocó (descarte por inconsistencia query/recomendación).
- `cost_before`, `cost_after: float | None` — `total_cost` del nodo
  de scan. Útiles para logs y para que C4 pueda mencionarlos al LLM;
  **no se usan para decidir el veredicto** (ver razón arriba).
- `plan_rows_before`, `plan_rows_after: int | None` — `plan_rows` del
  nodo de scan (filas estimadas por el planner) en cada corrida (E7).
  Alimentan el comparativo enriquecido del frontend; **tampoco
  participan en el veredicto**. Default `None`: `None` cuando la query
  no tocó la tabla, en el short-circuit de `kind="analyze"`, o si un
  EXPLAIN no devolvió plan. **No hay campos de tiempo:** el EXPLAIN del
  sandbox corre sin `ANALYZE` (tablas vacías por R6 → un `EXPLAIN
  ANALYZE` no daría tiempos comparables a producción), así que no hay
  tiempo real que reportar.

### `verdict_from_plans(plan_before, plan_after, table_key) -> ValidationResult`
Función pura. Permite testear la lógica de veredicto sin levantar el
sandbox. La usan los unit tests de C3 y la usa internamente
`validate_index_recommendation`.

### `explain_in_sandbox(pool, snapshot, query, *, timeout_seconds=5.0, schema_name=None) -> motor.ExplainResult`
Orquesta el flujo completo:
1. Monta un schema temporal con `setup_sandbox_schema`.
2. Abre una transacción nueva, setea `SET LOCAL statement_timeout` y
   `SET LOCAL search_path = analysis_xxx, public`.
3. Corre `EXPLAIN (FORMAT JSON)` sobre la query (sin ANALYZE).
4. Parsea con `motor.parse_explain`.
5. Dropea el schema (incluso si el EXPLAIN explotó: cleanup en
   `try/finally`).

Devuelve el `motor.ExplainResult` listo para los detectores y el
recomendador. Si el EXPLAIN excede `timeout_seconds`, Postgres aborta
con `psycopg.errors.QueryCanceled` (SQLSTATE 57014) y el schema igual
se dropea.

### Uso típico

```python
from conector import extract_snapshot
from sandbox import SandboxConfig, create_sandbox_pool, explain_in_sandbox

sandbox_pool = create_sandbox_pool(SandboxConfig(
    host="localhost", port=5435, dbname="sandbox",
    user="sandbox_user", password="sandbox_pass",
))

snapshot = extract_snapshot(appdb_pool)
result = explain_in_sandbox(
    sandbox_pool,
    snapshot,
    "SELECT * FROM posts WHERE author_id = 42",
)
print(result.root.node_type)  # 'Seq Scan' si no hay índice

sandbox_pool.close()
```

## Estructura interna

```
sandbox/
├── __init__.py     # exporta API pública del módulo
├── config.py       # SandboxConfig (dataclass)
├── pool.py         # create_sandbox_pool (sin read-only, con timeout)
├── setup.py        # setup_sandbox_schema, drop_sandbox_schema (B15)
├── explain.py      # explain_in_sandbox (B16)
├── validator.py    # validate_index_recommendation, verdict_from_plans (C3)
└── CLAUDE.md       # este archivo
```

## Cómo extender

### Agregar soporte para FOREIGN KEYs
Hoy `_create_table` ignora `table["foreign_keys"]`. Si un detector
futuro necesita FKs para razonar (ej. detección de "FK sin índice"),
agregarlos en un paso posterior a CREATE TABLE — todos los tables
deben existir antes de poder agregar FKs entre ellos.

### Agregar stats por columna
Hoy `_set_relation_stats` solo setea relpages/reltuples. Para
selectividades realistas (n_distinct, most_common_vals, correlation)
hay que extender con `pg_catalog.pg_restore_attribute_stats(...)`.
Disponible en PG18+ con la misma forma VARIADIC kwargs. Los datos
necesarios ya viven en `snapshot["stats"]`.

### Soportar tipos exóticos (postgis, vector, citext)
`_create_table` reproduce los tipos tal cual los reportó `format_type`.
Si el cliente usa extensiones, el sandbox debe tenerlas instaladas o
caer a `text` (o `bytea`) por columna. Sumar un paso de extension
detection antes del CREATE TABLE; degradar tipos desconocidos.

### Multi-schema en el snapshot
Hoy las tablas se aplanan en el schema temporal por nombre simple.
Si dos schemas del cliente tuvieran tablas con el mismo nombre habría
colisión. Para soportar multi-schema: usar dos schemas temporales
(`analysis_xxx_public`, `analysis_xxx_analytics`) o renombrar las
tablas en el sandbox y reescribir la query con `sqlglot`. Decisión
para cuando aparezca el primer cliente multi-schema.

### Cleanup de schemas zombies (E5)
Si un análisis crashea entre `setup_sandbox_schema` y
`drop_sandbox_schema`, queda un schema zombie. Para E5: agregar
`cleanup_zombies(pool, prefix="analysis_")` que dropea todos los
schemas que matchean el prefijo. Llamarlo al startup del backend.

### Timeouts endurecidos (E6)
Hoy aplicamos `statement_timeout`. E6 puede agregar timeouts
per-operación (CREATE INDEX en sandbox, EXPLAIN, DROP) con
`asyncio.wait_for` o threading para que ninguna pueda colgar el
thread principal del backend.

## Decisiones específicas del módulo

- **Sandbox = PG18, AppDB = PG16.** Backlog R6 nombra explícitamente
  `pg_set_relation_stats`/`pg_set_attribute_stats`; en PG18 se llaman
  `pg_restore_relation_stats`/`pg_restore_attribute_stats` y son la
  forma canónica de persistir stats sin pasar por VACUUM/ANALYZE.
  AppDB se queda en 16 porque la BD del cliente es eso lo que
  representamos; no la tocamos.
- **El planner sigue usando el tamaño físico para costos.** Aun con
  `pg_restore_relation_stats`, PG consulta `RelationGetNumberOfBlocks`
  y, para archivos vacíos, los costos colapsan a ~0. Los TIPOS de
  nodo (Seq Scan, Index Scan) sí responden a la presencia de índices,
  así que las decisiones cualitativas se preservan. Las comparaciones
  cuantitativas (cost reduction) se atenderán en C3 si las
  necesitamos: probable insertar filas sintéticas acotadas o razonar
  sobre cambio de tipo de nodo (Seq → Index) en lugar de magnitud.
- **`SandboxConfig` separado de `ConnectionConfig`.** Mismo shape pero
  intencionalmente distinto: confundir ambos pools (uno read-only,
  otro no) sería un bug de seguridad. Mantenerlos como tipos
  diferentes obliga a pensar.
- **Pool del sandbox no es read-only.** R7 aplica al pool del
  cliente, no al nuestro. Si alguien mete `SET TRANSACTION READ ONLY`
  por copy/paste accidental, los tests fallarían al primer CREATE
  SCHEMA (deliberado: que falle ruidoso).
- **`setup_sandbox_schema` es una sola transacción**, todas las DDL
  juntas. Si una falla, no queda schema parcial. PG soporta DDL
  transaccional, así que esto Just Works.
- **Nombres de schema con `analysis_` + UUID4 hex.** 41 chars,
  determinístico para tests cuando se pasa explícito, único cuando
  no. Prefijo `analysis_` facilita el cleanup_zombies futuro
  (E5).
- **FOREIGN KEYs no se replican.** El planner de SELECTs no las usa
  para nada relevante (no son índices). Replicarlas exigiría ordenar
  CREATE TABLE por dependencias y resolver ciclos: complejidad
  injustificada para este caso.
- **Tipos de columna van crudos desde `format_type`.** No hay
  traducción "VARCHAR(50)" → "text". Si AppDB declara un tipo, el
  sandbox lo intenta tal cual. Es la única forma de mantener
  fidelidad del plan (anchos, longitudes, etc.).
- **`SET LOCAL statement_timeout` per-call.** El pool ya tiene un
  default a 5s; el parámetro `timeout_seconds` de `explain_in_sandbox`
  override por transacción. `SET LOCAL` se descarta al cerrar la
  transacción — la conexión queda limpia para el próximo caller del
  pool.
- **Cleanup en `try/finally`** en `explain_in_sandbox`. Si el
  EXPLAIN falla por cualquier razón, el schema temporal igual se
  dropea. Si el drop también falla, la excepción del EXPLAIN gana
  como causa principal (es la información útil para el caller).

## Tests

Viven en `tests/sandbox/`:
- `conftest.py`: fixtures `sandbox_pool`, `appdb_pool` y
  `synthetic_snapshot` (3 tablas: `users`, `posts`, `tags`).
- `test_setup.py`: 8 tests de integración — creación de schema +
  tablas + índices, falseo de stats, skip de "unknown",
  independencia entre llamadas, drop idempotente, plan razonable.
- `test_explain.py`: 6 tests de integración — happy path con
  snapshot sintético, snapshot real de AppDB en <5s, cleanup en
  éxito y en error, timeout del pool con `SELECT pg_sleep`.

Todos marcados `@pytest.mark.integration`. Requieren ambos
contenedores levantados.

**Cómo correrlos:**
```bash
# Levantar AppDB + sandbox
docker compose up -d appdb sandbox

# Correr solo este módulo
pytest tests/sandbox

# Excluir integration (solo verifica imports y estructura)
pytest tests/sandbox -m "not integration"
```

Variables de entorno opcionales (defaults en `.env.example`):
`SANDBOX_HOST`, `SANDBOX_PORT`, `SANDBOX_DB`, `SANDBOX_USER`,
`SANDBOX_PASSWORD`.

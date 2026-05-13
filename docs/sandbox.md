# Módulo `sandbox` — guía del Postgres efímero de validación

> **Audiencia:** developers fuera del equipo de PgPilot que necesiten
> entender por qué el sandbox **no copia datos del cliente**, cómo
> falsea estadísticas, qué timeouts aplica, qué cleanup hace al
> terminar (y al fallar) — más cómo se valida una recomendación de
> índice antes de mostrársela al usuario.
>
> **Resumen en una línea:** el sandbox es un segundo contenedor
> Postgres que **monta schemas temporales con tablas vacías y stats
> falseadas** para que PgPilot pueda ejecutar `EXPLAIN` antes/después
> de aplicar una recomendación de índice — sin tocar la BD del
> cliente y sin copiar ni una sola fila.

---

## 1. ¿Qué hace este módulo?

`sandbox/` cumple **cuatro responsabilidades** y nada más:

1. **Montar schemas temporales** (`setup_sandbox_schema`): crea un
   schema con las tablas vacías del snapshot del cliente y los
   índices declarados, falseando los tamaños con
   `pg_restore_relation_stats`.
2. **Ejecutar EXPLAIN sin ANALYZE** sobre el schema temporal
   (`explain_in_sandbox`): orquesta setup → `EXPLAIN (FORMAT JSON)` →
   parse → drop, con cleanup garantizado en `finally`.
3. **Validar recomendaciones de índice** (`validate_index_recommendation`):
   corre EXPLAIN antes, aplica la recomendación, corre EXPLAIN después
   y emite un veredicto basado en el cambio de tipo de nodo
   (`Seq Scan` → `Index Scan`).
4. **Limpiar schemas zombies** al startup del backend
   (`cleanup_zombie_schemas`): dropea cualquier schema que haya
   sobrevivido a un crash entre setup y drop.

**Lo que NO hace este módulo:**

- No habla con la BD del cliente (eso vive en `/conector`).
- No parsea EXPLAIN ni decide sobre el plan (eso vive en `/motor`).
- No habla con el LLM (eso vive en `/ia`).
- No serializa al frontend (eso vive en `/backend`).

**Regla #1 del proyecto aplicada aquí:** el sandbox es la herramienta
que el **motor determinístico** usa para confirmar sus
recomendaciones antes de mostrarlas. Si el LLM propone una
recomendación, **también** pasa por aquí (vía `cross_validate` en
`/ia`). El sandbox nunca acepta sugerencias sin verificar; nunca
inventa veredictos.

---

## 2. Pipeline del sandbox

Dos modos de uso. El primero es genérico (EXPLAIN puro), el segundo
es la validación de recomendaciones (C3).

### 2.1. Modo "EXPLAIN puro"

```
                Snapshot del cliente
                (schema + sizes + stats)
                          │
                          ▼
              setup_sandbox_schema()             ← B15
                          │
                          ▼
        schema temporal `analysis_<uuid>` con:
          - tablas vacías (NO datos)
          - índices declarados
          - pg_class.relpages/reltuples falseados
                          │
                          ▼
              SET LOCAL search_path = ...
              SET LOCAL statement_timeout = 5000
              EXPLAIN (FORMAT JSON) <query>      ← B16
                          │
                          ▼
                 motor.parse_explain()
                          │
              ┌───────────┴───────────┐
              ▼ try/finally           ▼ try/finally
       ExplainResult           drop_sandbox_schema()
       (al caller)
```

### 2.2. Modo "validador de recomendación de índice" (C3)

```
                Snapshot + query + Recommendation
                          │
                          ▼
              setup_sandbox_schema()
                          │
                          ▼
              EXPLAIN (FORMAT JSON) <query>    → plan_before
                          │
                          ▼
              CREATE INDEX <name>_c3 ON ...    (en el schema temporal)
                          │
                          ▼
              SET LOCAL enable_seqscan = off
              EXPLAIN (FORMAT JSON) <query>    → plan_after
                          │
                          ▼
              verdict_from_plans(before, after, table)
                          │
              ┌───────────┴────────────┐
              ▼ try/finally            ▼ try/finally
       ValidationResult         drop_sandbox_schema()
       (al caller)
```

---

## 3. Por qué no se copian datos (R6)

**R6 del proyecto:** *"Sandbox no copia datos, solo schema y stats. Está
prohibido copiar filas de AppDB o de cualquier BD cliente al sandbox."*

Tres razones que sostienen la regla, en orden de importancia:

### 3.1. Privacidad / seguridad

Copiar filas significaría mover datos del cliente fuera de su
perímetro. Para clientes con compliance (PCI, HIPAA, GDPR) eso es
inaceptable, y para todos los demás es un riesgo innecesario. El
sandbox de PgPilot opera con metadata + stats, no con contenidos.

### 3.2. Costo y latencia

Replicar filas de una BD multi-GB es lento (segundos a minutos por
tabla) y caro (disco, red, RAM). PgPilot apunta a tiempos de
análisis de pocos segundos por query — incompatible con copia
masiva.

### 3.3. `EXPLAIN` sin `ANALYZE` no necesita filas

El planner de Postgres decide los planes basándose en estadísticas
(`pg_class.reltuples`, `pg_stats`), no en los datos reales. Mientras
las estadísticas estén bien falseadas, el planner produce los
mismos planes estimados sobre tablas vacías que sobre la BD del
cliente con millones de filas. Esto es lo que hace viable la
validación estructural sin copiar nada.

> **Excepción documentada:** el planner sí consulta el tamaño físico
> del archivo (`RelationGetNumberOfBlocks`) además de
> `pg_class.relpages`. Para tablas físicamente vacías ese override
> empuja los costos absolutos a ~0. Por eso el validador C3 mide
> **cambio de tipo de nodo** (Seq Scan → Index Scan), no magnitudes
> absolutas de costo. Ver §10.3.

---

## 4. Por qué Postgres 18 en el sandbox (AppDB sigue en 16)

El stack del proyecto declara Postgres 16 para AppDB. El contenedor
**sandbox** corre Postgres 18.

### 4.1. La razón

R6 pide explícitamente `pg_set_relation_stats` /
`pg_set_attribute_stats` para falsear stats sin pasar por
`VACUUM`/`ANALYZE`. En Postgres 16 esas funciones no existen — se
introdujeron en Postgres 18 con los nombres
`pg_restore_relation_stats` / `pg_restore_attribute_stats`, pensadas
para el flujo `pg_dump --statistics-only` / `pg_restore --statistics-only`.

Sin ellas, el camino habitual sería `UPDATE pg_class`, pero el
planner de PG16 ignora `pg_class.relpages` cuando difiere del
tamaño físico del archivo — para tablas vacías eso colapsa los
costos a 0 igualmente. PG18 con `pg_restore_relation_stats` es la
forma canónica y sostenible.

### 4.2. Por qué AppDB se queda en 16

AppDB representa la **BD del cliente**. El cliente no necesariamente
puede actualizarse a PG18; el producto tiene que funcionar contra
PG16 (y eventualmente PG12+). Por eso AppDB se mantiene en 16 — es
lo que probamos contra el target real.

### 4.3. ¿Y los detectores?

Los detectores del motor leen `node_type` y campos tipados de
`PlanNode` que no han cambiado de forma significativa entre PG16 y
PG18 para nodos de query. El sandbox produciendo planes equivalentes
es suficiente para validar la recomendación; la query del cliente se
sigue ejecutando en su PG16.

---

## 5. Cómo se falsean las estadísticas

Esta es la sección que responde a la segunda pregunta explícita del
backlog ("cómo se falsean stats").

### 5.1. Qué se falsea hoy

**Solo dos campos**, ambos en `pg_class`:

| Campo | Tipo | Valor falseado | De dónde sale |
|---|---|---|---|
| `relpages` | `int` | `max(1, estimated_rows // 100)` | Heurística de ~100 filas por página de 8 KB. |
| `reltuples` | `real` | `estimated_rows` (del snapshot) | `pg_class.reltuples` original de la BD del cliente, extraído por `/conector` en B3. |

La función usada es `pg_restore_relation_stats` con la sintaxis
VARIADIC kwargs de PG18:

```sql
SELECT pg_catalog.pg_restore_relation_stats(
    'schemaname'::text, 'analysis_xxxx'::text,
    'relname'::text, 'posts'::text,
    'relpages'::text, 5000::int,
    'reltuples'::text, 500000::real
);
```

Esto persiste los valores en `pg_class` con la validación interna
apropiada — equivalente a haber corrido `ANALYZE` con esos números
exactos.

### 5.2. Qué NO se falsea (todavía)

- **Estadísticas por columna** (`pg_stats`): `n_distinct`,
  `null_frac`, `most_common_vals`, `correlation`. Estas viven en
  `pg_statistic` y se manipulan con `pg_restore_attribute_stats`
  (también PG18+). Las datos relevantes ya están en
  `snapshot["stats"]`; el setup actual los ignora. Esto se atenderá
  cuando el validador C3 razone sobre selectividad real
  (`PROGRESS.md` 2026-05-10, "Limitaciones conocidas" del módulo).
- **Foreign keys.** No las replicamos — no afectan al planner de
  `SELECT`. Si alguna vez aparece un detector que las necesita
  (ej. "FK sin índice"), habrá que añadirlas en un paso posterior
  al `CREATE TABLE` (orden de dependencias resuelto manualmente).

### 5.3. La limitación del tamaño físico

Esto es importante para entender la semántica acotada de "validated"
del validador C3:

Aunque `pg_class.relpages` diga `5000`, Postgres también consulta
`RelationGetNumberOfBlocks` durante la planificación — que devuelve
el tamaño físico **real** del archivo en disco. Para una tabla recién
creada en el sandbox (físicamente vacía: 0 páginas), Postgres usa
ese 0 al calcular costos absolutos. Los costos colapsan a ~0 aunque
`pg_class.relpages` diga otra cosa.

**Qué SÍ funciona:** las decisiones cualitativas del planner
(elegir Seq Scan vs Index Scan, Hash Join vs Merge Join, etc.) sí
responden a la presencia de índices y a los datos en `pg_class`.

**Qué NO funciona:** comparar magnitudes absolutas de
`total_cost` entre planes en el sandbox vs. planes en producción.

Decisión registrada en `PROGRESS.md` 2026-05-10 (B15+B16). El
validador C3 (§10) usa cambio de tipo de nodo como discriminador
honesto en lugar de magnitudes de costo.

### 5.4. Categoría `"unknown"` se respeta

Si el snapshot reporta una tabla con `category="unknown"` (sin
`ANALYZE` previo en el cliente), `setup_sandbox_schema`
**no toca sus stats**. El planner del sandbox usa sus defaults
internos. Es más honesto que inventar un número.

---

## 6. API pública

Exportado desde `sandbox/__init__.py`:

### 6.1. Conexión

#### `SandboxConfig` (frozen dataclass)

| Campo | Tipo | Default | Descripción |
|---|---|---|---|
| `host` | `str` | — | Host del contenedor sandbox. |
| `port` | `int` | — | Puerto TCP (5435 en docker-compose). |
| `dbname` | `str` | — | Nombre de la BD del sandbox. |
| `user` | `str` | — | Usuario con permiso de DDL y `pg_restore_relation_stats`. |
| `password` | `str` | — | Password (en claro, no se persiste). |
| `statement_timeout_ms` | `int` | `5000` | Timeout aplicado por sesión (§7). |
| `min_pool_size` | `int` | `1` | Conexiones mínimas en el pool. |
| `max_pool_size` | `int` | `4` | Conexiones máximas en el pool. |

#### `create_sandbox_pool(config) -> ConnectionPool`

Devuelve un `psycopg_pool.ConnectionPool` ya abierto. **Importante:**
a diferencia del pool del `/conector`, este **NO** fuerza read-only
— el sandbox necesita DDL (`CREATE SCHEMA`, `CREATE TABLE`,
`CREATE INDEX`, `DROP SCHEMA`, `pg_restore_relation_stats`).

R7 del proyecto aplica al pool del cliente, no al sandbox. El
`SandboxConfig` es un **tipo distinto** a `ConnectionConfig`
deliberadamente: confundir los dos sería un bug de seguridad, los
tipos diferentes obligan al caller a pensar.

### 6.2. Setup y cleanup

#### `setup_sandbox_schema(pool, snapshot, *, schema_name=None, timeout_ms=5000) -> str`

Crea un schema temporal `analysis_<uuid_hex>` con:

- Una tabla por cada entrada de `snapshot["schema"]`, vacía, con sus
  columnas declaradas tal cual (tipos, nullabilidad).
- Cada índice de `table["indexes"]` recreado con su nombre original,
  método (`btree`/`gin`/`gist`), unicidad y orden de columnas.
- `pg_restore_relation_stats` para cada tabla con
  `category != "unknown"` en `snapshot["sizes"]`.

Todo dentro de **una sola transacción** — si una sentencia falla, el
schema no queda parcial. Timeout duro de 5 segundos.

Devuelve el nombre del schema creado para que el caller pueda apuntar
`search_path` a él y luego dropearlo.

#### `drop_sandbox_schema(pool, schema_name, *, timeout_ms=5000) -> None`

`DROP SCHEMA IF EXISTS <name> CASCADE`. Idempotente — un caller
puede llamarlo sin saber si el schema todavía existe. Timeout duro
de 5 segundos.

#### `cleanup_zombie_schemas(pool, *, prefix="analysis_") -> list[str]`

Dropea **todos** los schemas que matcheen el prefijo. Está pensado
para correrse al startup del backend: si un análisis crasheó entre
`setup_sandbox_schema` y `drop_sandbox_schema`, queda un schema
zombie. Esta función los limpia. Devuelve los nombres dropeados
para logging.

### 6.3. EXPLAIN

#### `explain_in_sandbox(pool, snapshot, query, *, timeout_seconds=5.0, schema_name=None) -> ExplainResult`

Orquesta el flujo completo:

1. `setup_sandbox_schema(pool, snapshot)`.
2. Abre una transacción nueva, setea `SET LOCAL statement_timeout`
   y `SET LOCAL search_path = analysis_xxx, public`.
3. Corre `EXPLAIN (FORMAT JSON) <query>` (sin `ANALYZE`).
4. Parsea con `motor.parse_explain`.
5. **Cleanup en `finally`:** dropea el schema incluso si el EXPLAIN
   explotó. Si el drop también falla, la excepción del EXPLAIN se
   preserva como causa principal.

Devuelve el `motor.ExplainResult` listo para los detectores. Si el
EXPLAIN excede `timeout_seconds`, Postgres aborta con
`psycopg.errors.QueryCanceled` (SQLSTATE `57014`) y el schema igual
se dropea.

**Por qué EXPLAIN sin ANALYZE:** las tablas están vacías; con
`ANALYZE` el plan refleja la realidad (todo escanea 0 filas) y
pierde valor. Sin `ANALYZE`, el planner usa
`pg_class.reltuples`/`relpages` (que falsificamos) y produce el
mismo plan estimado que produciría sobre la BD real.

### 6.4. Validador de recomendaciones — ver §10

`validate_index_recommendation`, `verdict_from_plans`,
`ValidationResult`.

---

## 7. Timeouts

Esta es la sección que responde a la tercera pregunta explícita del
backlog ("qué timeouts aplican").

### 7.1. Capa 1 — Timeout de sesión

`create_sandbox_pool` aplica a cada conexión:

```sql
SET SESSION statement_timeout = <statement_timeout_ms>;   -- default 5000
```

Cualquier statement que exceda 5 segundos es abortado por Postgres
con `psycopg.errors.QueryCanceled` (SQLSTATE `57014`). Esto protege
contra:

- Una query del usuario que toma demasiado tiempo en el sandbox.
- Una recomendación con `CREATE INDEX` que crea un índice gigante
  innecesariamente complejo.
- Un `DROP SCHEMA CASCADE` que se cuelga por contención.

### 7.2. Capa 2 — Timeout per-call

Las funciones de alto nivel también aplican `SET LOCAL
statement_timeout` dentro de su transacción, derivado del parámetro
`timeout_seconds` (o `timeout_ms`):

| Función | Parámetro | Default |
|---|---|---|
| `setup_sandbox_schema` | `timeout_ms=5000` | 5 s |
| `drop_sandbox_schema` | `timeout_ms=5000` | 5 s |
| `explain_in_sandbox` | `timeout_seconds=5.0` | 5 s |
| `validate_index_recommendation` | `timeout_seconds=5.0` | 5 s |

`SET LOCAL` se descarta al cerrar la transacción — la conexión queda
limpia para el próximo caller del pool sin necesidad de resetear
manualmente.

### 7.3. Qué pasa cuando hay timeout

Postgres aborta la transacción con `QueryCanceled` (SQLSTATE `57014`).
Para los flujos de `explain_in_sandbox` y `validate_index_recommendation`:

- El `try/finally` garantiza que el schema temporal se dropee aunque
  el EXPLAIN haya muerto por timeout.
- La excepción se propaga al caller (típicamente el orquestador del
  backend, que la atrapa por E8 y devuelve resultados parciales).

---

## 8. Cleanup

Esta es la sección que responde a la cuarta pregunta explícita del
backlog ("qué cleanup hace").

### 8.1. Cleanup feliz — `try/finally` en cada operación

Cada operación de alto nivel (`explain_in_sandbox`,
`validate_index_recommendation`) hace:

```python
schema_name = setup_sandbox_schema(pool, snapshot)
try:
    # ...EXPLAIN, CREATE INDEX, EXPLAIN, etc.
    return resultado
finally:
    drop_sandbox_schema(pool, schema_name)
```

Si la operación interna falla (timeout, syntax error, sandbox
caído), el schema temporal **igual se dropea**. Si el drop **también**
falla, la excepción de la operación interna se preserva como causa
principal (es la información útil para el caller).

### 8.2. Cleanup de emergencia — `cleanup_zombie_schemas` al startup

Si el proceso del backend crashea entre `setup` y `drop` (kill -9,
OOM, panic del kernel), el `finally` no corre. Resultado: un schema
zombie con prefijo `analysis_` queda en el sandbox.

`cleanup_zombie_schemas(pool, prefix="analysis_")` se llama al
startup del backend (E5) y dropea **todos** los schemas que matcheen.
Devuelve la lista de schemas dropeados para que el backend pueda
loguearlos.

Esto significa que, salvo race condition exótica (otro proceso
PgPilot corriendo en paralelo contra el mismo sandbox justo al
arrancar), el sandbox **nunca acumula** schemas zombies entre runs.

### 8.3. Por qué el prefijo `analysis_`

- **Discriminante:** un humano puede crear schemas con cualquier
  nombre en el sandbox para debugging; `cleanup_zombie_schemas` no
  los toca mientras no usen el prefijo reservado.
- **Identificación rápida:** `\dn` en `psql` muestra todos los
  schemas; los `analysis_*` se identifican a simple vista como
  efímeros de PgPilot.

### 8.4. Nombres de schema: `analysis_<uuid_hex>`

- **41 chars** (prefijo + 32 hex de UUID4). Bajo el límite de 63
  bytes que Postgres impone a identificadores.
- **Único** por construcción — dos análisis concurrentes no
  colisionan.
- **Determinístico para tests:** las funciones aceptan
  `schema_name=...` explícito como kwarg, útil cuando el test quiere
  un nombre legible y predecible.

---

## 9. EXPLAIN en sandbox — uso típico

```python
from pathlib import Path

from conector import (
    ConnectionConfig, create_pool,
    compute_fingerprint, get_snapshot,
)
from sandbox import (
    SandboxConfig, create_sandbox_pool,
    explain_in_sandbox,
)

# Pool al cliente (read-only)
client_pool = create_pool(ConnectionConfig(
    host="db.empresa.local", port=5432, dbname="appdb",
    user="readonly_pgpilot", password="...",
))
fp = compute_fingerprint("db.empresa.local", 5432, "appdb", ("public",))
snapshot = get_snapshot(client_pool, fingerprint=fp,
                       cache_dir=Path(".pgpilot_cache"))
client_pool.close()

# Pool al sandbox (con DDL)
sandbox_pool = create_sandbox_pool(SandboxConfig(
    host="localhost", port=5435, dbname="sandbox",
    user="sandbox_user", password="sandbox_pass",
))

try:
    result = explain_in_sandbox(
        sandbox_pool,
        snapshot,
        "SELECT * FROM posts WHERE author_id = 42",
    )
    print(result.root.node_type)   # 'Seq Scan' si no hay índice
finally:
    sandbox_pool.close()
```

El snapshot puede venir de:

- Una conexión viva (`extract_snapshot` o `get_snapshot`).
- Cache local (`load_snapshot`).
- Bundle JSON portable del cliente (`load_bundle`).

El sandbox no distingue — los tres producen el mismo `SchemaSnapshot`.

---

## 10. Validador de recomendaciones (C3)

### 10.1. `validate_index_recommendation(pool, snapshot, query, recommendation, *, timeout_seconds=5.0, schema_name=None) -> ValidationResult`

Recibe una `motor.Recommendation` y la prueba en el sandbox antes
de devolvérsela al frontend. Flujo:

1. Si `recommendation.kind == "analyze"`: retorna verdict
   `"skipped_no_sandbox_signal"` sin tocar el pool. Un `ANALYZE`
   sobre tablas vacías no informa.
2. Monta schema con `setup_sandbox_schema`.
3. `EXPLAIN (FORMAT JSON)` de la query → `plan_before`.
4. `CREATE INDEX <recommendation.index_name>_c3 ON <schema>.<tabla>
   USING <method> (<column>)` en el schema temporal. El sufijo `_c3`
   evita colisión si la recomendación apuntase a un nombre ya
   existente.
5. `SET LOCAL enable_seqscan = off`.
6. `EXPLAIN (FORMAT JSON)` de la query otra vez → `plan_after`.
7. Compara con `verdict_from_plans`; dropea el schema en `finally`.

### 10.2. El truco `enable_seqscan = off`

**Por qué se necesita:** sin este flag, el planner del sandbox
preferiría Seq Scan aun con el índice presente, porque las tablas
están físicamente vacías y `total_cost` colapsa a 0 para Seq Scan
sobre 0 páginas. La señal estructural se perdería.

**Con el flag**, le pedimos al planner: "si te prohibimos Seq Scan,
¿usarías el índice nuevo?". Tres outcomes posibles:

- El planner emite `Index Scan` (o `Bitmap Heap Scan` / `Index Only
  Scan`) → el índice es **estructuralmente aplicable al filtro** →
  veredicto `validated`.
- El planner emite `Seq Scan` con `Disabled: true` (cuando no hay
  alternativa viable) → el índice no aplica al filtro de la query
  → veredicto `discarded`.
- El nodo no cambia → veredicto `discarded` con razón "el planner
  sigue ignorando el índice".

### 10.3. Semántica acotada de "validated"

Dado el truco anterior, `"validated"` NO significa "el planner
elegirá este índice en producción". Significa:

> **El índice es estructuralmente aplicable al filtro de la query.**

Falta validar selectividad real para afirmar lo primero — eso
requiere filas sintéticas o stats por columna
(`pg_restore_attribute_stats`) y queda como trabajo futuro
(`PROGRESS.md` 2026-05-10).

Para el alcance del producto: la semántica actual **descarta los
CREATE INDEX absurdos** (columna mal, método mal, índice que no
toca el filtro) sin pretender más de lo que el sandbox vacío puede
afirmar honestamente.

### 10.4. `ValidationResult`

| Campo | Tipo | Descripción |
|---|---|---|
| `verdict` | `"validated" \| "discarded" \| "skipped_no_sandbox_signal"` | Veredicto principal. |
| `reason` | `str` | Prosa para el usuario y para logs. |
| `node_type_before` | `str \| None` | Tipo del nodo de scan sobre la tabla en `plan_before`. |
| `node_type_after` | `str \| None` | Tipo del nodo de scan sobre la tabla en `plan_after`. |
| `cost_before` | `float \| None` | `total_cost` del nodo de scan en `plan_before`. **No participa en el veredicto** (tablas vacías). |
| `cost_after` | `float \| None` | `total_cost` del nodo de scan en `plan_after`. **No participa en el veredicto.** |
| `plan_rows_before` | `int \| None` | `plan_rows` (filas estimadas) del nodo en `plan_before`. Alimenta E7 en el frontend. |
| `plan_rows_after` | `int \| None` | `plan_rows` del nodo en `plan_after`. Alimenta E7. |

**No hay campos de tiempo.** El EXPLAIN del sandbox corre sin
`ANALYZE` (tablas vacías por R6 — un `EXPLAIN ANALYZE` no daría
tiempos comparables a producción), así que no hay tiempo real que
reportar.

### 10.5. `verdict_from_plans(plan_before, plan_after, table_key) -> ValidationResult`

Función pura. Permite testear la lógica de veredicto **sin levantar
el sandbox real**. La usan los unit tests de C3 (sin marker
`integration`) y la usa internamente
`validate_index_recommendation` después de extraer los dos planes.

---

## 11. Garantías para el usuario

Tres garantías contractuales que el sandbox provee:

### 11.1. Privacidad (R6)

- **Cero filas del cliente.** El sandbox monta tablas vacías y solo
  falsea `relpages`/`reltuples` con valores enteros agregados (no
  identifican individuos ni revelan distribuciones).
- **Stats por columna no se transfieren todavía** (ver §5.2). Cuando
  se añadan (`pg_restore_attribute_stats`), los `most_common_vals`
  se filtrarán antes de ir al sandbox o se hashearán — política
  pendiente.
- **El sandbox vive en infraestructura de PgPilot**, no del cliente.
  La separación física es por contenedor (`docker-compose`).

### 11.2. Aislamiento (cleanup garantizado)

- Cada análisis monta su propio schema con nombre único.
- `try/finally` garantiza el drop incluso ante crash o timeout.
- `cleanup_zombie_schemas` al startup elimina cualquier residuo de
  crashes previos.
- Dos análisis concurrentes nunca colisionan (UUIDs únicos).

### 11.3. Determinismo / honestidad

- `setup_sandbox_schema` es **self-contained**: cada llamada monta y
  dropea su propio schema, no comparte estado entre llamadas.
- `verdict_from_plans` es **función pura**: dado el mismo input,
  produce el mismo output. Tests unitarios sin sandbox real.
- La semántica acotada de `"validated"` está documentada (§10.3); el
  validador **no pretende** más de lo que el sandbox vacío puede
  afirmar honestamente.

---

## 12. Configuración y ejecución

### 12.1. Variables de entorno

| Variable | Default | Efecto |
|---|---|---|
| `SANDBOX_HOST` | `localhost` | Host del contenedor sandbox. |
| `SANDBOX_PORT` | `5435` | Puerto TCP. |
| `SANDBOX_DB` | `sandbox` | Nombre de la BD. |
| `SANDBOX_USER` | `sandbox_user` | Usuario con permisos de DDL. |
| `SANDBOX_PASSWORD` | `sandbox_pass` | Password. |

Defaults documentados en `.env.example` de la raíz del repo.

### 12.2. Levantar el contenedor sandbox

```bash
# Desde la raíz del repo:
docker compose up -d sandbox

# Verificar que está vivo:
docker compose ps sandbox
```

`docker-compose.yml` declara el sandbox como `postgres:18` (ver §4)
con un volumen efímero (`pgpilot_sandbox_data`) — se borra y se
recrea sin pérdida (el sandbox no tiene data persistente que importe).

### 12.3. Tests

```bash
# Unit tests (no requieren docker): solo verdict_from_plans
pytest tests/sandbox -m "not integration"

# Todos (requieren docker compose up -d appdb sandbox)
pytest tests/sandbox
```

Cobertura:

| Archivo | Cobertura |
|---|---|
| `test_setup.py` | 8 tests — creación de schema + tablas + índices, falseo de stats, skip de `"unknown"`, independencia entre llamadas, drop idempotente, plan razonable. |
| `test_explain.py` | 6 tests — happy path con snapshot sintético, snapshot real de AppDB en <5s, cleanup en éxito y en error, timeout del pool con `SELECT pg_sleep`. |
| `test_validator.py` | Tests de C3 — happy paths, todos los outcomes de `verdict_from_plans` con planes sintéticos, integración con `setup_sandbox_schema`. |

Tests marcados con `@pytest.mark.integration` requieren ambos
contenedores (AppDB en 5434 y sandbox en 5435).

---

## 13. Limitaciones conocidas

Listadas honestamente, en orden de importancia:

- **Tamaño físico del archivo derrota a `pg_class.relpages` para
  costos absolutos.** Documentado en §5.3. Mitigación práctica: el
  validador C3 razona sobre cambio de tipo de nodo, no sobre
  magnitudes. Mitigación futura: insertar filas sintéticas acotadas
  o ampliar `setup_sandbox_schema` para usar
  `pg_restore_attribute_stats` (PG18+) con MCF/correlación.
- **Stats por columna no se transfieren.** El planner usa defaults
  internos para selectividad. Aceptable para discriminar
  estructuralmente; insuficiente para afirmar "este índice
  reducirá el tiempo de X a Y" cuantitativamente.
- **No se replican FOREIGN KEYs.** Aceptable hoy porque ningún
  detector las usa para razonar. Si aparece un detector "FK sin
  índice" o similar, hay que extender `_create_table`/`_create_indexes`
  para añadir las FKs en un paso posterior (orden de dependencias).
- **Multi-schema en el snapshot causa colisión por nombre de tabla.**
  Si dos schemas del cliente tienen `posts`, ambas se intentan crear
  en `analysis_xxx.posts` y la segunda falla. Para AppDB v1 (todo en
  `public`) no aplica. Solución cuando importe: usar dos schemas
  temporales (`analysis_xxx_public`, `analysis_xxx_analytics`) o
  reescribir la query con `sqlglot` para apuntar al schema
  renombrado.
- **Tipos exóticos requieren extensiones instaladas en el sandbox.**
  Si el cliente usa `postgis`, `vector` o `citext`, el `CREATE TABLE`
  en el sandbox falla con `type "geometry" does not exist`. Solución
  futura: detector de extensiones en el snapshot + `CREATE EXTENSION`
  en `setup_sandbox_schema`, o caer a `text` por columna desconocida.
- **El pool del sandbox NO es read-only** (R7 no aplica a este pool).
  Si un humano se conecta al contenedor sandbox con `psql` y hace
  estragos, el cleanup no protege contra eso — el sandbox es **infra
  nuestra**, no del cliente; el riesgo es operacional, no de
  privacidad.
- **`pg_restore_relation_stats` requiere superuser por default.** El
  `sandbox_user` del contenedor oficial lo es. Si en producción se
  endurece a un rol no-superuser, hay que conceder
  `EXECUTE ON FUNCTION pg_catalog.pg_restore_relation_stats` y
  `INSERT/UPDATE ON pg_class` explícitos — política pendiente.

---

## 14. Cómo extender

### 14.1. Soportar FOREIGN KEYs

Hoy `_create_table` ignora `table["foreign_keys"]`. Para añadirlas:

1. En `setup_sandbox_schema`, después de que **todas** las tablas
   estén creadas, recorrer los FKs del snapshot y emitir
   `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ...`.
2. Resolver el orden topológico de FKs es trivial si los FKs apuntan
   a tablas creadas; si hay ciclos (raro), usar `DEFERRABLE
   INITIALLY DEFERRED`.
3. Tests: añadir un fixture con FK y verificar que el planner usa
   inferencia FK (`Inner Join` con `inner_unique=true`).

### 14.2. Soportar stats por columna

Hoy `_set_relation_stats` solo setea `relpages`/`reltuples`. Para
selectividades realistas (`n_distinct`, `most_common_vals`,
`correlation`):

1. Extender `_set_relation_stats` con una segunda llamada a
   `pg_catalog.pg_restore_attribute_stats(...)` por columna con
   stats.
2. Los datos ya viven en `snapshot["stats"][table][col]` — el
   conector los expone (B4).
3. Considerar filtrado/hashing de `most_common_vals` antes de
   transferirlos al sandbox si contienen PII (política pendiente,
   ver §11.1).

### 14.3. Soportar tipos exóticos

Si un cliente usa extensiones (`postgis`, `vector`, `citext`):

1. Detectar las extensiones en el snapshot (extender el conector B2
   para extraer `pg_extension`).
2. En `setup_sandbox_schema`, emitir `CREATE EXTENSION IF NOT
   EXISTS ...` antes del primer `CREATE TABLE`.
3. Las extensiones tienen que estar **instaladas** en la imagen del
   contenedor sandbox; documentar en `docker-compose.yml`.

### 14.4. Soportar multi-schema sin colisión

Hoy las tablas se aplanan en el schema temporal por nombre simple.
Para soportar dos tablas con el mismo nombre en schemas distintos:

1. Crear `analysis_xxx_<schema_origen>` por cada schema del cliente.
2. Reescribir la query del usuario con `sqlglot` para que apunte al
   schema renombrado.
3. `search_path` debe listar todos los schemas temporales en orden.

---

## 15. Referencias

- **Código fuente:** [`sandbox/`](../sandbox/) en la raíz del repo.
- **Notas internas para mantenedores:**
  [`sandbox/CLAUDE.md`](../sandbox/CLAUDE.md).
- **Reglas del proyecto** (R6, R3, R9, R7):
  [`RULES.md`](../RULES.md) en la raíz del repo.
- **Documentación de módulos relacionados:**
  - [`docs/conector.md`](conector.md) — de dónde viene el
    `SchemaSnapshot` que `setup_sandbox_schema` consume.
  - [`docs/motor.md`](motor.md) — el parser de EXPLAIN que produce
    los `PlanNode` que `verdict_from_plans` compara.
  - [`docs/ia.md`](ia.md) — el cross-validador que opcionalmente
    pasa por aquí para descartar sugerencias del LLM.
- **Decisiones técnicas:** `PROGRESS.md` — entradas relevantes
  2026-05-10 (B15+B16, sandbox a PG18, pool separado, EXPLAIN sin
  ANALYZE), 2026-05-11 (C3 con `enable_seqscan=off`, semántica
  acotada de `validated`), 2026-05-12 (cleanup_zombie_schemas E5,
  timeouts endurecidos E6).

Si encuentras algo confuso o falta documentar un escenario, abrí un
issue en el repo de PgPilot.

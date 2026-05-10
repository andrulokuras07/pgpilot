# Fase 1 — Cimientos técnicos de PgPilot

> **Para qué sirve este documento.** Resume todo lo que construimos en
> Fase 1 (B1–B16) de forma que cualquiera del equipo, aunque no sea
> experto en Postgres o en el stack, pueda entender qué hacemos, por
> qué lo hacemos así, y defenderlo en el Demo Day.
>
> No reemplaza el código ni los `CLAUDE.md` por módulo. Es un mapa.

---

## 1. ¿Qué es PgPilot, en 3 frases?

1. **Producto B2B** para devs backend que tienen Postgres en
   producción y queries lentas que no saben cómo arreglar.
2. **Detecta anti-patterns** (queries mal escritas, índices faltantes),
   **recomienda índices** y **sugiere reescrituras**.
3. **Combina dos motores**: uno determinístico (lógica Python pura,
   100% predecible) y uno con IA (Claude API), pero la IA SIEMPRE está
   con guardrails — nunca tiene la última palabra.

**Universidad / contexto:** Proyecto final de SIS2404 (Bases de Datos
Avanzadas), Anáhuac Querétaro. Equipo de 5. Demo Day **2026-05-14**.

---

## 2. La regla #1 del proyecto (memorízala)

> **El motor determinístico DETECTA y DECIDE. El LLM EXPLICA y
> PROPONE. El motor VALIDA lo que el LLM propone. Si el LLM contradice
> al motor, gana el motor.**

¿Por qué es tan importante? Porque los LLMs alucinan. Si dejamos que
Claude decida "¿esto es un anti-pattern?" o "¿qué índice creamos?", a
veces va a inventar. Nuestro motor —escrito en Python puro, leyendo
estructuras de datos reales de Postgres— es 100% predecible. El LLM
solo agrega prosa pedagógica encima.

**Si te preguntan en el Demo Day "¿cómo evitan alucinaciones?"**, esta
es la respuesta corta: arquitectura. El LLM nunca tiene la palabra
final.

---

## 3. Mapa mental: cómo se conectan las piezas

```
┌────────────────────────────────────────────────────────────┐
│                    BD del cliente (AppDB)                  │
│            Postgres real con queries lentas                │
└──────────────────────────┬─────────────────────────────────┘
                           │  read-only, timeout 5s
                           ▼
┌──────────────────────────────────────────────────────────┐
│                       /conector                          │
│  Pool de conexiones psycopg + extractores de metadata    │
│  (schema, tamaños, stats por columna)                    │
└──────────────────────────┬───────────────────────────────┘
                           │  SchemaSnapshot
                           ▼
┌──────────────────────────────────────────────────────────┐
│                       /backend                           │
│           FastAPI — orquesta todo el flujo               │
│  (hoy es stub; Fase 2 conecta el motor real)             │
└──┬──────────────────┬──────────────────┬─────────────────┘
   │                  │                  │
   ▼                  ▼                  ▼
┌──────────┐   ┌────────────┐   ┌───────────────────────┐
│  /motor  │   │    /ia     │   │      /sandbox         │
│  parser  │   │ sanitiza + │   │ Postgres 18 efímero   │
│  + detec │   │ habla con  │   │ valida planes con     │
│  tores   │   │ Claude     │   │ EXPLAIN antes/después │
└──────────┘   └────────────┘   └───────────────────────┘
                           ▲
                           │  JSON con detecciones
                           ▼
┌──────────────────────────────────────────────────────────┐
│                       /frontend                          │
│  React + Monaco editor (tema oscuro tipo VS Code)        │
│  Editor de queries + panel lateral con detecciones       │
└──────────────────────────────────────────────────────────┘
```

**Flujo end-to-end (cuando esté completo en Fase 2):**

1. El usuario pega su query en el editor del frontend.
2. El frontend hace POST `/analyze` al backend.
3. El backend usa `/conector` para conectarse a su Postgres y traer la
   metadata.
4. Usa `/motor` para parsear el plan de la query.
5. Pasa el árbol del plan + la metadata a los detectores.
6. Si hay detección, `/ia` sanitiza la query y le pide a Claude una
   explicación pedagógica.
7. La sugerencia del LLM se valida en `/sandbox` con un EXPLAIN
   antes/después.
8. El backend devuelve un JSON al frontend con las detecciones,
   recomendaciones y explicaciones.

Hoy tenemos 1, 2, 3 y la mitad de 4. Fase 2 termina el flujo.

---

## 4. Lo que se cerró en Fase 1 — módulo por módulo

### 4.1 `/conector` — el "ojo" en la BD del cliente

**Misión:** todo lo que toca la BD del cliente vive aquí, y nada más
toca esa BD. Nunca escribe.

**Tickets cerrados:** B1, B2, B3, B4, B5, B6.

#### B1 — Conexión read-only forzada

`create_pool(config)` devuelve un pool de conexiones psycopg que
aplica a cada conexión:

- `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`
- `SET statement_timeout = 5000` (5 segundos)

**Por qué importa para defensa:** un INSERT/UPDATE/DELETE/DDL contra
la BD del cliente NO PUEDE pasar. Postgres lo rechaza con
`SQLSTATE 25006` (read_only_sql_transaction). Aunque mañana alguien
escriba código con un bug que intente borrar una tabla del cliente,
**Postgres mismo lo bloquea**. La protección es por construcción, no
por disciplina.

Lo aplicamos a nivel de SESIÓN (no de transacción): así no hay forma
de "olvidarlo" en código nuevo.

#### B2 — Extractor de schema

`get_schema(pool)` devuelve un dict con todas las tablas, sus
columnas (con tipo y nullabilidad), índices (con orden de columnas,
método btree/gin/gist, unicidad) y foreign keys.

**Detalle técnico para defender:** consultamos `pg_catalog`, no
`information_schema`. ¿Por qué? Porque pg_catalog preserva el orden
exacto de columnas en índices compuestos y maneja correctamente FKs
con varias columnas. `information_schema` es un estándar SQL que
Postgres implementa de forma fiel pero pierde detalles que sí están
en pg_catalog.

**Convención clave:** las claves del dict son `"<schema>.<tabla>"`
(no solo el nombre de la tabla). Esto evita colisiones cuando hay
tablas con el mismo nombre en schemas distintos.

#### B3 — Extractor de tamaños

`get_table_sizes(pool)` devuelve por cada tabla:

- `estimated_rows`: filas estimadas (de `pg_class.reltuples`).
- `total_bytes`: heap + índices + toast.
- `category`: `small` < 100k, `medium` 100k–1M, `large` ≥ 1M, o
  `unknown`.

**Cosa importante para defender:** cuando la categoría es `unknown`,
es porque la tabla nunca tuvo `ANALYZE`. NO la confundimos con
`small`. Una tabla sin estadísticas no es seguro afirmar que sea
chica — puede estar recién creada y tener millones de filas. El
motor trata `unknown` distinto.

#### B4 — Extractor de estadísticas por columna

`get_column_stats(pool)` devuelve para cada columna:

- `n_distinct`: número de valores distintos (convención Postgres:
  positivo = absoluto, negativo = ratio).
- `null_frac`: fracción de NULLs (0..1).
- `most_common_vals`: lista de los valores más frecuentes.
- `correlation`: correlación física vs lógica (-1..1). Crítica para
  saber si un Index Scan será secuencial o aleatorio en disco.
- `has_stats`: bandera. Si es `False`, la columna nunca tuvo ANALYZE
  y los demás campos son `None`.

**Por qué importa:** estos datos son los que el motor (próximamente)
va a usar para estimar selectividades y decidir si una recomendación
de índice tiene sentido.

#### B5 — Cache local

`get_snapshot(pool, fingerprint=...)` orquesta el cache:

- Si el cache existe y `force_refresh=False`, lee del disco
  (<100ms, verificado en tests).
- Si no, extrae fresco con `extract_snapshot` y persiste.

**Dos hashes distintos, no confundir:**

- `fingerprint`: md5 de `host:puerto:nombre_db:schemas`. Identifica
  la BD. Es el nombre del archivo del cache.
- `content_hash`: md5 del contenido del snapshot serializado.
  Detecta drift (cambios) entre dos extracciones de la misma BD. Va
  guardado *dentro* del JSON, no en el nombre.

**Decisión a defender:** el backlog original pedía
`cache/{content_hash}.json` pero eso es circular: para saber qué
archivo leer, hay que re-extraer y recalcular el hash, lo cual
defeats el cache. Separamos identidad (nombre) de contenido (hash
interno).

#### B6 — Modo offline (bundle)

`export_bundle(pool, path)` escribe un archivo JSON portable con
todo el snapshot. `load_bundle(path)` lo lee sin necesidad de
conexión.

**Defensa de venta crítica:** muchas empresas con datos sensibles
(banca, salud, gobierno) **no nos van a dar acceso a su BD
productiva**. Con el modo offline les decimos: "instala PgPilot un
ratito en tu entorno, corre `export_bundle()`, mándanos el archivo,
y nosotros analizamos sin abrir conexión a tu infra". Es la
diferencia entre que cierren venta o no.

`validate_bundle(path)` recalcula el `content_hash` y lo compara con
el guardado. Detecta tampering o corrupción en tránsito.

---

### 4.2 `/motor` — el "cerebro" determinístico

**Misión:** parsear el output de Postgres (EXPLAIN) en una estructura
que se pueda razonar con código puro. Aquí van a vivir los detectores
de anti-patterns en Fase 2.

**Tickets cerrados:** B7, B8, B9.

#### B7 + B8 — Parser de EXPLAIN

`parse_explain(raw)` convierte el JSON crudo de
`EXPLAIN (FORMAT JSON)` en un árbol de `PlanNode`s **tipados**.

¿Qué es "tipado" y por qué importa? En lugar de leer
`node["Index Name"]` (string, propenso a typos), los detectores leen
`node.index_name` (atributo nombrado). El editor te da autocomplete,
y refactorizar es seguro.

**Cobertura: 17 tipos de nodos** que Postgres puede emitir:

- Scans: `Seq Scan`, `Index Scan`, `Index Only Scan`,
  `Bitmap Heap Scan`, `Bitmap Index Scan`.
- Joins: `Nested Loop`, `Hash Join`, `Merge Join`.
- Otros: `Sort`, `Hash`, `Aggregate`, `Limit`, `Subquery Scan`,
  `CTE Scan`, `Materialize`, `Gather`, `Gather Merge`.

`ExplainResult` envuelve el árbol con metadata top-level
(`planning_time_ms`, `execution_time_ms`).

**Decisión a defender — `PlanNode` con campos planos vs dict:**
elegimos un atributo por campo posible en lugar de un `extras: dict`.
La explosión de campos `Optional` se contiene a un solo dataclass que
rara vez cambia, y los detectores ganan autocomplete + type checking.

**Decisión a defender — `frozen=True` y `tuple` para hijos:** los
detectores son funciones puras (R9). Inmutabilidad por construcción
evita bugs por mutación accidental.

#### B9 — `find_nodes`

`find_nodes(tree, node_type)` recorre el árbol en DFS pre-order y
devuelve todos los nodos cuyo `node_type` matchea. Acepta un string
o un iterable.

**Esta es LA primitiva sobre la que escribirán los detectores.**
Ejemplo:

```python
seq_scans = find_nodes(plan, "Seq Scan")
joins = find_nodes(plan, ["Hash Join", "Merge Join", "Nested Loop"])
```

**Por qué importa para R2 (regla inviolable):** un detector hace
`find_nodes(plan, "Seq Scan")` operando sobre la **estructura** del
árbol, NO `if "Seq Scan" in raw_explain_text` haciendo regex sobre el
texto crudo. Esto sobrevive al renombrado de tablas en AppDB v2 (el
bonus de detección genérica).

---

### 4.3 `/ia` — la capa de privacidad y prosa

**Misión:** sanitizar literales antes de cualquier llamada al LLM y
(próximamente) construir prompts y validar respuestas.

**Tickets cerrados:** B10, B11.

#### B10 — Sanitizador de literales SQL

`sanitize(sql)` recibe una query y devuelve `SanitizedQuery(sql,
literals)`. La query sanitizada tiene los literales reemplazados por
placeholders por tipo:

| Tipo de literal | Placeholder       | Ejemplo                        |
|-----------------|-------------------|--------------------------------|
| string          | `$LITERAL_1_<i>`  | `'juan@empresa.com'` → `$LITERAL_1_0` |
| número          | `$LITERAL_2_<i>`  | `42` → `$LITERAL_2_0`         |
| fecha ISO       | `$LITERAL_3_<i>`  | `'2024-01-15'` → `$LITERAL_3_0` |
| UUID            | `$LITERAL_4_<i>`  | `'a1b2c3...'` → `$LITERAL_4_0` |
| email           | `$LITERAL_5_<i>`  | `'foo@bar.com'` → `$LITERAL_5_0` |

`restore(sanitized)` reconstruye la query original. **Importante: el
restore NUNCA va al LLM.** Solo se usa localmente, por ejemplo para
mostrarle la query original al usuario en el panel.

**Defensa central de privacidad (R4):** ningún dato sensible (PII,
datos de negocio, credenciales) sale a Anthropic. Esta es la regla
absoluta. Aplica también a logs, traces y mensajes de debug —
absolutamente todo lo que pueda llegar al LLM o quedar persistido.

#### B11 — Test de privacidad

Test específico que mete datos sensibles **reales** en una query:

- Email mexicano: `juan.perez@empresa.com.mx`
- RFC mexicano: `GODE561231GR8`
- Número de tarjeta: `4532015112830366`

Sanitiza la query, escribe el output a un archivo temporal, y corre
`grep` para verificar que **ninguno** de esos strings aparezca en lo
que va a salir al LLM.

**Por qué es crítico para el Q&A del Demo Day:** si nos preguntan
"¿cómo prueban que no leakean datos?", apuntamos a este test. Es la
prueba defensiva concreta. No es teoría — es un grep ejecutado en CI
contra datos sensibles plantados.

---

### 4.4 `/frontend` — la interfaz visual

**Misión:** editor de queries y panel para mostrar las detecciones.

**Tickets cerrados:** B12.

#### B12 — Scaffold de Vite + React + Monaco

Stack:

- **Vite 6.x** como bundler/dev server (puerto 5173).
- **React 18.x** con hooks (R12: nada de class components).
- **Monaco editor** (el mismo que usa VS Code).
- **CSS plano** con tema oscuro hardcodeado tipo VS Code.

El editor arranca con una query de ejemplo realista (un JOIN con
fecha y agregación) para que en el demo no se vea vacío.

**Decisión a defender — Tailwind diferido:** el `CLAUDE.md` raíz
lista Tailwind en el stack, pero para B12 con CSS plano son ~60
líneas legibles. Agregar Tailwind ahora es overhead (postcss, vite
plugin, conflicts con estilos de Monaco) sin ganancia mientras el
UI sea editor + panel. Se va a introducir en C10/C11 cuando aparezca
lógica de componentes (tarjetas de detección, comparativos
before/after). R12 admite "Tailwind **o** CSS modules", así que
técnicamente cumple.

**Decisión a defender — scaffold a mano:** el backlog literalmente
decía "crear con `npm create vite@latest`". Lo escribimos a mano
porque (a) ese comando es interactivo y descarga deps en el
momento, (b) baja archivos no deseados (eslint default) que después
hay que limpiar, y (c) tener los 8 archivos explícitos en el commit
es más auditable. El resultado funcional es idéntico.

---

### 4.5 `/backend` — el orquestador (stub hoy, completo en Fase 2)

**Misión:** FastAPI que en Fase 2 va a orquestar todo el flujo —
recibe la query del frontend, sanitiza, conecta a AppDB, extrae el
plan, parsea, corre los detectores, valida en sandbox, llama al
LLM, y devuelve un JSON estructurado.

**Tickets cerrados:** B13, B14.

#### B13 — Endpoint /analyze (stub)

`POST /analyze` recibe `AnalyzeRequest(query: str, min_length=1)` y
devuelve `AnalyzeResponse(detections, recommendations)`. Por ahora
las dos listas son **vacías**.

**Decisión a defender — listas vacías como contrato definitivo:** la
tentación era devolver datos dummy tipo
`{"detections": [{"id": "x", "fake": true}]}` para que el frontend
tenga algo que mostrar. Lo evitamos porque el frontend acostumbraría
a esos dummies y obligaría después a borrar lógica de display
defensiva. El **shape (estructura)** del contrato ya es el real;
solo el contenido es vacío. Cuando C9 conecte el motor real, solo se
llenan los arrays — el frontend no cambia.

CORS está restringido a `http://localhost:5173` (puerto del Vite dev
server). Hay un `GET /health` extra para healthcheck.

#### B14 — Wiring frontend ↔ backend

El botón "Analizar" del frontend hace `fetch` al backend y muestra
en el panel lateral los estados:

- `cargando…` mientras espera.
- `error` si el fetch falla (con mensaje sugiriendo verificar que el
  backend esté arriba).
- `respuesta` con el JSON del backend cuando todo va bien.

---

### 4.6 `/sandbox` — el "laboratorio" para validar recomendaciones

**Misión:** segunda BD de Postgres (efímera, sin datos del cliente)
donde montamos schemas temporales con stats falseadas y corremos
EXPLAIN. Sirve para que en Fase 2 podamos validar que una
recomendación de índice efectivamente reduce el costo, antes de
mostrársela al usuario.

**Tickets cerrados:** B15, B16.

#### B15 — Sandbox Postgres efímero

`setup_sandbox_schema(pool, snapshot)` crea un schema temporal con
nombre único (`analysis_<uuid_hex>`) y dentro:

1. Recrea cada tabla del snapshot, **vacía**, con sus columnas y
   tipos exactos.
2. Recrea cada índice (preservando nombre, método, columnas,
   unicidad).
3. Falsea las estadísticas (`reltuples`, `relpages`) usando
   `pg_restore_relation_stats` — función nativa de Postgres 18+.

`drop_sandbox_schema(pool, schema_name)` borra todo con
`DROP SCHEMA … CASCADE`. Idempotente.

**Decisión a defender — Postgres 18 en sandbox, 16 en AppDB:** R6
del proyecto pide explícitamente `pg_set_relation_stats` para falsear
stats sin copiar datos. Esa función fue agregada en PG18 (en PG18 se
llama `pg_restore_relation_stats`). Sandbox es nuestra infraestructura
— podemos elegir su versión. AppDB se queda en 16 porque
representa la BD del cliente. Cambio mínimo en docker-compose.

**Decisión a defender — no replicamos FOREIGN KEYs:** los FKs no
afectan al planner cuando solo hacemos SELECTs y complican el orden
de creación. Los detectores que necesiten FKs los leen del snapshot,
no del sandbox.

**Defensa de R6 (no copiar datos):** las tablas se crean **vacías**
con `CREATE TABLE`. Las stats se setean con una función nativa de
Postgres diseñada exactamente para esto (su caso de uso original
es `pg_dump --statistics-only` / `pg_restore --statistics-only`).
Ningún byte de los datos del cliente toca el sandbox.

**Pool del sandbox es DISTINTO al de `/conector`:** el de
`/conector` es read-only (R7). El del sandbox necesita DDL (CREATE
TABLE, CREATE INDEX, DROP SCHEMA), así que es escribible. Para que
nadie los confunda, son tipos separados (`SandboxConfig` vs
`ConnectionConfig`). Un parámetro booleano se setea mal por
copy/paste; tipos distintos obligan a pensar.

#### B16 — `explain_in_sandbox`

`explain_in_sandbox(pool, snapshot, query, *, timeout_seconds=5.0)`
hace todo el flujo end-to-end de validación:

1. Llama a `setup_sandbox_schema` (paso 1).
2. Setea `search_path` al schema temporal y `statement_timeout` al
   valor pedido (5s default).
3. Corre `EXPLAIN (FORMAT JSON)` sin ANALYZE.
4. Parsea con `motor.parse_explain` y devuelve `ExplainResult`.
5. Dropea el schema **siempre** (incluso si el EXPLAIN explotó:
   cleanup en `try/finally`).

**Por qué EXPLAIN sin ANALYZE:** las tablas están vacías. ANALYZE
ejecutaría la query y reportaría 0 filas para todo, lo cual es
ruido. Sin ANALYZE el planner usa nuestras stats falseadas y
produce el mismo plan estimado que produciría sobre la BD real.

**Limitación conocida (sé honesto en el Demo Day si te preguntan):**
aun con `pg_restore_relation_stats`, el planner de Postgres también
consulta el tamaño físico del archivo en disco. Para tablas
físicamente vacías, los **costos absolutos** del plan colapsan a ~0.
Esto NO bloquea B15/B16 (lo que validamos es la **estructura** del
plan), pero sí va a importar en C3 (validación de recomendaciones
por costo). La solución probable es insertar filas sintéticas
acotadas o pivotear C3 a razonar sobre el cambio de tipo de nodo
(Seq Scan → Index Scan) en lugar de magnitudes absolutas. Está
documentado como deuda en `sandbox/CLAUDE.md` y en `PROGRESS.md`.

---

## 5. Las reglas inviolables que hay que poder citar

Estas son las reglas operativas del proyecto que están en `RULES.md`.
Las más importantes para defender:

| #   | Regla                                                                 | Para qué sirve                              |
|-----|-----------------------------------------------------------------------|---------------------------------------------|
| R1  | Motor decide, LLM explica                                             | Evita alucinaciones                         |
| R2  | Detección sobre estructura, no strings                                | Bonus de AppDB v2 (detección genérica)      |
| R3  | Toda salida del LLM se valida antes de mostrarla                      | Evita alucinaciones (parte 2)               |
| R4  | Nunca enviar literales al LLM                                         | Privacidad (regla absoluta)                 |
| R5  | El producto debe funcionar sin LLM                                    | Resiliencia y argumento de venta            |
| R6  | Sandbox no copia datos, solo schema y stats                           | Privacidad + criterio explícito de éxito    |
| R7  | Conexiones a la BD del cliente son read-only                          | Imposible romper la BD del cliente          |
| R14 | No hardcodear nombres de tablas o columnas                            | Bonus de AppDB v2                           |
| R15 | Documentación obligatoria al cerrar una actividad                     | Memoria viva del proyecto                   |

---

## 6. Cheat sheet para el Demo Day

### "¿Cómo evitan que el LLM aluciné?"
1. **Arquitectura:** el motor determinístico decide qué es
   anti-pattern. El LLM solo da prosa pedagógica encima de una
   detección que ya existe (R1).
2. **Validación múltiple:** cuando el LLM propone un índice o
   reescritura, verificamos que las columnas existen en el schema,
   que el índice no existe ya, que el SQL es parseable con sqlglot,
   y que el sandbox confirma reducción de costo. Si falla cualquiera,
   descartamos la sugerencia (R3).
3. **Modo apagado:** existe un toggle `LLM_ENABLED`. Si lo apagas, el
   producto sigue funcionando con explicaciones por plantilla (R5).

### "¿Cómo protegen los datos del cliente?"
1. **Read-only forzado en BD del cliente:** el pool de `/conector`
   aplica `SET TRANSACTION READ ONLY` por sesión. Cualquier
   INSERT/UPDATE/DELETE/DDL es rechazado por Postgres con SQLSTATE
   25006 (R7). Imposible romperle la BD aunque haya un bug.
2. **Sanitización de literales:** ningún email, número de tarjeta,
   UUID o string del cliente sale al LLM (R4). El sanitizador los
   reemplaza por placeholders. Tenemos un test (B11) que mete datos
   sensibles reales y verifica con `grep` que no aparezcan.
3. **Sandbox sin datos:** al validar recomendaciones, el sandbox
   monta tablas **vacías** con stats falseadas mediante
   `pg_restore_relation_stats`. Cero filas del cliente tocan el
   sandbox (R6).
4. **Modo offline:** si el cliente no nos quiere dar credenciales, le
   pasamos el `export_bundle` para que corra en su entorno y nos
   mande un archivo JSON (B6). PgPilot nunca abre conexión a su BD.

### "¿Cómo detectan los anti-patterns?"
1. Postgres ejecuta `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` y nos
   devuelve el plan en JSON.
2. `motor/parser.py` lo convierte en un **árbol tipado** de
   `PlanNode`s (B7+B8). Cada nodo expone sus campos relevantes.
3. Los detectores (próximos en Fase 2) usan `find_nodes` (B9) para
   localizar nodos sospechosos y los comparan contra la metadata
   del schema y las stats de columna que vienen del snapshot.
4. La detección es **estructural** (R2): un detector razona sobre
   "hay un Seq Scan sobre una tabla con >100k filas y existe una
   columna con stats que indica alta selectividad", no sobre el
   texto del SQL.

### "¿Y si el cliente tiene un Postgres distinto al de AppDB?"
- El extractor (B2/B3/B4) opera sobre `pg_catalog` parametrizado
  por schemas. No hardcodea ningún nombre.
- Los detectores (R14) tampoco hardcodean nombres de tabla/columna.
  Operan sobre los nombres que llegan en el snapshot.
- Funciona contra cualquier Postgres 12+ con queries que toquen las
  tablas que tenga.

### "¿Por qué Postgres 18 en sandbox y 16 en AppDB?"
- AppDB representa la BD del cliente. En producción suele ser
  PG13–16 — nos quedamos con 16 que es lo más común.
- Sandbox es **nuestra** infraestructura. Podemos elegir su versión
  libremente.
- PG18 trae `pg_restore_relation_stats`, función diseñada
  específicamente para falsear stats sin tener datos en la tabla.
  La alternativa en PG16 (UPDATE pg_class) es ignorada por el
  planner cuando el archivo en disco está vacío. Lo verificamos
  empíricamente con un script de debug.

### "¿Cuál es el modo offline?"
El cliente corre `export_bundle()` en su entorno (sobre su BD) y
genera un archivo JSON. Nos manda el archivo. Nosotros corremos
`load_bundle()` y obtenemos el mismo `SchemaSnapshot` que tendríamos
con conexión viva. Es la respuesta a "no quiero abrirles puertos a
mi prod".

---

## 7. Estado de tests al cierre de Fase 1

Suite total: **127 tests, 100% verde**. Distribución:

| Módulo     | Tests | Notas                                          |
|------------|-------|------------------------------------------------|
| conector   | 43    | Mayoría integration (necesitan AppDB up)       |
| motor      | 42    | Unit puro, fixtures JSON versionados           |
| ia         | 20    | Unit + privacidad (B11)                        |
| backend    | 8     | Endpoint + CORS                                |
| sandbox    | 14    | Integration (necesitan AppDB y sandbox up)     |
| **Total**  | **127** | —                                            |

```bash
# Levantar las dos BDs
docker compose up -d appdb sandbox

# Correr toda la suite
pytest

# Solo unit (sin Docker)
pytest -m "not integration"
```

---

## 8. Para profundizar

Cada módulo tiene su propio `CLAUDE.md` con detalles internos —
firmas de funciones, decisiones específicas, cómo extender. Son la
referencia técnica completa:

- `conector/CLAUDE.md`
- `motor/CLAUDE.md`
- `ia/CLAUDE.md`
- `frontend/CLAUDE.md`
- `backend/CLAUDE.md`
- `sandbox/CLAUDE.md`

Otros archivos clave:

- **`RULES.md`** — las 20 reglas inviolables (técnicas + de
  proceso). Léelas al menos una vez.
- **`PROGRESS.md`** — la bitácora del proyecto. Cada actividad
  cerrada tiene su entrada con archivos modificados, decisiones y
  trade-offs. Si te preguntan "¿por qué tomaron X decisión?", la
  respuesta está acá.
- **`docs/decisiones.md`** — decisiones de stack y trade-offs que
  cubren el Criterio 1.2 de la rúbrica.
- **`docs/patterns/`** — catálogo de anti-patterns implementados
  (uno por archivo, llenándose en Fase 2).
- **`PgPilot_Backlog.md`** — el backlog completo de actividades.

---

## 9. Glosario rápido

| Término                | Significado                                                           |
|------------------------|-----------------------------------------------------------------------|
| **AppDB**              | BD demo en desarrollo. v1 con 20 queries plantadas; v2 renombra tablas para evaluar detección genérica. |
| **anti-pattern**       | Query mal escrita o sin índice apropiado.                             |
| **EXPLAIN**            | Comando de Postgres que devuelve el plan de ejecución de una query.   |
| **EXPLAIN ANALYZE**    | EXPLAIN que además ejecuta la query y reporta tiempos reales.         |
| **planner**            | El optimizador de Postgres; elige el plan basándose en las stats.     |
| **plan**               | Árbol de operaciones que Postgres ejecutará para resolver la query.   |
| **Seq Scan**           | Lectura secuencial de toda la tabla. Sin filtros muy restrictivos suele indicar índice faltante. |
| **Index Scan**         | Lectura usando un índice. Eficiente para filtros selectivos.          |
| **selectividad**       | Fracción de filas que devuelve un filtro (de 0 a 1).                  |
| **`pg_class`**         | Tabla del sistema con metadata de cada tabla (tamaño, estimaciones).  |
| **`pg_stats`**         | Vista del sistema con estadísticas por columna.                       |
| **`reltuples`**        | Estimación de filas en `pg_class`.                                    |
| **`relpages`**         | Páginas en disco (1 página = 8KB) en `pg_class`.                      |
| **read-only**          | Modo de conexión donde Postgres rechaza escrituras.                   |
| **SchemaSnapshot**     | Dict consolidado: schema + tamaños + stats. Mismo formato lo persisten cache y bundle. |
| **fingerprint**        | Hash que identifica una BD (host:puerto:db:schemas).                  |
| **content hash**       | Hash del contenido del snapshot. Detecta drift.                       |
| **sandbox**            | Postgres secundario donde montamos schemas temporales para validar planes sin tocar la BD del cliente. |
| **sanitizador**        | Módulo que reemplaza literales por placeholders antes de enviar al LLM. |
| **PII**                | Personally Identifiable Information — emails, nombres, RFCs, etc.     |
| **GUARDRAILS**         | Validaciones automáticas alrededor de la salida del LLM para evitar alucinaciones. |

---

> **Última actualización:** 2026-05-10, al cierre de Fase 1.
> Próxima fase (Fase 2 — primer flujo end-to-end) arranca con C1
> (primer detector real: Seq Scan en tabla grande con índice
> disponible).

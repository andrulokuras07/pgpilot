# Arquitectura de PgPilot

> **Audiencia:** evaluadores de la rúbrica del curso (Criterio 1.2) y
> developers externos que quieran entender cómo se compone el producto
> antes de leer cualquier código. Este documento es la fuente única
> para los cuatro elementos que pide la rúbrica: **diagramas**,
> **decisiones técnicas con alternativas**, **trade-offs identificados**
> y **uso de IA en el desarrollo**.
>
> **Resumen en una línea:** PgPilot es una pipeline determinística
> auditada que combina extracción de metadata (read-only) + parser
> estructural de planes + 19 detectores de anti-patterns + validación
> en sandbox + capa de IA con guardrails + UI con explicación visual.

---

## 1. Visión general (TL;DR para evaluadores)

PgPilot recibe una query SQL (o un export de `pg_stat_statements`) y
devuelve detecciones, recomendaciones validadas y un comparativo
*before/after* del plan. La premisa que rige todo el diseño:

> **El motor determinístico decide. El LLM explica. Si el LLM
> contradice al motor, gana el motor.** (Regla R1 del proyecto.)

Esto se traduce en cinco principios de arquitectura:

1. **Estructura, no strings (R2).** Los detectores nunca operan sobre
   el SQL crudo: leen el árbol de `EXPLAIN` y la metadata del schema.
2. **Validación cruzada antes de mostrar (R3).** Toda salida del LLM
   pasa por Pydantic + cross-validator contra el schema + sandbox.
3. **Privacidad por construcción (R4 + R6 + R7).** El LLM nunca ve
   literales; el sandbox jamás copia filas; el conector fuerza
   read-only en la BD del cliente.
4. **Resiliencia sin LLM (R5).** El producto degrada elegantemente a
   plantillas locales cuando la API de Anthropic está apagada o falla.
5. **Funciones puras donde sea posible (R9).** Especialmente en
   `/motor`: detectores y recomendador son testables sin Docker.

---

## 2. Diagrama de componentes

### 2.1. Vista de módulos

```
                          ┌─────────────────────────┐
                          │       FRONTEND          │
                          │  React 18 + Vite 6      │
                          │  Monaco editor (SQL)    │
                          │  Tarjetas + before/after│
                          └────────────┬────────────┘
                                       │ HTTP /analyze, /workload
                                       ▼
                          ┌─────────────────────────┐
                          │       BACKEND           │
                          │  FastAPI + Pydantic     │
                          │  /backend/orchestrator  │
                          │  (E8: try/except por    │
                          │   etapa)                │
                          └─┬───────┬──────┬──────┬─┘
                            │       │      │      │
                snapshot ◄──┘       │      │      └──► /workload
                            │       │      │           (parser +
                ┌───────────▼───┐   │  ┌───▼─────────┐  scoring)
                │   CONECTOR    │   │  │     IA       │
                │ psycopg pool  │   │  │ sanitizer    │
                │ READ-ONLY     │   │  │ prompt       │
                │ stmt_timeout  │   │  │ Claude API   │
                │   = 5 s       │   │  │ Pydantic     │
                │ schema/stats/ │   │  │ cross-valid. │
                │ sizes/cache/  │   │  │ plantillas   │
                │ bundle JSON   │   │  └──────┬──────┘
                └───────┬───────┘   │         │
                        │           │         │
                        ▼           ▼         ▼
                  ┌──────────────────────────────────┐
                  │              MOTOR               │
                  │  parse_explain (B7/B8)           │
                  │  find_nodes (B9)                 │
                  │  19 detectores (C1, D2-D12,      │
                  │                 D16-D22)         │
                  │  recommender (con selectividad)  │
                  └──────────────────┬───────────────┘
                                     │ Detection +
                                     │ Recommendation
                                     ▼
                          ┌─────────────────────────┐
                          │        SANDBOX          │
                          │  Postgres 18 efímero    │
                          │  schemas analysis_<uuid>│
                          │  pg_restore_relation_   │
                          │    stats (PG18+)        │
                          │  EXPLAIN before/after   │
                          │  cleanup_zombies + 5 s  │
                          │  timeout                │
                          └─────────────────────────┘

      ───────────────────────────  Postgres  ─────────────────────────
      ┌─────────────────┐                         ┌─────────────────┐
      │     AppDB       │                         │    SANDBOX      │
      │  postgres:16    │                         │  postgres:18    │
      │  localhost:5434 │                         │  localhost:5435 │
      │  ~5M filas,     │                         │  schema-only,   │
      │  20 queries     │                         │  stats falseadas│
      │  problemáticas  │                         │                 │
      └─────────────────┘                         └─────────────────┘
```

Los siete recuadros con título en MAYÚSCULAS son los módulos que pide
la rúbrica (los 5 de producto + frontend + sandbox como pieza
arquitectónica diferenciada). Cada módulo expone una API pública
estrecha y **no se conoce con sus pares**: el único que conoce a todos
es `/backend`, que actúa de orquestador. Esto permite testear cada
módulo aislado y cambiar implementaciones internas sin afectar al
resto.

### 2.2. Mapa de responsabilidades

| Módulo | Qué hace | Qué NO hace |
|---|---|---|
| `/conector` | Pool psycopg read-only; extrae schema, sizes, stats; cache; modo offline por bundle JSON. | Parsear SQL, hablar con LLM, mutar BD. |
| `/motor` | Parser de `EXPLAIN JSON` → árbol tipado; helpers (`find_nodes`); 19 detectores; recomendador. | I/O, red, llamar al LLM. |
| `/ia` | Sanitizar literales (R4); construir prompt; llamar Claude; validar respuesta con Pydantic; cross-validation contra schema; plantillas locales. | Detectar anti-patterns, decidir índices. |
| `/workload` | Parsear `pg_stat_statements` (CSV/JSON); score por `total_exec_time`; top-N. | Conectarse a Postgres, exponer HTTP. |
| `/sandbox` | Crear schemas efímeros; falsear stats con `pg_restore_relation_stats`; `EXPLAIN` before/after; cleanup. | Almacenar datos persistentes, copiar filas. |
| `/backend` | Orquestar la pipeline; exponer `/analyze`, `/workload`, `/health`; CORS; lifespan del snapshot. | Lógica de detección. |
| `/frontend` | Editor Monaco; tarjetas de detección/recomendación; comparativo before/after; banner de degradación. | Lógica de análisis. |

---

## 3. Flujo de datos — Análisis individual (endpoint `/analyze`)

Pipeline de 7 etapas dentro del orquestador. Cada una está aislada en
su propio `try/except` (E8): si una falla, las siguientes siguen lo
que pueden y la respuesta lleva `partial=true` + `errors[]`.

```
 [1] Frontend                                                        Backend
     │ POST /analyze                                                  │
     │ {"query": "SELECT * FROM posts WHERE author_id = 12345"}       │
     ├───────────────────────────────────────────────────────────────►│
     │                                                                │
     │                                                  [2] Sanitize  │
     │                                          ia.sanitize(query)    │
     │                                          → SanitizedQuery      │
     │                                            (5 tipos: string,   │
     │                                             number, date,      │
     │                                             uuid, email)       │
     │                                                                │
     │                                                  [3] Extract   │
     │                                  conn.execute("EXPLAIN         │
     │                                    (ANALYZE, BUFFERS, JSON)    │
     │                                    <query original>")          │
     │                                  → JSON plan                   │
     │                                                                │
     │                                                  [4] Parse     │
     │                                  motor.parse_explain(plan)     │
     │                                  → ExplainResult(root, ...)    │
     │                                                                │
     │                                                  [5] Detect    │
     │                                  ┌── C1 — seq_scan_on_large    │
     │                                  ├── D2 — stale_statistics     │
     │                                  ├── D3 — sort_spill_to_disk   │
     │                                  ├── … (19 detectores en       │
     │                                  │    paralelo, cada uno con   │
     │                                  │    su propio try/except)    │
     │                                  └── D22 — count_star_full     │
     │                                  → list[Detection]             │
     │                                                                │
     │                                                  [6] Recommend │
     │                                  motor.recommend()             │
     │                                  • C1/D16/D17/D18 → kind=      │
     │                                    create_index | analyze |    │
     │                                    create_partial_index |      │
     │                                    create_statistics |         │
     │                                    skipped_low_selectivity     │
     │                                  • Otros 15 detectores →       │
     │                                    kind=finding (sin SQL)      │
     │                                                                │
     │                                              [7] Validate      │
     │                                  ┌───────────────────────────┐ │
     │                                  │ Por cada Recommendation:  │ │
     │                                  │ 1. setup_sandbox_schema   │ │
     │                                  │    (schemas analysis_<id>)│ │
     │                                  │ 2. EXPLAIN antes          │ │
     │                                  │ 3. CREATE INDEX en sandbox│ │
     │                                  │ 4. EXPLAIN después        │ │
     │                                  │ 5. verdict_from_plans     │ │
     │                                  │    → validated /          │ │
     │                                  │      discarded /          │ │
     │                                  │      skipped              │ │
     │                                  │ 6. DROP SCHEMA (cleanup)  │ │
     │                                  └───────────────────────────┘ │
     │                                                                │
     │                                                  [8] Explain   │
     │                                  ┌───────────────────────────┐ │
     │                                  │ Por cada Recommendation   │ │
     │                                  │ formal:                   │ │
     │                                  │ 1. build_explanation_     │ │
     │                                  │    prompt(SanitizedQuery) │ │
     │                                  │ 2. call_llm() → JSON      │ │
     │                                  │ 3. Pydantic validate      │ │
     │                                  │ 4. cross_validate         │ │
     │                                  │    contra snapshot        │ │
     │                                  │ 5. Si falla → plantilla   │ │
     │                                  │    determinística         │ │
     │                                  └───────────────────────────┘ │
     │                                                                │
     │ 200 OK                                                         │
     │ {"detections": [...], "recommendations": [...],                │
     │  "errors": [...], "partial": false}                            │
     │◄───────────────────────────────────────────────────────────────│
     │                                                                │
 [9] Render                                                           │
     • DetectionCard por cada detection                               │
     • RecommendationCard por cada recommendation                     │
     • PlanComparison con before/after + resumen ejecutivo            │
     • ValidationIndicators (4 píldoras: schema OK / no duplica       │
       índice / sintaxis válida / sandbox confirma mejora)            │
     • BannerParcial si partial=true                                  │
```

**Diferencias clave de este flujo vs. una "consulta directa a ChatGPT":**

- **Etapa 2 (sanitize)** garantiza R4: los literales nunca cruzan a
  Anthropic. El test `tests/ia/test_privacidad.py` lo prueba con
  `grep` externo contra emails, RFCs y tarjetas reales.
- **Etapas 5-6 (detect + recommend)** son código Python determinístico,
  testeado con fixtures de planes reales. El LLM **no participa** en
  decidir si hay un anti-pattern, ni qué índice crear.
- **Etapa 7 (validate)** mide en el sandbox si el planner usaría el
  índice; recomendaciones que el planner ignora se **descartan
  silenciosamente**. ChatGPT no puede hacer esto: su output es solo
  texto.
- **Etapa 8 (explain)** sólo agrega prosa pedagógica + un rewrite
  alternativo. Si Pydantic o el cross-validator detectan que la
  respuesta menciona columnas inexistentes, índices ya creados o SQL
  no parseable, la respuesta del LLM se **descarta** y se muestra la
  plantilla determinística.

---

## 4. Flujo de datos — Workload analysis (endpoint `/workload`)

Análisis batch sobre un export completo de `pg_stat_statements`. El
caso de uso es: "tengo Postgres en producción, exporto los top-100 por
tiempo total, quiero saber cuáles atacar primero".

```
 [1] Cliente exporta en producción                  Frontend
     COPY (SELECT query, calls,                       │
           total_exec_time, mean_exec_time, rows      │
           FROM pg_stat_statements                    │
           ORDER BY total_exec_time DESC              │
           LIMIT 100)                                 │
     TO '/tmp/stats.csv' WITH CSV HEADER;             │
                                                      │
                                                      │ POST /workload
                                                      │ (multipart/form-data
                                                      │  o text/plain)
                                                      ▼
                                                 Backend
                                                      │
                                  [2] Parse formato  │
                                  • Si empieza con [ │
                                    → JSON           │
                                  • Si no → CSV con  │
                                    DictReader       │
                                  • Compat PG <13:   │
                                    total_time /     │
                                    mean_time como   │
                                    fallback         │
                                  → list[Statement   │
                                       Entry]        │
                                                     │
                                  [3] Score          │
                                  sorted(entries,    │
                                    key=total_exec_  │
                                         time,       │
                                    reverse=True)    │
                                  [:top_n=10]        │
                                  score=time/max     │
                                  rank=1..N          │
                                  → list[Scored      │
                                       Entry]        │
                                                     │
                                  200 OK             │
                                  {"top": [          │
                                    {query, calls,   │
                                     total_exec_time,│
                                     mean_exec_time, │
                                     rows, score,    │
                                     rank}, ...]}    │
     ◄────────────────────────────────────────────────│
                                                     │
 [4] WorkloadTab del frontend                        │
     Tabla clickeable con 10 filas                   │
     Click en una fila → setQuery(row.query) +       │
     switchTab("analyze") → flujo /analyze normal    │
```

**Decisión clave: score por `total_exec_time`, no por `calls`.** Una
query que corre 10 veces y tarda 5 s cada una (50 s totales) duele más
que una que corre 10 000 veces y tarda 1 ms (10 s totales). El test
`test_frecuencia_no_domina_sobre_tiempo` lo verifica explícitamente.

---

## 5. Decisiones técnicas con alternativas consideradas

Las decisiones vivas viven en [`docs/decisiones.md`](./decisiones.md);
aquí se reproducen las **siete que más impactan la arquitectura** con
sus alternativas reales descartadas. La rúbrica pide "alternativas
consideradas", no solo el resultado.

### 5.1. Driver de Postgres — psycopg v3 vs asyncpg

- **Decisión:** `psycopg` v3 (no `psycopg2`, no `asyncpg`).
- **Alternativa descartada:** `asyncpg`. Es más rápido y tiene mejor
  API async, pero su control sobre `SET TRANSACTION READ ONLY` por
  conexión es menos limpio. Para nuestro caso (queries cortas de
  análisis, no streaming masivo), la diferencia de rendimiento es
  imperceptible y la legibilidad del read-only forzado pesa más.
- **Por qué importa:** R7 (read-only en la BD del cliente) es una
  garantía de venta. `psycopg.ConnectionPool` con `configure=` callback
  permite emitir `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`
  en cada nueva conexión, garantizado a nivel de Postgres. Un test
  intenta `INSERT` y verifica que Postgres devuelve `SQLSTATE 25006`.

### 5.2. Parser SQL — sqlglot vs pglast

- **Decisión:** `sqlglot`.
- **Alternativa descartada:** `pglast` — el parser oficial de Postgres
  empaquetado como librería Python. Es más fiel al dialecto exacto de
  Postgres, pero requiere compilación nativa (libpg_query) y su AST es
  más verboso. Para nuestros casos (sanitizar literales, parsear
  rewrites del LLM, normalizar para deduplicación) el AST limpio de
  sqlglot pesa más que la fidelidad teórica.
- **Por qué importa:** sqlglot es puro Python sin dependencias C — el
  `pip install` corre en macOS, Linux y Windows sin tocar compiladores.
  El test del cross-validator (`tests/ia/test_cross_validator.py`)
  verifica que las recomendaciones del LLM se descartan si sqlglot no
  las parsea.

### 5.3. Postgres del sandbox — versión 16 vs 18

- **Decisión:** **Postgres 18** en el sandbox, **Postgres 16** en AppDB.
- **Alternativa descartada:** mantener el sandbox también en 16. Más
  consistente con el target del cliente, pero `pg_restore_relation_stats`
  (la función con la que falseamos stats sin copiar datos) **existe
  solo desde PG18**. En PG16 habría que insertar filas sintéticas, lo
  que rompe R6 ("sandbox no copia datos").
- **Por qué importa:** los detectores leen `node_type` y campos
  tipados de `PlanNode` que no han cambiado de forma significativa
  entre 16 y 18 para nodos de query SELECT. El sandbox produce planes
  equivalentes; la query del cliente se sigue ejecutando contra su
  PG16. **Limitación honesta:** si el cliente usa una feature de PG12
  que cambió en 18 (raro en consultas), el plan del sandbox podría
  divergir. Documentado en [`docs/sandbox.md §4`](./sandbox.md).

### 5.4. Modo offline — bundle JSON vs pg_dump SQL

- **Decisión:** bundle JSON con el mismo formato del cache de B5.
- **Alternativa descartada:** parsear `pg_dump --schema-only` + un
  export CSV de `pg_stats`. Parsear pg_dump con sqlglot es frágil:
  emite SQL específico de Postgres (`ALTER OWNER`, `SET`, `COMMENT`,
  extensions) que sqlglot no parsea fielmente. Y `pg_stats.most_common_vals`
  es `anyarray`, parsearlo desde CSV requiere lógica por tipo.
- **Por qué importa:** el modo offline es un argumento de venta
  concreto en sectores con datos sensibles (fintech, healthtech). El
  cliente corre `export_bundle()` en su entorno, **nunca abre conexión
  hacia nuestra infra**, y nos comparte un archivo auditable línea por
  línea. Implementación: <100 líneas, testeable, portable.

### 5.5. Cache de metadata — `cache/{fingerprint}.json` vs `cache/{hash}.json`

- **Decisión:** nombre por `fingerprint` (identidad de la BD), no por
  `content_hash`.
- **Alternativa descartada:** lo que pedía el backlog literal —
  `cache/{md5_del_contenido}.json`. Eso obliga a re-extraer el snapshot
  cada vez para saber qué archivo leer (chicken-and-egg).
- **Por qué importa:** con `fingerprint = md5(host:port:db:schemas)`,
  el lookup es directo. El `content_hash` se guarda **dentro** del
  JSON, así que la detección de drift sigue disponible cuando alguien
  la necesite. Trade-off documentado: dos archivos con el mismo nombre
  no garantizan el mismo contenido; mitigado por tests de roundtrip.

### 5.6. Validación de respuestas del LLM — Pydantic vs JSON Schema manual

- **Decisión:** Pydantic v2 + cross-validator hecho a mano.
- **Alternativa descartada:** JSON Schema con `jsonschema` package. Es
  más portable entre lenguajes, pero el cross-validator (verificar que
  las columnas mencionadas existan en el snapshot, que el índice
  propuesto no exista ya, que el SQL parsee con sqlglot) necesita
  acceso al estado del schema en runtime — eso ya es Python, no JSON
  Schema declarativo.
- **Por qué importa:** Pydantic da type checking gratis, integración
  nativa con FastAPI (los modelos del request/response son los mismos),
  y mensajes de error legibles. Si la respuesta del LLM no parsea →
  reintento (1 vez) → si vuelve a fallar → plantilla determinística.
  Tests en `tests/ia/test_response_validator.py`.

### 5.7. Layout del monorepo — venv compartido vs por módulo

- **Decisión:** un solo `venv` y `requirements.txt` en la raíz.
- **Alternativa descartada:** un venv por módulo (`/conector/.venv`,
  `/motor/.venv`, etc.). Más aislado en teoría, pero el backend va a
  importar de todos los módulos así que comparten dependencias por
  diseño. Cinco venvs serían cinco copias de psycopg y sqlglot.
- **Por qué importa:** simplifica el setup
  (`pip install -r requirements.txt` y listo) y el deploy. Match con
  el patrón del `docker-compose.yml` donde el backend es un solo
  servicio. `pyproject.toml` declara `pythonpath = ["."]` para que
  pytest pueda importar `from conector import ...` sin instalar como
  paquete.

> Decisiones adicionales (puertos del compose, Tailwind diferido,
> scaffold del frontend a mano, `sandbox_plan_comparison` como objeto
> separado de `sandbox_reason`, honestidad sobre el "Xx mejora" en
> C11) están en [`docs/decisiones.md`](./decisiones.md) y en las
> entradas correspondientes de [`PROGRESS.md`](../PROGRESS.md).

---

## 6. Trade-offs identificados

Lo que **se sacrificó conscientemente** en cada decisión arquitectónica
importante. Listado en orden de impacto sobre el producto.

### 6.1. "Costos absolutos del sandbox son magnitudes de tablas vacías"

- **Trade-off:** R6 prohíbe copiar filas al sandbox. Aunque
  `pg_class.relpages` reporta lo falseado, Postgres también lee el
  tamaño físico del archivo en disco; para una tabla recién creada en
  el sandbox (0 bytes), los costos absolutos colapsan a magnitudes que
  no representan producción.
- **Mitigación implementada:** el validador C3 razona sobre **cambio
  de tipo de nodo** (Seq Scan → Index Scan), no sobre magnitudes
  absolutas. El componente `PlanComparison` del frontend etiqueta el
  "Xx mejora" como "**estimado en sandbox** (los costos son sobre
  tablas vacías por R6, la magnitud real depende de stats de
  producción)" — decisión registrada en PROGRESS 2026-05-10 ("Honestidad
  sobre el Xx mejora en C11").
- **Por qué se aceptó:** la alternativa era violar R6 y copiar datos,
  o pivotear a stats por columna con `pg_restore_attribute_stats`
  (PG18+) — trabajo grande para el alcance del proyecto.

### 6.2. "Falsos negativos por sufijo de schema en la resolución de tabla"

- **Trade-off:** los planes de Postgres traen `Relation Name = "posts"`
  sin schema. La función `_resolve_table_in_snapshot` del motor
  resuelve buscando un sufijo `.posts` en las claves del snapshot. Si
  dos schemas distintos tienen una tabla con el mismo nombre
  (`public.posts` y `analytics.posts`), la resolución es ambigua y se
  toma la primera coincidencia.
- **Mitigación implementada:** en AppDB v1 y v2 todas las tablas viven
  en `public`, así que el problema no se materializa hoy. Documentado
  en `motor/CLAUDE.md` y en `docs/motor.md §9`.
- **Por qué se aceptó:** Postgres no expone el schema en el campo
  `Relation Name` del JSON de EXPLAIN. La solución limpia (parsear el
  campo `Schema` cuando exista, o leerlo del `search_path`) queda como
  E-ticket post-Demo.

### 6.3. "AppDB v2 podría romper detectores que usen nombres específicos"

- **Trade-off:** la rúbrica incluye un bonus por sobrevivir a AppDB v2,
  donde el profesor renombrará tablas y columnas para verificar que la
  detección sea estructural (R2/R14). Cualquier literal `"posts"` o
  `"author_id"` en un detector quemaría el bonus.
- **Mitigación implementada:** los detectores leen todos los nombres
  del snapshot/plan. El test `test_no_false_positives.py` corre el
  motor sobre 10 queries sanas y verifica que no se inventan
  detecciones. Aún así, AppDB v2 no se ha probado (sigue marcada como
  "sin probar" en `PROGRESS.md`).
- **Por qué se aceptó:** no hay forma de testear AppDB v2 hasta que el
  profesor publique las queries renombradas; el plan B es leer el
  schema en vivo del v2 y confiar en que la cobertura estructural se
  mantenga.

### 6.4. "No hay protección de rama main"

- **Trade-off:** la regla R17 establece "PRs con review entre
  miembros", pero `Required approvals = 0` en GitHub. Si alguien hace
  push directo a `main` por accidente, no hay red de seguridad técnica.
- **Mitigación implementada:** comunicación en el grupo de WhatsApp,
  recordatorio en standups, R15 atada al `git push` (no al merge del
  PR) para que la documentación llegue igual.
- **Por qué se aceptó:** quedan 9 días al Demo Day. Bloquear merges
  esperando approval de un compañero introducía latencia que el
  equipo no se podía permitir. Decisión registrada en PROGRESS
  2026-05-08.

### 6.5. "Snapshot del schema se extrae una sola vez al startup"

- **Trade-off:** si el cliente cambia su schema (CREATE INDEX, ALTER
  TABLE) después de levantar el backend, las recomendaciones se
  vuelven inconsistentes con la BD real.
- **Mitigación implementada:** documentado en `backend/CLAUDE.md`; un
  endpoint `/refresh-snapshot` queda como E-ticket post-Demo. Para
  Demo Day, basta con reiniciar el backend si se cambia el schema.
- **Por qué se aceptó:** extraer schema + sizes + stats cuesta
  cientos de ms; hacerlo en cada `/analyze` mata el demo.

### 6.6. "Tailwind diferido en el frontend"

- **Trade-off:** el `CLAUDE.md` raíz lista Tailwind en el stack. B12
  arrancó con CSS plano (tema VS Code hardcoded). Cuando llegue un
  componente que justifique Tailwind (probablemente C10 o tarjetas
  más densas), habrá un commit de migración.
- **Por qué se aceptó:** los 60 LOC de CSS plano de B12 son legibles
  y no chocan con los estilos de Monaco. R12 admite "Tailwind **o**
  CSS modules"; técnicamente cumple. Documentado en PROGRESS 2026-05-09.

---

## 7. Limitaciones reconocidas

Honestidad explícita. La rúbrica valora declarar limitaciones por
encima de pretender un producto perfecto.

| # | Limitación | Dónde se documenta más a fondo |
|---|---|---|
| 1 | Costos absolutos del sandbox son sobre tablas vacías (por R6); la señal honesta es el cambio cualitativo de tipo de nodo. | [`docs/sandbox.md §5.3`](./sandbox.md), [`docs/sandbox.md §13`](./sandbox.md). |
| 2 | Stats por columna (`n_distinct`, `null_frac`, `most_common_vals`) no se transfieren al sandbox todavía — el planner usa defaults internos para selectividad. | [`docs/sandbox.md §5.2`](./sandbox.md). |
| 3 | Foreign keys no se replican en el sandbox (ningún detector las usa hoy; si aparece un detector "FK sin índice", habría que añadirlas). | [`docs/sandbox.md §5.2`](./sandbox.md). |
| 4 | Resolución de tabla por sufijo en el motor: dos schemas con la misma tabla causarían ambigüedad. | [`docs/motor.md §9`](./motor.md). |
| 5 | `parse_explain` ignora silenciosamente campos nuevos de EXPLAIN si Postgres agrega versiones futuras (pinneado a 16/18). | `motor/CLAUDE.md`. |
| 6 | El sanitizador (`/ia`) es regex, no parser. PII no-literal (en comentarios SQL, por ejemplo) no se cubre. | [`docs/ia.md §12`](./ia.md). |
| 7 | `cross_validate` valida forma + existencia de columnas, no semántica. Un LLM que sugiera un índice sintácticamente válido pero inútil pasa el cross-validate y depende del sandbox para descartarlo. | [`docs/ia.md §12`](./ia.md). |
| 8 | `max_retries=1` en el cliente LLM. Una falla transitoria de la API en una segunda llamada hace caer a plantilla. | [`docs/ia.md §12`](./ia.md). |
| 9 | Logs JSONL de C8 sin rotación. Un dev que corra el producto por semanas acumula archivo sin compactar. | [`docs/ia.md §12`](./ia.md). |
| 10 | Snapshot cacheado al startup; drift de schema en runtime requiere reiniciar el backend. | `backend/CLAUDE.md`. |
| 11 | Sin autenticación: `/analyze` y `/workload` están abiertos al `localhost:5173`. Producción exigiría auth + rate-limit. | `backend/CLAUDE.md`. |
| 12 | AppDB v2 sin probar; el bonus de detección estructural no se ha validado contra el rename del profesor. | `PROGRESS.md` (Estado actual). |

---

## 8. Uso de IA en el desarrollo

> **Declaración explícita conforme al Criterio 1.2 de la rúbrica.** La
> rúbrica penaliza con **-5 puntos** no declarar el uso de IA. Esta
> sección lo declara con detalle suficiente para que un evaluador
> entienda exactamente dónde y cómo se usó.

### 8.1. Modelos utilizados

| Contexto | Modelo | Para qué |
|---|---|---|
| Desarrollo del producto | **Claude Sonnet 4.5 / 4.6** vía **Claude Code** | Generación de código, refactor, redacción de documentación, sugerencia de casos de test. |
| Runtime del producto | **Claude Sonnet 4.6** vía **Anthropic Messages API** | Capa `/ia`: explicación pedagógica de detecciones del motor, sugerencia de rewrites. Modelo configurable vía `DEFAULT_MODEL` en `ia/llm.py`. |

### 8.2. Dónde **sí** se usó IA — durante el desarrollo

- **Generación inicial de código de módulos con contrato claro.** El
  parser de `EXPLAIN`, el sanitizador de literales, las plantillas
  locales del modo "LLM apagado", las funciones de scoring del
  workload analyzer. Cada commit fue revisado, testeado y aprobado
  por una persona del equipo antes de mergear.
- **Refactor y documentación de módulos existentes.** Los `CLAUDE.md`
  internos de cada módulo y los docs externos (`docs/conector.md`,
  `docs/motor.md`, `docs/ia.md`, `docs/sandbox.md`, este mismo
  `docs/arquitectura.md`) se redactaron con asistencia de Claude a
  partir del código real, verificando que cada firma, cada constante
  y cada test referenciado coincidieran con `main`.
- **Tests automatizados.** Muchos casos de prueba — especialmente los
  que cubren ramas de error y casos límite (timeout en `pg_sleep`,
  CRLF en `ANTHROPIC_API_KEY`, JSON malformado del LLM, fence de
  markdown alrededor del JSON) — fueron sugeridos por la IA y
  refinados a mano.
- **Bitácora del proyecto** (`PROGRESS.md`). Las entradas se redactan
  con asistencia de IA a partir del diff real de cada PR.
- **Investigación competitiva** (`business/competencia.md`,
  `business/diferenciador.md`). Estructura y borradores asistidos;
  hechos verificados manualmente contra las páginas de pganalyze,
  EverSQL, DBtune y pgMustard.

### 8.3. Dónde **NO** se usó IA — dentro del producto final

Estas restricciones son las reglas R1 a R7 del proyecto y se aplican
en runtime, no solo en desarrollo:

- **El motor determinístico es código humano** revisado línea por
  línea. Los 19 detectores (`motor/detectors/*.py`) **no usan IA en
  runtime**. Cada uno es una función pura Python con tests deterministas
  contra fixtures versionados de planes reales.
- **El recomendador de índices** decide qué SQL emitir leyendo el
  snapshot y la evidencia del detector — sin consultar al LLM.
- **La validación cruzada** (`ia/cross_validator.py`) verifica que las
  recomendaciones del LLM sean consistentes con el schema real **antes
  de mostrarlas**. Si el LLM contradice al motor, gana el motor.
- **El sandbox** es la última red de seguridad: si el planner no usa
  el índice propuesto, la recomendación se descarta independientemente
  de lo que el LLM haya dicho.
- **Plantillas locales** (`ia/templates.py`) garantizan que el
  producto siga funcionando con `LLM_ENABLED=false` o sin
  `ANTHROPIC_API_KEY`. Demostrable apagando el LLM en vivo durante el
  Demo Day.

### 8.4. Trazabilidad

- Los archivos generados con asistencia significativa de Claude llevan
  el comentario `# HECHO CON CLAUDE` en su cabecera (ver `.gitignore`,
  `docker-compose.yml`, etc.). Permite a un revisor identificar de un
  vistazo qué partes del repo fueron asistidas por IA.
- Los modelos en runtime y sus parámetros están en `ia/llm.py`
  (`DEFAULT_MODEL`, `DEFAULT_MAX_TOKENS`, `DEFAULT_TIMEOUT_SECONDS`)
  y son configurables vía env vars.
- Las **decisiones de arquitectura** (este documento + `docs/decisiones.md`)
  fueron tomadas por el equipo de 5 personas. La IA sirvió como par
  programador que sugiere alternativas; cada decisión final fue de un
  miembro del equipo, registrada con autor en `PROGRESS.md`.

### 8.5. Cómo el producto puede defender su uso de IA en el Demo Day

Tres preguntas del Q&A son anticipables y tienen respuesta directa
en este documento:

| Pregunta probable | Respuesta corta |
|---|---|
| *"¿Y si el LLM aluciña?"* | Tres capas en serie: motor decide (R1) · Pydantic + cross-validator (R3) · sandbox confirma con EXPLAIN (R3). Si cualquiera falla, gana el motor. |
| *"¿Por qué no usan ChatGPT directo?"* | Pegar la query a ChatGPT viola compliance en datos sensibles. PgPilot sanitiza literales antes (R4), el modo offline elimina la conexión, y la sugerencia se valida antes de mostrarla — no es solo texto plausible. |
| *"¿Funcionaría sin Claude?"* | Sí. `LLM_ENABLED=false` activa plantillas locales (R5). El producto pierde la prosa pedagógica del LLM, pero las detecciones, recomendaciones, validaciones y comparativos before/after siguen iguales. Demo en vivo del toggle. |

---

## 9. Referencias internas

- [`README.md`](../README.md) — guía de instalación y primer análisis.
- [`CLAUDE.md`](../CLAUDE.md) — arquitectura general y regla #1.
- [`RULES.md`](../RULES.md) — las 15 reglas que rigen el código.
- [`PROGRESS.md`](../PROGRESS.md) — bitácora cronológica con todas las
  decisiones registradas por fecha y autor.
- [`docs/decisiones.md`](./decisiones.md) — bitácora de decisiones de
  stack y arquitectura con sus alternativas.
- [`docs/conector.md`](./conector.md) — guía externa del módulo de
  conexión.
- [`docs/motor.md`](./motor.md) — catálogo de los 19 detectores, cómo
  agregar un detector nuevo.
- [`docs/ia.md`](./ia.md) — qué se sanitiza, cómo se valida, cómo
  funcionan las plantillas locales.
- [`docs/sandbox.md`](./sandbox.md) — por qué no se copian datos, cómo
  se falsean stats, cleanup automático.
- [`docs/patterns/`](./patterns/) — catálogo de anti-patterns, uno por
  archivo.
- [`PgPilot_Backlog.md`](../PgPilot_Backlog.md) — las 80 actividades
  del proyecto.

---

> **Nota de mantenimiento (R15 espiritual):** este documento es el
> mapa que un evaluador externo lee primero. Si la arquitectura cambia
> de forma sustantiva (nuevo módulo, nuevo flujo, nueva regla, retiro
> de una limitación), este archivo debe actualizarse en el mismo PR.
> Las decisiones nuevas van primero a `docs/decisiones.md` y a
> `PROGRESS.md`; este documento las consolida.
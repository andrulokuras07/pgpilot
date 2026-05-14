# Fase 4 — Workload completo y sandbox endurecido

> **Para qué sirve este documento.** Resume todo lo que construimos en
> Fase 4 (E1–E13) de forma que cualquiera del equipo, aunque no sea
> experto en Postgres o en el stack, pueda entender qué hacemos, por
> qué lo hacemos así, y defenderlo en el Demo Day.
>
> No reemplaza el código ni los `CLAUDE.md` por módulo. Es un mapa.

---

## 1. ¿Qué es PgPilot, en 3 frases? (recordatorio)

1. **Producto B2B** para devs backend que tienen Postgres en producción
   y queries lentas que no saben cómo arreglar.
2. **Detecta anti-patterns** (queries mal escritas, índices faltantes),
   **recomienda índices** y **sugiere reescrituras**.
3. **Combina dos motores**: uno determinístico (lógica Python pura,
   100% predecible) y uno con IA (Claude API), pero la IA SIEMPRE está
   con guardrails — nunca tiene la última palabra.

**Universidad / contexto:** Proyecto final de SIS2404 (Bases de Datos
Avanzadas), Anáhuac Querétaro.

---

## 2. ¿Qué cambia entre Fase 3 y Fase 4?

En una frase: **Fase 3 prendió todas las luces del cuarto. Fase 4
instaló el cuadro eléctrico completo y le puso breakers.**

La regla #1 sigue dictando todo:

> **El motor determinístico DETECTA y DECIDE. El LLM EXPLICA y
> PROPONE. El motor VALIDA lo que el LLM propone. Si el LLM contradice
> al motor, gana el motor.**

Al cerrar Fase 3 el sistema analizaba queries individuales con 18
detectores y una cobertura de 18/20 sobre el workload plantado. Fase 4
agrega dos ejes que no existían:

- **Workload real** (`pg_stat_statements`): el usuario ya no analiza
  queries manualmente una a una. Sube el export de la vista de
  Postgres, el sistema ranquea automáticamente las queries que más
  duelen y el usuario hace click para analizar la que quiera.
- **Sandbox de producción**: el sandbox que validaba CREATE INDEX ya
  existía desde Fase 2, pero podía dejar schemas zombie si crashaba y
  podía colgarse indefinidamente. Fase 4 le pone cleanup automático al
  startup y timeouts duros en cada operación.

Además, Fase 4 añade polimento defensivo al sistema:

- **E7** — comparativo before/after enriquecido: tipo de nodo, filas
  estimadas, resumen ejecutivo automático.
- **E8** — aislamiento de errores: si el LLM cae o el sandbox falla,
  el endpoint sigue devolviendo detecciones y recomendaciones
  determinísticas, nunca crasha.
- **E9** — indicadores de validación visibles: cada tarjeta de
  recomendación muestra los 4 checks anti-alucinación con íconos.
- **E10–E13** — documentación técnica de módulos: conector, motor, IA
  y sandbox documentados en `/docs/` para el entregable final.

---

## 3. Mapa mental: cómo se conectan las piezas (versión Fase 4)

```
┌──────────────────────────────────────────────────────────────┐
│                   BD del cliente (AppDB)                     │
│            Postgres real con queries lentas                  │
└─────────────────────────┬────────────────────────────────────┘
                          │  read-only, timeout 5s
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                       /conector                             │
│  Pool psycopg + extractores de metadata (snapshot)         │
│  + modo offline (bundle JSON)                              │
└─────────────────────────┬───────────────────────────────────┘
                          │  SchemaSnapshot
                          ▼
┌─────────────────────────────────────────────────────────────┐
│             /backend  (FastAPI — orquestador)               │
│   POST /analyze   → flujo individual (Fases 2–3)           │
│   POST /workload  → E3: recibe pg_stat_statements          │
│                      devuelve top 10 por total_exec_time   │
│                      con score normalizado 0..1            │
│                                                            │
│   Startup: cleanup_zombie_schemas(sandbox_pool) — E5       │
└──┬──────────────────┬──────────────────┬────────────────────┘
   │                  │                  │
   ▼                  ▼                  ▼
┌──────────┐   ┌────────────┐   ┌───────────────────────────┐
│  /motor  │   │    /ia     │   │         /sandbox          │
│ 18 detect│   │ prompt +   │   │ schema temporal único     │
│ recomend │   │ LLM call + │   │ (analysis_{uuid})         │
│ dador    │   │ guardrails │   │ CREATE INDEX + EXPLAIN    │
│          │   │ + xvalidat │   │ cleanup CASCADE al final  │
└──────────┘   └────────────┘   │ timeout 5s por operación  │
                                └───────────────────────────┘
                          ▲
                          │  JSON payload enriquecido
                          ▼
┌─────────────────────────────────────────────────────────────┐
│            /frontend  (React + Monaco)                      │
│  Tab "Analizar"                                            │
│    Editor SQL → tarjetas + comparativo enriquecido E7      │
│    BannerParcial si /analyze falla parcialmente (E8)       │
│    Píldoras de validación R3 por tarjeta (E9)              │
│  Tab "Workload Analysis"                                   │
│    Uploader CSV/JSON + tabla top 10 clickeable (E4)        │
└─────────────────────────────────────────────────────────────┘
                          ▲
                ┌─────────┴──────────┐
                │     /workload      │
                │  parser (E1)       │
                │  scoring (E2)      │
                └────────────────────┘
```

**Flujo 1 — análisis individual (sin cambio desde Fase 3):**

1. El usuario pega su query en el editor.
2. `POST /analyze` → motor corre los 18 detectores.
3. Sandbox valida cada CREATE INDEX con schemas temporales únicos (E5).
4. LLM explica; cross validator la chequea.
5. Frontend renderea tarjetas con comparativo enriquecido (E7) y
   píldoras de validación (E9). Si algo falló parcialmente, muestra
   el banner ámbar de E8 pero no crasha.

**Flujo 2 — análisis de workload (nuevo en Fase 4):**

1. El usuario sube su export de `pg_stat_statements` (CSV o JSON).
2. `POST /workload` → `/workload` parsea el archivo (E1) y calcula
   el score por total_exec_time (E2).
3. Frontend muestra la tabla con top 10 queries ranqueadas (E4).
4. El usuario hace click en una fila → la query se precarga en el
   editor y se dispara `/analyze` automáticamente.

---

## 4. Lo que se cerró en Fase 4 — módulo por módulo

### 4.1 `/workload` — módulo nuevo de análisis de carga

**Misión Fase 4:** que el producto no obligue al usuario a recordar
qué queries copiar al editor. `pg_stat_statements` ya las tiene todas
— solo hay que ranquearlas por impacto real.

**Tickets cerrados:** E1, E2, E3.

#### E1 — Parser de pg_stat_statements

`workload/parser.py` recibe el export en CSV o JSON de la vista
`pg_stat_statements` y devuelve una lista de `WorkloadEntry` con:
`query`, `calls`, `total_exec_time`, `mean_exec_time`, `rows`.

**Decisión a defender — heurística de formato:** el parser infiere el
formato por la primera línea (si empieza con `[` → JSON, si no →
CSV). No se pide al usuario que especifique el formato. Soporta
nombres de columna de PG ≤ 12 (`total_time`/`mean_time`) y de PG ≥ 13
(`total_exec_time`/`mean_exec_time`) — el mismo parser funciona con
cualquier versión de Postgres que tenga el cliente.

#### E2 — Score de impacto por tiempo total

`workload/scoring.py` calcula un score normalizado 0..1 para cada
query, basado en `total_exec_time` (no en frecuencia). La decisión es
deliberada y tiene respaldo en la rúbrica:

> Una query que corre 10 veces y tarda 5s cada una (50s totales) duele
> más que una que corre 10,000 veces y tarda 1ms (10s totales).

`score = total_exec_time / max(total_exec_time)` sobre el top N
(default 10). La función es pura: sin I/O, sin estado global.

#### E3 — Endpoint `POST /workload`

Endpoint en FastAPI que acepta el archivo de `pg_stat_statements` vía
multipart (file upload) o raw body. Devuelve el top 10 estructurado:
`query`, `score`, `total_exec_time`, `mean_exec_time`, `calls`.

**Decisión a defender — multipart + raw body:** los clientes CLI
(cURL, Python scripts) naturalmente hacen raw body; los formularios
web hacen multipart. Soportar ambos evita que el frontend necesite
base64 manual y que los usuarios de CLI ajusten sus scripts.

---

### 4.2 `/sandbox` — sandbox endurecido

**Misión Fase 4:** el sandbox de Fase 2/3 ya validaba CREATE INDEX,
pero tenía dos puntos de fragilidad: schemas zombie si el proceso
crashaba a la mitad, y operaciones sin timeout que podían colgar el
orquestador indefinidamente.

**Tickets cerrados:** E5, E6.

#### E5 — Cleanup automático de schemas

Cada análisis usa un schema temporal con nombre único:
`analysis_{uuid4()}`. Al terminar (o al fallar), el sandbox ejecuta
`DROP SCHEMA analysis_{uuid} CASCADE`. Además, al startup del backend
se llama `cleanup_zombie_schemas(pool)` que dropea todos los schemas
con prefijo `analysis_` que hayan quedado huérfanos de sesiones
anteriores.

**Decisión a defender — UUID por análisis en lugar de nombre fijo:**
si dos análisis corren en paralelo (posible con FastAPI async), un
schema fijo colisionaría. El UUID garantiza aislamiento sin locking
adicional.

#### E6 — Timeouts duros por operación

Cada operación contra el sandbox (CREATE INDEX, EXPLAIN, DROP schema,
setup) tiene un timeout duro de 5 segundos implementado con
`SET LOCAL statement_timeout = 5000` en el mismo bloque de transacción.
Si el timeout se excede, la operación aborta y el sandbox devuelve
`verdict="inconclusive"`. El thread principal no se bloquea.

**Decisión a defender — `SET LOCAL statement_timeout` vs asyncio
timeout:** el timeout de Postgres es nativo y sobrevive si el thread
del Python muere de forma inesperada. Un `asyncio.wait_for` externo
no cancela la query en la BD, solo abandona la espera en Python
dejando la query corriendo. El timeout nativo es más seguro para un
sandbox que no debe costarnos recursos no controlados.

---

### 4.3 `/sandbox` + `/backend` — comparativo enriquecido (E7)

**Ticket cerrado:** E7.

`PlanComparison.jsx` se reescribió para mostrar más que costo+tipo:

- **Titular de transición** destacado: "El planner pasa de `Seq Scan`
  a `Index Scan`".
- **Dos paneles** con tipo de nodo, `total_cost` y `plan_rows` (filas
  estimadas por el planner).
- **Resumen ejecutivo automático**: "redujo el costo estimado de X a Y
  — Zx mejora estimada en sandbox."

**Decisión a defender — filas estimadas en lugar de tiempo:**
el sandbox corre `EXPLAIN` sin `ANALYZE` (las tablas están vacías por
R6). Un `EXPLAIN ANALYZE` sobre tablas vacías no produciría tiempos
comparables a producción y solo sumaría latencia. `plan_rows` siempre
existe en el plan y es un dato honesto que muestra cómo cambia el
método de acceso, no cuántas filas hay.

**Decisión a defender — resumen ejecutivo en el frontend:**
el string "Zx mejora" es derivable de forma determinística desde los
campos `cost_before`/`cost_after` del payload. Generarlo en el backend
como string pre-computado acoplaría el backend a decisiones de
presentación. El backend mantiene el payload como datos puros; el
frontend calcula la prosa. Consistente con el diseño de C11.

---

### 4.4 `/backend` — aislamiento de errores (E8)

**Ticket cerrado:** E8.

Cada etapa del orquestador (sanitize, EXPLAIN, detectores, sandbox,
LLM) está envuelta en `try/except`. Si una etapa falla:

- Las demás siguen ejecutando.
- El endpoint devuelve resultados parciales con `partial=true` y un
  array `errors[]` que lista qué etapa(s) fallaron.
- El frontend muestra un banner ámbar arriba de las tarjetas con la
  lista de fallos, pero las detecciones y recomendaciones
  determinísticas que sí se calcularon se siguen mostrando.
- El endpoint **nunca crasha con 500** por un fallo de LLM o sandbox.

**Decisión a defender — banner ámbar en lugar de error global:**
si el LLM cae pero el motor detectó 3 anti-patterns, mostrar una
pantalla de error vacía sería peor que mostrar las 3 tarjetas con
explicación de plantilla. El usuario obtiene valor aunque una capa
falle. Es la implementación concreta de R5 ("el producto debe
funcionar sin LLM").

---

### 4.5 `/frontend` — indicadores de validación R3 (E9)

**Ticket cerrado:** E9.

Cada tarjeta de recomendación muestra 4 píldoras de validación:

| Indicador | Significado |
|---|---|
| ✓/✗ Schema OK | El SQL recomendado hace referencia a tablas/columnas que existen en el snapshot |
| ✓/✗ No duplica índice | El índice sugerido no duplica un índice existente |
| ✓/✗ Sintaxis válida | El SQL pasa `EXPLAIN` sin error de sintaxis |
| ✓/✗ Sandbox confirma mejora | El tipo de nodo cambió de Seq Scan a algo mejor |

El cómputo de los 4 indicadores vive en el backend
(`orchestrator._compute_validations`), no en el frontend. El frontend
solo renderiza el dict `validations` que le llega en el payload.

**Decisión a defender — 4 indicadores, no uno solo:** la pregunta
del Demo Day que más temen todos es "¿cómo evitan que la IA mienta?".
Cuatro indicadores con estados ✓/✗/— muestran visualmente que hay
capas de verificación independientes. No es solo "el LLM dijo algo" —
es "el LLM dijo algo, el motor lo validó en schema, el sandbox lo
confirmó en un plan real, y no pisó un índice existente". Eso es
la respuesta a la pregunta, no en palabras sino en UI.

---

### 4.6 `/frontend` — tab de Workload Analysis (E4)

**Ticket cerrado:** E4.

Tab nueva "Workload Analysis" en la SPA:

- **Uploader** de CSV/JSON con drag & drop.
- **Tabla** con top 10 queries: columnas score (barra visual 0..1),
  total time, avg time, calls, query preview (primeros 80 chars).
- **Click en una fila** → la query completa se precarga en el editor
  del tab "Analizar" y se dispara `/analyze` automáticamente.

**Decisión a defender — score como barra visual, no solo número:**
un número `0.847` no comunica urgencia. Una barra que llena casi toda
la celda sí. La idea es que el usuario entienda de un vistazo cuáles
queries le están costando el 80% del tiempo, sin leer decimales.

---

### 4.7 E10–E13 — Documentación técnica de módulos

Cuatro archivos de documentación orientados a que cualquier miembro
del equipo (o el jurado) pueda entender la API de cada módulo sin
leer el código fuente:

| Ticket | Archivo | Contenido |
|--------|---------|-----------|
| E10 | `/docs/conector.md` | API pública del conector, modo offline, cómo invalidar cache, snippets de código |
| E11 | `/docs/motor.md` | Arquitectura del parser, lista de 18 detectores con reglas, cómo agregar uno nuevo |
| E12 | `/docs/ia.md` | Qué se sanitiza, formato del prompt, schema de respuesta esperado, validaciones cruzadas |
| E13 | `/docs/sandbox.md` | Por qué no se copian datos, cómo se falsean stats, timeouts, cleanup |

**Decisión a defender — documentación en `/docs/`, no solo en
`CLAUDE.md`:** los `CLAUDE.md` por módulo están orientados a agentes
de Claude Code trabajando en ese módulo (API interna, convenciones,
cómo correr tests). Los `/docs/*.md` están orientados a lectores
humanos que quieren entender el sistema sin abrir el código. Son
audiencias distintas, formatos distintos. El README principal enlaza
a `/docs/` para el jurado; los agentes leen `CLAUDE.md`.

---

## 5. Estado al cierre de Fase 4

### Tickets cerrados

| Código | Descripción | Estado |
|--------|-------------|--------|
| E1 | Parser de pg_stat_statements | ✅ |
| E2 | Score de impacto por tiempo total | ✅ |
| E3 | Endpoint POST /workload | ✅ |
| E4 | Tab "Workload Analysis" en frontend | ✅ |
| E5 | Sandbox con cleanup automático | ✅ |
| E6 | Sandbox con timeouts duros | ✅ |
| E7 | Comparativo before/after enriquecido | ✅ |
| E8 | Aislamiento de errores en /analyze | ✅ |
| E9 | Indicadores de validación en frontend | ✅ |
| E10 | Documentación API del conector | ✅ |
| E11–E13 | Documentación motor, IA, sandbox | ✅ |

### Tests nuevos en Fase 4

| Suite | Tests | Estado |
|-------|-------|--------|
| `tests/workload/test_workload_parser.py` | 7 | ✅ verde |
| `tests/workload/test_workload_scoring.py` | 5 | ✅ verde |
| `tests/backend/test_workload.py` | 5 (E3) | ✅ verde |
| `tests/sandbox/test_validator.py` | +nuevos E6/E7 | ✅ verde |
| `tests/backend/test_orchestrator.py` | +5 nuevos E9 | ✅ verde |

### Cobertura de detección (sin cambio desde Fase 3)

**18/20** queries cubiertas. Las dos huérfanas (Q05, Q10) siguen como
`xfail` — detectores correctos, problema del seed de AppDB, no del
motor. **0 falsos positivos** sobre 10 queries sanas.

---

## 6. Las reglas inviolables (cómo se cumplen en Fase 4)

| #   | Regla | Cómo se cumple en Fase 4 |
|-----|-------|--------------------------|
| R1  | Motor decide, LLM explica | Sin cambio. Los 18 detectores son funciones puras. |
| R2  | Detección sobre estructura, no strings | Sin cambio. |
| R3  | Toda salida del LLM se valida antes de mostrarla | E9 hace visibles las 4 capas de validación. |
| R4  | Nunca enviar literales al LLM | Sin cambio. El workload también pasa por sanitize antes de llegar al LLM. |
| R5  | El producto debe funcionar sin LLM | E8 garantiza que si el LLM falla, el endpoint sigue devolviendo detecciones determinísticas. |
| R6  | Sandbox no copia datos, solo schema y stats | E5/E6 endurecen el sandbox sin cambiar este principio. Los schemas temporales siguen vacíos. |
| R7  | Conexiones a la BD del cliente son read-only | Sin cambio. |
| R9  | Detectores son funciones puras | Sin cambio. E1/E2 también son funciones puras. |
| R10 | Cada detector con tests +/- | Sin cambio. La nueva suite de workload sigue el mismo patrón. |
| R15 | Documentar en el mismo PR que el código | E10–E13 son entregables de documentación dedicados. E1–E9 actualizaron sus `CLAUDE.md` en el mismo PR. |

---

## 7. Cheat sheet para el Demo Day (Fase 4 edition)

**P: ¿Qué hace la pestaña de Workload Analysis?**
R: El usuario exporta `pg_stat_statements` desde su Postgres (es una
vista nativa, siempre está disponible). Lo sube como CSV o JSON.
Nosotros calculamos qué queries están costando más tiempo en total
(no las más frecuentes — las que más duelen) y mostramos el top 10.
Un click en cualquier fila lleva al análisis completo de esa query.

**P: ¿Por qué ranquear por tiempo total y no por frecuencia?**
R: Una query que corre 10,000 veces en 1ms (10s totales) duele menos
que una que corre 10 veces en 5s (50s totales). La rúbrica lo pide
explícitamente. El score es `total_exec_time / max` — normalizado
para que sea fácil de visualizar como barra.

**P: ¿Qué pasa si el sandbox se cuelga validando un índice raro?**
R: Cada operación tiene un timeout duro de 5 segundos implementado
con `SET LOCAL statement_timeout` en Postgres nativo. Si se excede,
devuelve `verdict="inconclusive"` y el endpoint sigue. El usuario
ve la tarjeta con indicador ámbar en "sandbox confirma mejora"; las
otras validaciones siguen mostrándose.

**P: ¿Qué pasa si el LLM cae en medio de un análisis?**
R: E8. El endpoint nunca crasha. Si el LLM falla, la explicación cae
a plantilla determinística (R5). Si el sandbox falla, las detecciones
siguen mostrándose. El banner ámbar lista qué etapas fallaron; las
tarjetas de lo que sí se calculó se siguen mostrando.

**P: ¿Qué muestran los iconos verdes y rojos en cada tarjeta?**
R: Son los 4 checks anti-alucinación: schema OK (las columnas que
menciona el LLM existen), no duplica índice (no recomienda algo que
ya está), sintaxis válida (el SQL pasa EXPLAIN), y sandbox confirma
mejora (el planner cambió de Seq Scan a algo mejor). Verde = pasó,
rojo = falló, gris = no aplica para este tipo de recomendación
(ej: ANALYZE no tiene sandbox).

**P: ¿Por qué el comparativo no muestra tiempos?**
R: El sandbox monta tablas vacías por R6. Un `EXPLAIN ANALYZE` sobre
tablas vacías no mediría nada comparable a producción — solo sumaría
latencia. El `plan_rows` (filas estimadas por el planner) sí existe
siempre y es un dato honesto. La señal real es el cambio de tipo de
nodo (de Seq Scan a Index Scan), que sí representa una diferencia
estructural en cómo Postgres accede a los datos.

---

## 8. Estado de tests al cierre de Fase 4

| Módulo | Tests | Estado |
|--------|-------|--------|
| `conector` | 43 | ✅ verde |
| `motor` (parser + find_nodes) | 42 | ✅ verde |
| `motor/detectors` (18 detectores) | ~361 | ✅ verde |
| `sandbox` | ✅ + E6/E7 nuevos | ✅ verde |
| `backend/orchestrator` | ✅ + E8/E9 nuevos | ✅ verde |
| `workload` (E1 + E2 + E3) | 17 nuevos | ✅ verde |
| `tests/integration/` (D14 + D15) | 30 queries | 18/20 cubiertas, 0 FP |

**Suite total del proyecto al cierre de Fase 4:** ~500+ tests.

---

## 9. Para profundizar

- `workload/CLAUDE.md` — API del módulo, formato de `WorkloadEntry`,
  cómo correr los tests sin AppDB.
- `sandbox/CLAUDE.md` — contrato de schemas temporales, comportamiento
  de E5 (cleanup zombie) y E6 (timeouts).
- `backend/CLAUDE.md` — payload extendido de E7 (comparativo), E8
  (partial flag) y E9 (dict validations).
- `frontend/CLAUDE.md` — qué componentes se agregaron en E4/E7/E8/E9.
- `docs/conector.md`, `docs/motor.md`, `docs/ia.md`,
  `docs/sandbox.md` — documentación orientada a lectores humanos
  (E10–E13).
- `docs/estudio/fase1-cimientos.md` — cómo se construyeron los
  cimientos del sistema.
- `docs/estudio/fase2-flujo-end-to-end.md` — cómo se conectó el
  primer flujo real.
- `docs/estudio/fase3-ancho-de-detectores.md` — cómo se ampliaron los
  18 detectores.

---

## 10. Glosario rápido (Fase 4)

| Término | Significado |
|---------|-------------|
| **pg_stat_statements** | Vista nativa de Postgres que acumula estadísticas de ejecución de todas las queries normalizadas: calls, total_exec_time, mean_exec_time, rows. Requiere `shared_preload_libraries = 'pg_stat_statements'` (ya activo en AppDB). |
| **WorkloadEntry** | Dataclass del módulo `/workload` con los campos: `query`, `calls`, `total_exec_time`, `mean_exec_time`, `rows`, `score`. |
| **score** | Valor 0..1 calculado como `total_exec_time / max(total_exec_time)` sobre el top N. 1.0 = la query que más tiempo consume. |
| **analysis_{uuid}** | Nombre del schema temporal creado en el sandbox para cada análisis. Garantiza aislamiento entre análisis concurrentes. |
| **cleanup_zombie_schemas** | Función del sandbox que dropea todos los schemas con prefijo `analysis_` al startup del backend — limpieza de sesiones anteriores que crasharon. |
| **SET LOCAL statement_timeout** | Comando SQL de Postgres que cancela la operación actual si tarda más de N ms. "LOCAL" = aplica solo en la transacción actual. Es el mecanismo de E6. |
| **partial=true** | Flag en el payload de `/analyze` que indica que una o más etapas fallaron pero el endpoint devuelve resultados parciales. Acompañado de `errors[]`. |
| **ValidationIndicators** | Componente React (E9) dentro de `RecommendationCard` que renderiza las 4 píldoras de validación. Consume el dict `validations` del backend — no computa nada. |
| **BannerParcial** | Componente React (E8) en `App.jsx` que muestra el aviso ámbar cuando el backend devuelve `partial=true`. |
| **plan_rows** | Número de filas que el planner estima que el nodo producirá. Siempre presente en el plan (con o sin ANALYZE). Es el campo que E7 agrega al comparativo. |
| **executive_summary** | Prosa generada en `PlanComparison.jsx` (no en el backend): "redujo el costo estimado de X a Y — Zx mejora estimada en sandbox". |
| **E10–E13** | Tickets de documentación: conector, motor, IA, sandbox. Orientados a lectores humanos, complementan los `CLAUDE.md` (orientados a agentes). |

---

> **Última actualización:** 2026-05-13, al cierre de Fase 4.
> Cobertura de detección: **18/20** queries cubiertas,
> **0 falsos positivos** sobre 10 queries sanas.
> El workload tab (E1–E4), el sandbox endurecido (E5–E6) y el
> polimento defensivo (E7–E9) están mergeados en `main`.
> Demo Day: **2026-05-14**.

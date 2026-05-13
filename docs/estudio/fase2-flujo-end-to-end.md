# Fase 2 — Primer flujo end-to-end de PgPilot

> **Para qué sirve este documento.** Resume todo lo que construimos en
> Fase 2 (C1–C12) de forma que cualquiera del equipo, aunque no sea
> experto en Postgres o en el stack, pueda entender qué hacemos, por
> qué lo hacemos así, y defenderlo en el Demo Day.
>
> No reemplaza el código ni los `CLAUDE.md` por módulo. Es un mapa.

---

## 1. ¿Qué es PgPilot, en 3 frases? (recordatorio)

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

## 2. ¿Qué cambia entre Fase 1 y Fase 2?

**Fase 1** dejó los seis módulos en su sitio (`conector`, `motor`,
`ia`, `frontend`, `backend`, `sandbox`) pero conectados con stubs.
El backend devolvía listas vacías; el frontend imprimía JSON crudo.
**Fase 2 cierra el flujo end-to-end**: pegas una query en el editor,
clic en "Analizar" y obtienes una tarjeta con detección,
recomendación validada por sandbox y explicación pedagógica generada
por Claude (con caída automática a plantilla si el LLM no está).

En una frase: **Fase 1 cableó la casa, Fase 2 prendió la luz.**

La regla #1 sigue igual:

> **El motor determinístico DETECTA y DECIDE. El LLM EXPLICA y
> PROPONE. El motor VALIDA lo que el LLM propone. Si el LLM contradice
> al motor, gana el motor.**

Y en Fase 2 esa regla se vuelve código real: hay un orquestador en
`/backend` que llama detector → recomendador → sandbox → LLM → cross
validator, en ese orden, y el frontend muestra una etiqueta sutil
("explicación generada sin IA") cuando la prosa vino de plantilla.

---

## 3. Mapa mental: cómo se conectan las piezas (versión Fase 2)

```
┌────────────────────────────────────────────────────────────┐
│                    BD del cliente (AppDB)                  │
│            Postgres real con queries lentas                │
└──────────────────────────┬─────────────────────────────────┘
                           │  read-only, timeout 5s
                           ▼
┌──────────────────────────────────────────────────────────┐
│                       /conector                          │
│  Pool psycopg + extractores de metadata (snapshot)       │
└──────────────────────────┬───────────────────────────────┘
                           │  SchemaSnapshot
                           ▼
┌──────────────────────────────────────────────────────────┐
│              /backend  (FastAPI — orquestador real)      │
│   POST /analyze                                          │
│     1. sanitize(query)            → ia.sanitize          │
│     2. EXPLAIN → parse_explain    → motor                │
│     3. correr detectores          → motor.detectors      │
│     4. recomendar                 → motor.recommender    │
│     5. validar en sandbox         → sandbox.validate_…   │
│     6. explicar (LLM o plantilla) → ia.explain_recom…    │
│     7. devolver JSON al frontend                         │
└──┬──────────────────┬──────────────────┬─────────────────┘
   │                  │                  │
   ▼                  ▼                  ▼
┌──────────┐   ┌────────────┐   ┌───────────────────────┐
│  /motor  │   │    /ia     │   │      /sandbox         │
│ detector │   │ prompt +   │   │ valida CREATE INDEX   │
│ recomien │   │ LLM call + │   │ con EXPLAIN antes/    │
│ dador    │   │ guardrails │   │ después               │
└──────────┘   └────────────┘   └───────────────────────┘
                           ▲
                           │  JSON con detecciones
                           ▼
┌──────────────────────────────────────────────────────────┐
│            /frontend  (React + Monaco)                   │
│  Editor SQL + tarjetas (DetectionCard +                  │
│  RecommendationCard) + comparativo before/after          │
└──────────────────────────────────────────────────────────┘
```

**Flujo end-to-end al cierre de Fase 2:**

1. El usuario pega su query en el editor del frontend.
2. El frontend hace `POST /analyze` al backend.
3. El backend sanitiza la query (R4) y la corre con
   `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` contra AppDB.
4. El motor parsea el plan y dispara los detectores registrados
   sobre el árbol.
5. Por cada detección, el recomendador del motor produce un
   `CREATE INDEX` / `ANALYZE` / `CREATE STATISTICS` con justificación.
6. La recomendación va al sandbox: se monta el schema vacío con
   stats falseadas, se aplica el `CREATE INDEX`, se corre `EXPLAIN`
   y se compara el tipo de nodo antes/después.
7. Si la validación pasa, `ia.explain_recommendation` llama a Claude
   con prompt sanitizado, valida la respuesta con Pydantic + cross
   validator, y devuelve `Explanation(source="llm")`. Si algo falla,
   cae a plantilla (`source="template"`).
8. El backend arma el payload y el frontend lo renderea como
   tarjeta con before/after.

---

## 4. Lo que se cerró en Fase 2 — módulo por módulo

### 4.1 `/motor` — el cerebro determinístico, ahora con detectores y recomendador

**Misión Fase 2:** dejar de ser solo "parser de EXPLAIN" para ser el
componente que **decide** qué es anti-pattern y **propone** la
acción concreta. Toda la lógica sigue siendo Python puro (R9): sin
LLM, sin red, sin estado global.

**Tickets cerrados:** C1, C2 (más D2–D12 y D16–D22 de Fase 3
mergeados temprano para empujar cobertura — ver §5).

#### C1 — Primer detector real (Seq Scan en tabla grande con índice disponible)

`detect_seq_scan_on_large_table(plan, snapshot) -> Detection`.
Función pura. Lógica:

1. `find_nodes(plan, "Seq Scan")` (R2: estructura, no strings).
2. Para cada Seq Scan: ¿la tabla tiene ≥100k filas en el snapshot?
3. ¿La columna del filtro tiene un índice btree disponible?
4. Si las dos respuestas son sí → **dispara** (el planner está
   ignorando un índice existente, típicamente por stats
   desactualizadas).

C1 **NO** dispara cuando falta el índice — ese caso lo cubre D16.
La frontera está documentada explícitamente en el backlog: "C1 =
índice existe y se ignora; D16 = índice falta". Mezclarlos pisaría
recomendaciones distintas (`ANALYZE` vs `CREATE INDEX`).

**Decisión a defender — contrato `Detection` cuajado en C1:**
`Detection(found, confidence, evidence={"matches": [...]})`. El
`matches` es lista vacía cuando no dispara (no `{}`), de modo que
todos los callers iteran `evidence["matches"]` sin chequear `found`
primero. Esta convención la copian D2–D22 sin esfuerzo.

**Por qué importa para defensa:** la columna del filtro se infiere
del campo `Filter` del nodo (texto **estructurado** que emite
Postgres en EXPLAIN), no del SQL del usuario. Eso preserva R2 y
sobrevive a AppDB v2 (cuando el profe renombre tablas).

#### C2 — Recomendador de índice básico

`recommend_for_seq_scan_on_large_table(detection, snapshot) ->
list[Recommendation]`. Por cada match emite una `Recommendation`
inmutable con:

- `kind`: `"create_index"` o `"analyze"` (el recomendador detecta
  si el índice equivalente ya existe en el snapshot; si sí, manda
  `ANALYZE`, si no, manda `CREATE INDEX`).
- `create_index_sql`: SQL del DDL con identificadores citados.
- `justification`: prosa que cita selectividad estimada y nota
  sobre índice parcial si `null_frac > 50%`.
- `expected_impact`: cambio esperado en el plan.
- `selectivity`: `1/n_distinct` cuando hay stats positivas,
  `n_distinct` como ratio cuando es negativo (convención Postgres),
  `None` cuando la tabla nunca tuvo ANALYZE.

**Decisión a defender — kinds duales en una sola función:** la
tentación era escribir dos recomendadores. Lo unificamos porque la
detección de "¿ya existe el índice?" es trivial sobre el snapshot
y emitir `ANALYZE` vs `CREATE INDEX` desde el mismo punto evita
fragmentar la lógica. Cuando D16 entró (caso "índice falta") solo
hubo que escribir `recommend_for_missing_index` con la misma firma.

**R14 estrictamente respetado:** los nombres de tabla/columna salen
del snapshot y de la detección. Cero literales de AppDB en el
recomendador.

#### D13 — Recomendador con selectividad real (mergeado dentro de Fase 2)

Aunque está numerado como D13 (Fase 3), aterrizó dentro de la misma
ola que cerró C2 porque la rúbrica exige no recomendar índices
inútiles. Agrega:

- Umbral `MIN_SELECTIVITY_FOR_INDEX = 0.2`. Si la columna no es
  suficientemente selectiva (ej: 3 valores distintos en 10M filas),
  un btree no aporta — Postgres prefiere Seq Scan.
- Cuando se descartaría un `CREATE INDEX`, el recomendador no lo
  borra: emite una `Recommendation(kind="skipped_low_selectivity")`
  que va al log/JSONL pero no a la UI principal.
- Orquestador `recommend(detections, snapshot)` que recibe
  `dict[código → Detection]` y devuelve todas las recomendaciones
  unificadas.

---

### 4.2 `/sandbox` — el validador, ahora con veredicto estructural

**Misión Fase 2:** confirmar que una recomendación del motor
**efectivamente** cambia el plan, antes de mostrársela al usuario.

**Tickets cerrados:** C3.

#### C3 — Validación de recomendaciones con sandbox

`validate_index_recommendation(pool, snapshot, query, recommendation)
-> ValidationResult`. Flujo:

1. Monta el schema temporal (B15).
2. Corre `EXPLAIN` original → `node_type_before`, `cost_before`.
3. Aplica el `CREATE INDEX` de la recomendación (en sandbox).
4. Corre `EXPLAIN` otra vez → `node_type_after`, `cost_after`.
5. Dropea el schema (cleanup en `try/finally`).
6. Compara y devuelve veredicto.

Veredictos posibles:

| `verdict` | Cuándo |
|-----------|--------|
| `validated` | El plan cambió de `Seq Scan` a `Index Scan` / `Bitmap (Heap|Index|Only) Scan` sobre la tabla afectada. |
| `discarded` | Mismo tipo de nodo (el planner sigue ignorando el índice) o cambio inesperado. |
| `skipped_no_sandbox_signal` | La recomendación es `kind="analyze"`. Un ANALYZE sobre tablas vacías no produce señal comparable. |

**Decisión clave a defender — veredicto por TIPO DE NODO, no por
costo absoluto:** la deuda de B15/B16 (sandbox con tablas vacías →
costos colapsan a ~0) bloquea cualquier comparación de magnitud.
Pivoteamos C3 para razonar sobre el **cambio cualitativo** (Seq →
Index). Esa señal sí es confiable. Los costos se siguen
reportando como dato secundario en `sandbox_plan_comparison` con
una etiqueta honesta en la UI ("estimado en sandbox").

**Decisión a defender — `verdict_from_plans` como función pura
separada:** la orquestación (setup/teardown/CREATE INDEX) requiere
Docker y es lenta. La función de comparación es pura y se testea
con planes sintéticos sin Docker. Los tests unit cubren la lógica
del veredicto; dos tests de integración cubren el pipeline
completo.

**Detalle de seguridad:** el `CREATE INDEX` en sandbox usa
`recommendation.index_name + "_c3"` y identificadores citados,
para evitar colisión con índices preexistentes del snapshot y para
soportar nombres con caracteres especiales.

---

### 4.3 `/ia` — la capa que habla con Claude (con todos los guardrails)

**Misión Fase 2:** producir prosa pedagógica de calidad sin
sacrificar privacidad ni precisión. Esta es la capa donde el LLM
finalmente entra al flujo, siempre detrás de una pared de
validaciones.

**Tickets cerrados:** C4, C5, C6, C7, C8 (más un orquestador
`explain_recommendation` que los une).

#### C4 — Prompt estructurado al LLM

`build_explanation_prompt(detection, plan, recommendation,
sanitized_query) -> LLMPrompt` (pura). El system prompt dice:

- "Tú no detectas anti-patterns. El motor ya lo hizo. Tú explicas."
- "No inventes nombres de tabla o columna que no estén en el
  payload."
- "Devuelve JSON estricto:
  `{explanation, suggested_rewrite, confidence}`."

El user-turn lleva, en JSON compacto (con `sort_keys=True` para
determinismo):

- `detection`: `{found, confidence, matches}`.
- `recommendation`: todos los campos.
- `plan_summary`: lista de nodos con campos macro (NO el árbol
  crudo completo — eso explotaría tokens).
- `sanitized_query`: el SQL con placeholders.
- `literal_placeholders`: `{placeholder → tipo}`. **Nunca el valor
  original.**

`call_llm(prompt, ...)` llama al endpoint `messages` de Anthropic
vía `httpx`. Modelo default `claude-sonnet-4-6`.

**Decisión a defender — `TypeError` si `sanitized_query` no es
`SanitizedQuery`:** defensa en profundidad para R4. Si alguien
intenta pasar un string crudo "por accidente", el código
**rechaza** en lugar de continuar. La privacidad no se delega a
disciplina del autor.

**Toggle `LLM_ENABLED=false` y ausencia de API key:** ambos casos
levantan `LLMDisabledError` antes de cualquier red. Cumple R5
(funcionar sin LLM).

#### C5 — Validación de la respuesta del LLM con Pydantic

`LLMResponseSchema` con validators estrictos:

- `explanation: str` (no vacío).
- `suggested_rewrite: str | None`.
- `confidence: float` (entre 0 y 1).

`request_validated_explanation(prompt, *, max_retries=1)` llama al
LLM, parsea con Pydantic, y si falla **reintenta una vez**. Si
vuelve a fallar, levanta `LLMResponseInvalid`. El orquestador la
atrapa y cae a plantilla.

**Defensa en profundidad — strip de fences markdown:** Claude a
veces envuelve el JSON en ` ```json … ``` `. El parser limpia los
fences antes de pasar el texto a Pydantic.

#### C6 — Validación cruzada (cross validator)

Cuando el LLM propone un rewrite, el sistema **no confía** en él.
`cross_validate(recommendation, llm_response, snapshot, sandbox_pool=…)`
verifica:

1. **Columnas existen:** todas las columnas mencionadas en el
   rewrite están en el snapshot (consulta a B2).
2. **Sin duplicados:** si el rewrite contiene `CREATE INDEX`, el
   nombre del índice no existe ya en el schema (los nombres de
   índice son scope-schema en Postgres).
3. **SQL parseable:** sqlglot puede parsear el rewrite sin error.
4. **(Opcional) Sandbox:** si hay `sandbox_pool`, corre
   `validate_index_recommendation` sobre el rewrite y descarta si
   `verdict == "discarded"`.

`CrossValidationResult(passed, reasons, sandbox_verdict)` lleva la
lista de razones diagnósticas. Si **cualquier** validación falla, el
orquestador cae a plantilla.

**Decisión a defender — conservador por construcción:** ante
cualquier inconsistencia, falla. La regla #1 implica que descartar
al LLM nunca es un costo alto — siempre hay plantilla.

#### C7 — Modo "LLM apagado" con plantillas

`explain_from_template(detection, recommendation) -> Explanation`.
Dos plantillas:

- `kind="create_index"`: explica cómo un Seq Scan compara con un
  Index Scan, cita selectividad, incluye el SQL del motor.
- `kind="analyze"`: explica que las stats están desactualizadas y
  por qué `ANALYZE` puede llevar al planner a usar el índice
  existente.

Confianza: `0.8` con selectividad, `0.6` sin.

**Por qué importa para defensa:** este es nuestro argumento de venta
("nuestro producto funciona sin IA"). Y es la red de seguridad para
todos los caminos donde el LLM falla.

#### C8 — Logs estructurados

`ia/logs.py`. Cada llamada al LLM deja una entrada JSONL con:
prompt sanitizado, raw response (truncado), validaciones que
pasaron/fallaron, prosa final mostrada, `request_id` para
correlación con la request HTTP del backend.

Es la evidencia para el Q&A: si te preguntan "¿qué pasó en este
análisis?", abres el log y respondes con datos.

#### Orquestador `explain_recommendation` (tie de C5+C6+C7+C8)

Función única que el backend (C9) consume:

```python
explanation = explain_recommendation(
    detection, plan, recommendation, sanitized_query,
    snapshot=snapshot, sandbox_pool=sandbox_pool,
    max_retries=1, request_id=request_id,
)
# explanation.source ∈ {"llm", "template"}
```

Garantía fuerte: **nunca propaga** `LLMDisabledError`, `LLMError`
ni `LLMResponseInvalid` al backend. Los 5 caminos posibles
(`llm_ok`, `llm_disabled`, `llm_error`, `llm_invalid_response`,
`cross_validation_failed`) caen a plantilla y dejan log JSONL antes
de retornar.

**Decisión a defender — orquestación en `ia/`, no en `backend/`:**
los hecho-cuando de C5/C7 hablan del comportamiento del sistema
completo ("cae a plantilla sin crashear"), no de una primitiva
aislada. El backend (C9) hace mucho más (parsear EXPLAIN, dispatch
a detectores, etc.) y mezclar la lógica de fallback ahí
contaminaría responsabilidades. `ia/explain.py` es la unidad
natural: el módulo `ia` es exactamente "capa de explicación".

---

### 4.4 `/backend` — orquestador real

**Misión Fase 2:** dejar de devolver listas vacías. Recibir la
query, conectar todo en orden, atrapar errores y traducirlos a
códigos HTTP semánticos.

**Tickets cerrados:** C9.

#### C9 — Endpoint `/analyze` conectando todo

`backend/orchestrator.py:analyze_query(query, *, pools, snapshot,
request_id)` hace:

1. `ia.sanitize(query)` (R4).
2. `pools.appdb` corre `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.
3. `motor.parse_explain` parsea el plan.
4. Itera detectores registrados: cada uno devuelve un `Detection`.
5. Para cada detección que dispara: corre el recomendador.
6. Para cada recomendación: corre `sandbox.validate_index_recommendation`
   (si `pools.sandbox` está configurado).
7. Para cada recomendación validada: corre
   `ia.explain_recommendation`.
8. Arma `AnalyzeResponse` y devuelve.

**Códigos de error mapeados explícitamente:**

| HTTP | Cuándo |
|------|--------|
| `422` | body inválido (sin `query` o vacía) |
| `503` | AppDB no configurada al startup |
| `400` | Postgres rechazó la query (sintaxis, tabla inexistente, permiso) |
| `403` | el usuario intentó UPDATE/INSERT/DROP — la conexión es read-only por R7 |
| `504` | EXPLAIN excedió el `statement_timeout` (5s default) |
| `500` | estado inesperado interno |

**Decisión a defender — snapshot cacheado al startup:** el
snapshot del schema se extrae **una vez** en `lifespan` de FastAPI
y se cachea en `app.state.snapshot`. Refrescarlo requiere reiniciar
el proceso. Razón: la latencia del `/analyze` sería inaceptable si
extrajéramos el snapshot cada vez (10-15s contra AppDB real).

**Decisión a defender — orquestador en función separada (no en el
handler):** `analyze_query` es testeable con `FakePool` inline (no
necesita uvicorn ni AppDB). El handler de FastAPI solo traduce
errores a HTTP. Esto permite cubrir el "hecho cuando" de C9 con
tests unit rápidos.

**Payload extendido para C11:** el orquestador agrega
`sandbox_plan_comparison` a cada recomendación con
`{node_type_before, node_type_after, cost_before, cost_after}`
extraído del `ValidationResult`. Es un campo nuevo opcional —
B14/B13 siguen funcionando porque la estructura existente no
cambió.

---

### 4.5 `/frontend` — UI real, no más JSON crudo

**Misión Fase 2:** transformar el panel lateral en una vista que un
humano pueda leer rápido, copiar SQL con un click y entender el
impacto visualmente.

**Tickets cerrados:** C10, C11.

#### C10 — Tarjetas de detección y recomendación

Tres componentes nuevos:

- `DetectionCard.jsx`: por cada entrada de `detections[]`. Muestra
  título humanizado del tipo de pattern (de `seq_scan_on_large_table`
  → "Seq Scan en tabla grande"), confianza del motor (porcentaje) y
  la lista de `evidence.matches[]` con tablas/columnas afectadas.
- `RecommendationCard.jsx`: por cada entrada de `recommendations[]`.
  Renderea:
  - Título humanizado y badges: origen (`LLM` vs `Plantilla`),
    `sandbox_verdict` (validated / discarded / skipped).
  - Prosa de `explanation.text`.
  - Bloques SQL copiables: `create_index_sql` y
    `explanation.suggested_rewrite` (si el LLM lo propuso).
  - Botón "Copiar SQL" con `navigator.clipboard` y fallback
    silencioso (servir por http sin foco puede rechazar el permiso).
  - `<details>` colapsable con justificación + impacto +
    selectividad.
- `Card.css`: estilos VS Code oscuro, consistente con la decisión
  "sin Tailwind" del 2026-05-10.

**Decisión a defender — tarjetas en español, sin
internacionalización todavía:** el Demo Day es en español. Hacer
i18n ahora es overhead inútil. Si en algún momento sale del
contexto académico, se introduce `react-intl` (≈medio día).

#### C11 — Comparativo before/after

`PlanComparison.jsx`: consume
`recommendation.sandbox_plan_comparison` y renderea dos paneles
lado a lado:

- **Antes** (borde rojo): el tipo de nodo original (típicamente
  `Seq Scan`) + costo.
- **Después** (borde verde si el nodo cambió a `Index/Bitmap Scan`,
  gris si se mantuvo): nuevo tipo de nodo + costo.

Si ambos costos son positivos, calcula "Xx mejora estimada en
sandbox" junto con una advertencia textual:

> "Los costos del sandbox son sobre tablas vacías por R6 — la
> magnitud real depende de las estadísticas de producción."

Cuando `sandbox_plan_comparison` viene `null` (sandbox apagado, o
`verdict="skipped_no_sandbox_signal"` típico de ANALYZE), la
tarjeta muestra un mensaje neutral. **No miente.**

**Decisión a defender — honestidad sobre costos absolutos:** la
tentación era pintar "158x mejora" como hace la rúbrica del
profesor. Lo evitamos porque es engañoso: los costos en sandbox
**son** sobre tablas vacías. El cambio cualitativo (Seq → Index) es
real y se resalta visualmente; la magnitud absoluta se reporta con
asterisco honesto. Eso vale más en el Q&A que un número
impresionante mal sustentado.

#### `WorkloadTab.jsx` (E4 — adelanto de Fase 4)

Pestaña nueva con uploader de CSV/JSON de `pg_stat_statements`,
tabla con top 10 por `total_exec_time` y click-through que precarga
la query en el editor y dispara `/analyze` automáticamente.

---

### 4.6 `C12` — Prueba integral del slice

**Misión:** los 5 miembros, cada uno en su máquina, levantan
`docker compose up`, abren el frontend, pegan una query plantada de
AppDB con seq scan, y verifican el flujo end-to-end (detección +
recomendación + comparativo + explicación).

Estado: **en curso**. El flujo funciona en las máquinas de
desarrollo individuales; falta la ronda de validación cruzada en
las 5 máquinas. Cualquier divergencia entre máquinas se debugea en
grupo hasta que las 5 corran el mismo escenario.

---

## 5. Cobertura de detección al cierre de Fase 2

La rúbrica exige **≥16 de 20 queries plantadas detectadas**. Para
llegar ahí mergeamos en paralelo con C1–C12 buena parte de Fase 3:

**Detectores activos: 18**

| Código | Anti-pattern | Queries cubiertas |
|--------|--------------|---|
| C1  | Seq Scan en tabla grande con índice ignorado | 0 (depende del seed) |
| D2  | Stats obsoletas (mismatch plan/actual) | — (seed con ratio bajo) |
| D3  | Sort en disco | — (seed cabe en `work_mem`) |
| D4  | LIKE con wildcard al inicio | Q03 |
| D5  | Función no-immutable en WHERE | Q04 |
| D6  | OR sobre columnas de tablas distintas | — |
| D7  | Subquery correlacionada | Q09, Q19 |
| D8  | Nested Loop con outer grande | — |
| D9  | SELECT * en tabla grande | Q01, Q07, Q12, Q18 |
| D10 | Falta índice cubriente | — |
| D11 | Type mismatch (cast en WHERE) | — |
| D12 | CTE materializada innecesariamente | — |
| D16 | Falta índice (Seq Scan sin índice) | Q01, Q02, Q06, Q08, Q09, Q15, Q16 |
| D17 | Oportunidad de índice parcial | Q11 |
| D18 | Cardinalidad mal estimada (joins) | Q13 |
| D19 | HAVING que debería ser WHERE | Q16 |
| D20 | IN (SELECT) → EXISTS | Q17 |
| D22 | count(*) sin WHERE en tabla grande | Q20 |

**Cobertura final medida (2026-05-13): 18/20.** Las dos huérfanas
(Q05, Q10) tienen los detectores correctos mergeados pero el seed
actual de AppDB no cruza los umbrales — bajar los umbrales
introduciría falsos positivos. El equipo prefiere documentar como
`xfail` antes que relajar el motor.

**Falsos positivos:** **0 sobre 10 queries sanas** (test D15 en
`tests/integration/test_no_false_positives.py`). La rúbrica permite
hasta 3.

**Decisión a defender — xfail honesto, no relajar umbrales:**
ajustar el umbral D2 de 10× a 5× para cubrir Q10 lo haría chocar
con D18 (que usa 5× para joins) y produciría FP en queries sanas.
Crecer el seed de AppDB requiere coordinación que no cabe a 1 día
del Demo Day. Marcar `expected_covered=False` con nota explicativa
es la decisión profesional.

---

## 6. Las reglas inviolables (recordatorio + cómo se cumplen en Fase 2)

| #   | Regla                                                                 | Cómo se cumple en Fase 2                                  |
|-----|-----------------------------------------------------------------------|-----------------------------------------------------------|
| R1  | Motor decide, LLM explica                                             | El LLM solo entra después de detector+recomendador+sandbox. `cross_validate` descarta cualquier propuesta inconsistente. |
| R2  | Detección sobre estructura, no strings                                | Todos los detectores operan sobre `find_nodes(plan, …)` y campos tipados de `PlanNode`. Cero regex sobre el SQL del usuario. |
| R3  | Toda salida del LLM se valida antes de mostrarla                      | Pydantic (C5) + cross validator (C6) en serie. Falla → plantilla. |
| R4  | Nunca enviar literales al LLM                                         | `build_explanation_prompt` rechaza con `TypeError` si no recibe `SanitizedQuery`. Los placeholders viajan con `{placeholder → tipo}`, nunca el valor original. |
| R5  | El producto debe funcionar sin LLM                                    | Toggle `LLM_ENABLED=false` o ausencia de API key → plantilla. Demostrable en el demo apagando el LLM en vivo. |
| R6  | Sandbox no copia datos, solo schema y stats                           | C3 valida sobre tablas vacías con stats falseadas. Costos absolutos no se usan para el veredicto. |
| R7  | Conexiones a la BD del cliente son read-only                          | El pool de `/conector` aplica `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`. Mutaciones → 403. |
| R14 | No hardcodear nombres de tablas o columnas                            | El recomendador y los detectores leen todo del snapshot. Tests D15 verifican que ninguna detección depende de nombres específicos. |
| R15 | Documentación obligatoria al cerrar una actividad                     | Cada PR de C/D toca `PROGRESS.md` + `<módulo>/CLAUDE.md` + `docs/patterns/` cuando aplica. |

---

## 7. Cheat sheet para el Demo Day (versión Fase 2)

### "¿Cómo evitan que el LLM aluciné?"

**Tres capas en serie:**

1. **Arquitectura:** el motor determinístico decide qué es
   anti-pattern y qué SQL emitir. El LLM solo agrega prosa.
2. **Validación estructural (C5):** la respuesta del LLM pasa por
   Pydantic. Si está mal formada, se reintenta una vez y luego
   se descarta.
3. **Validación semántica (C6):** las columnas/índices que el LLM
   menciona se cotejan contra el snapshot. Si inventa algo, se
   descarta.

Si cualquier capa falla → **plantilla determinística** (C7). El
usuario nunca ve una alucinación.

### "¿Qué pasa si Anthropic está caído?"

Demuéstralo en vivo: apaga `LLM_ENABLED` (env var) y vuelve a
analizar. La tarjeta sigue saliendo, con etiqueta "explicación
generada sin IA". Esto es R5 + C7.

### "¿Cómo prueban que su recomendación funciona?"

Sandbox (C3). Antes de mostrarte la recomendación, montamos un
schema vacío con tus stats falseadas, aplicamos `CREATE INDEX`,
corremos `EXPLAIN` antes y después, y comparamos el tipo de nodo.
Si el planner no cambia de `Seq Scan` a `Index Scan`, descartamos
la recomendación con razón ("the planner still ignores the
index"). Es lo que viste en el panel "Antes/Después".

### "¿Por qué los costos del comparativo son tan bajos?"

Porque las tablas en sandbox están vacías (R6 — no copiamos datos).
Lo que es real es el **cambio cualitativo** del plan (Seq Scan →
Index Scan). La magnitud absoluta depende de las stats de
producción. La UI lo dice explícitamente.

### "¿Por qué cubren 18/20 y no 20/20?"

Q05 y Q10 tienen los detectores correctos (D3 y D2) mergeados, pero
las condiciones del seed actual de AppDB no cruzan los umbrales
(Q05 ordena 3.7MB en memoria, no derrama; Q10 tiene ratio 6× vs
umbral 10× de D2). Bajar los umbrales introduce falsos positivos en
queries sanas — el equipo prefiere honestidad sobre métrica.

### "¿Pueden mostrarme que no leakean datos al LLM?"

Sí. Abre el JSONL de logs (C8). Cada entrada tiene el prompt
sanitizado **literal** que se envió. Verás placeholders
`$LITERAL_5_0`, nunca `juan@empresa.com`. El test B11 ya hacía esto
con grep contra datos sensibles plantados.

---

## 8. Estado de tests al cierre de Fase 2

Suite total: **445 passed + 1 skipped + 2 xfailed** (~2:11 min con
integration). Distribución aproximada:

| Módulo                  | Tests | Notas                                                                |
|-------------------------|-------|----------------------------------------------------------------------|
| `conector`              | 43    | Mayoría integration (necesitan AppDB up)                             |
| `motor` (parser + nodos)| 42    | Unit puro, fixtures JSON versionados                                 |
| `motor.detectors`       | 100+  | Unit puro, un test file por detector                                 |
| `motor.recommender`     | 25+   | Unit puro, cubre los 4 kinds + filtro de selectividad                |
| `ia`                    | 50+   | Unit puro; tests del LLM marcados con marker `llm` (saltables)       |
| `sandbox`               | 16    | 14 integration + 2 unit del validador estructural                    |
| `backend`               | 20+   | Endpoint + CORS + orchestrator (con `FakePool` inline)               |
| `workload`              | 12    | Unit puro (parser + scoring)                                         |
| `tests/integration`     | 30+   | Cobertura D14 (20 queries) + anti-FP D15 (10 queries)                |

```bash
# Levantar BDs
docker compose up -d appdb sandbox

# Toda la suite (incluido integration)
APPDB_TEST_TIMEOUT_MS=180000 pytest

# Solo unit (rápido, sin Docker)
pytest -m "not integration and not llm"
```

**Tests de bloqueo crítico:**

- `test_coverage_meets_rubric_target` — exige ≥16/20. Si baja,
  rompe.
- `test_no_false_positives.py` — exige 0 FP sobre 10 queries
  sanas. Si aparece un FP, rompe.
- Tests `hecho-cuando` de C5/C6/C7 — verifican los caminos de
  caída a plantilla.

---

## 9. Para profundizar

Igual que en Fase 1, cada módulo tiene su `CLAUDE.md`. Los más
relevantes para Fase 2:

- `motor/CLAUDE.md` — convención de detectores
  (`(plan, snapshot) -> Detection`, `evidence={"matches": [...]}`),
  helpers compartidos en `motor/detectors/_common.py`, lista
  completa de los 18 detectores.
- `ia/CLAUDE.md` — orquestador `explain_recommendation`, los 5
  caminos posibles, contrato de `Explanation`, schema de C8 logs.
- `sandbox/CLAUDE.md` — `ValidationResult`, los 3 veredictos,
  cleanup en `try/finally`, deuda conocida sobre costos absolutos.
- `backend/CLAUDE.md` — payload extendido del `/analyze`, mapeo
  de errores a códigos HTTP, snapshot cacheado al startup.
- `frontend/CLAUDE.md` — mapeo del payload a componentes,
  honestidad de C11, decisión sin Tailwind.
- `docs/patterns/` — un archivo por anti-pattern detectado (18+
  archivos al cierre).
- `PROGRESS.md` — bitácora. Cada PR de C/D tiene su entrada con
  archivos modificados, decisiones y trade-offs.
- `docs/decisiones.md` — decisiones de stack y trade-offs que
  cubren el Criterio 1.2 de la rúbrica.
- `PgPilot_Backlog.md` — el backlog completo, con frontera C1↔D16
  documentada explícitamente.

---

## 10. Glosario rápido (delta sobre Fase 1)

Los términos de Fase 1 (`AppDB`, `EXPLAIN`, `planner`, `Seq Scan`,
`SchemaSnapshot`, `sandbox`, `sanitizador`, `PII`, `GUARDRAILS`,
etc.) siguen iguales. Términos nuevos que aparecen en Fase 2:

| Término                  | Significado                                                                                         |
|--------------------------|-----------------------------------------------------------------------------------------------------|
| **Detection**            | Dataclass inmutable que devuelven los detectores: `{found, confidence, evidence={"matches": [...]}}`. |
| **Recommendation**       | Dataclass inmutable del recomendador: `kind`, `create_index_sql`, `justification`, `selectivity`, etc. |
| **kind**                 | Tipo de recomendación: `create_index`, `analyze`, `create_partial_index`, `create_statistics`, `skipped_low_selectivity`. |
| **ValidationResult**     | Salida del sandbox tras validar una recomendación: `verdict`, `reason`, `node_type_before/after`, `cost_before/after`. |
| **verdict**              | `validated` / `discarded` / `skipped_no_sandbox_signal`. Decide si la recomendación se muestra. |
| **Explanation**          | Salida final de la capa `ia`: `text`, `suggested_rewrite`, `confidence`, `source ∈ {"llm","template"}`. |
| **source**               | De dónde viene la prosa: `"llm"` (Claude) o `"template"` (plantilla determinística). |
| **cross validator**      | Capa que cruza la respuesta del LLM contra el snapshot para descartar alucinaciones. |
| **plantilla**            | Prosa determinística que el motor produce cuando el LLM no está disponible o falla validación. |
| **request_id**           | UUID por request HTTP, propagado a los logs JSONL de C8 para correlación. |
| **sandbox_plan_comparison** | Campo del payload del backend con `{node_type_before, node_type_after, cost_before, cost_after}` consumido por la tarjeta C11. |
| **selectividad**         | `1/n_distinct` (o ratio cuando `n_distinct < 0`). Si > 0.2, el recomendador descarta el `CREATE INDEX`. |
| **xfail**                | Test esperado-falla. Q05 y Q10 están marcadas así porque el seed no cruza umbrales. |
| **D14**                  | Test de cobertura sobre AppDB v1 (20 queries → ≥16 deben dispararse). |
| **D15**                  | Test anti-falsos-positivos (10 queries sanas → 0 detecciones esperadas). |

---

> **Última actualización:** 2026-05-13, al cierre de Fase 2 (con
> Fase 3 D2–D12, D16–D22 y D13–D15 mergeados en paralelo para
> empujar cobertura). Próxima fase (Fase 4 — workload completo +
> sandbox endurecido) arranca con E5/E6 (cleanup automático y
> timeouts duros del sandbox), aunque E1–E4 (workload tab) ya
> aterrizaron como adelanto. Demo Day: **2026-05-14**.

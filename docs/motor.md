# Módulo `motor` — guía del cerebro determinístico

> **Audiencia:** developers fuera del equipo de PgPilot que quieran
> entender la arquitectura del motor, evaluar la batería de detectores
> o aprender a añadir uno nuevo.
>
> **Resumen en una línea:** el motor convierte el output de
> `EXPLAIN (FORMAT JSON)` en un árbol tipado, lo recorre con una
> batería de **19 detectores deterministas** que reconocen
> anti-patterns, y emite **recomendaciones de índice** auditables —
> sin tocar nunca el LLM ni la BD del cliente.

---

## 1. ¿Qué hace este módulo?

`motor/` cumple **tres responsabilidades** y nada más:

1. **Parsear EXPLAIN.** `parse_explain` convierte el JSON crudo que
   emite Postgres en un árbol de `PlanNode` con campos tipados,
   `frozen=True` (R9). El JSON crudo no se guarda — todo el análisis
   downstream opera sobre estructura.
2. **Detectar anti-patterns.** 19 detectores deterministas (funciones
   puras) recorren el árbol y producen `Detection(found, confidence,
   evidence)`. Cada detector tiene su archivo en
   `motor/detectors/` y su entrada en
   [`docs/patterns/`](patterns/).
3. **Recomendar índices** (cuando aplica). Cuatro detectores (C1,
   D16, D17, D18) tienen recomendador formal: producen
   `Recommendation` con SQL listo para copiar y selectividad estimada.
   Los otros 15 detectores reportan el hallazgo pero no proponen DDL.

**Lo que NO hace este módulo:**

- No habla con el LLM (esa lógica vive en `/ia`).
- No abre conexiones a la BD (`/conector`).
- No ejecuta nada contra el sandbox (`/sandbox`).
- No serializa al frontend (`/backend`).

**Regla #1 del proyecto, aplicada aquí:** *el motor decide, el LLM
explica*. Si en algún momento un detector consulta al LLM para
decidir si una query es problemática, la arquitectura del producto
se rompe. Los detectores son funciones puras Python; los tests son
deterministas; la batería entera corre en milisegundos.

---

## 2. Pipeline del motor

```
              ┌─────────────────────────────────────────┐
              │  EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)│
              │  …emitido por Postgres                   │
              └─────────────────┬───────────────────────┘
                                │ str / list / dict
                                ▼
                       parse_explain()
                                │
                                ▼
                     ┌──────────────────┐
                     │   ExplainResult  │
                     │   └─ root: PlanNode (árbol)
                     └────────┬─────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
       detector_X(plan, snapshot)      find_nodes(plan, "Seq Scan")
              │                               │
              ▼                               │
     Detection(found=True,                    │
              confidence=0.95,                │
              evidence={"matches": [...]})    │
              │                               │
              └─────────────┬─────────────────┘
                            │ detections dict
                            ▼
                  recommend(detections, snapshot)
                            │
                            ▼
                   list[Recommendation]
                   (con kind, SQL, selectividad)
```

`snapshot` es el `SchemaSnapshot` que devuelve `/conector`
(`{schema, sizes, stats}`). El motor solo lee de él, nunca lo muta.

---

## 3. Arquitectura del parser

### 3.1. `parse_explain(raw) -> ExplainResult`

Convierte el JSON crudo en un árbol tipado. Acepta tres formas para
evitar boilerplate en el caller:

- `str` — el JSON entero como string (típico de `psql -tAq` o cuando
  `cur.fetchone()[0]` viene serializado).
- `list[dict]` — lo que devuelve psycopg al hacer
  `cur.execute("EXPLAIN ...").fetchone()[0]` (Postgres siempre envuelve
  EXPLAIN en una lista de un elemento).
- `Mapping` — un entry suelto, útil en tests con fixtures.

Devuelve `ExplainResult(root, planning_time_ms, execution_time_ms)`.
Lanza `ValueError` con mensaje claro si la estructura no contiene un
nodo `Plan`. Propaga `json.JSONDecodeError` si el string no es JSON.

```python
from motor import parse_explain

raw = '''[{"Plan": {"Node Type": "Seq Scan", "Relation Name": "posts",
           "Startup Cost": 0.0, "Total Cost": 12345.0,
           "Plan Rows": 5000, "Plan Width": 50,
           "Filter": "(author_id = 42)"}}]'''
result = parse_explain(raw)
print(result.root.node_type)         # 'Seq Scan'
print(result.root.relation_name)     # 'posts'
print(result.root.total_cost)        # 12345.0
```

### 3.2. `PlanNode` (frozen dataclass)

Un nodo del plan. Inmutable por construcción (`frozen=True`) — los
detectores son funciones puras (R9), así que la inmutabilidad evita
mutaciones accidentales y permite `__hash__`.

Atributos relevantes, agrupados por rol:

| Categoría | Atributos |
|---|---|
| **Comunes** (todo nodo) | `node_type`, `startup_cost`, `total_cost`, `plan_rows`, `plan_width` |
| **EXPLAIN ANALYZE** | `actual_startup_time`, `actual_total_time`, `actual_rows`, `actual_loops` |
| **Identidad de relación** | `relation_name`, `alias`, `parent_relationship` (`"Outer" \| "Inner" \| "Member"`) |
| **Scan-specific** | `index_name`, `index_cond`, `recheck_cond`, `filter`, `rows_removed_by_filter`, `rows_removed_by_index_recheck`, `scan_direction`, `heap_fetches` |
| **Join-specific** | `join_type` (`"Inner"\|"Left"\|"Full"\|"Anti"\|"Semi"`), `inner_unique`, `hash_cond`, `merge_cond` |
| **Sort-specific** | `sort_key` (tupla), `sort_method`, `sort_space_type`, `sort_space_used` |
| **Aggregate-specific** | `strategy` (`"Plain"\|"Hashed"\|"Sorted"\|"Mixed"`), `partial_mode`, `group_key` (tupla) |
| **CTE / Subquery** | `cte_name`, `subplan_name` |
| **Hash-specific** | `hash_buckets`, `hash_batches`, `peak_memory_kb` |
| **Paralelismo** | `parallel_aware`, `workers_planned`, `workers_launched` |
| **Jerarquía** | `children: tuple[PlanNode, ...]` |

Cualquier campo que Postgres no haya enviado queda en `None` (nunca
se inventa). Si EXPLAIN se corrió sin `ANALYZE`, **todos** los
`actual_*` son `None`.

### 3.3. `ExplainResult` (frozen dataclass)

Wrapper con metadata top-level:

| Campo | Tipo | Descripción |
|---|---|---|
| `root` | `PlanNode` | Raíz del árbol. |
| `planning_time_ms` | `float \| None` | `None` si EXPLAIN sin ANALYZE. |
| `execution_time_ms` | `float \| None` | `None` si EXPLAIN sin ANALYZE. |

### 3.4. `find_nodes(tree, node_type) -> list[PlanNode]`

Helper de navegación. Recorre el árbol en **DFS pre-order** y
devuelve todos los nodos cuyo `node_type` matchea. Acepta:

- `tree`: un `PlanNode` o un `ExplainResult` (en el segundo caso
  recorre desde `result.root`).
- `node_type`: un `str` (match exacto) o cualquier iterable de `str`
  (match si está en la colección).

Devuelve lista vacía si no hay matches; nunca lanza por "no
encontrado". Es la primitiva sobre la que los detectores operan.

```python
from motor import find_nodes, parse_explain

result = parse_explain(raw)

seq_scans = find_nodes(result, "Seq Scan")
joins     = find_nodes(result, ("Hash Join", "Merge Join", "Nested Loop"))
```

### 3.5. `KNOWN_NODE_TYPES: frozenset[str]`

Los 17 tipos de nodo que el parser y los detectores han visto en
producción contra AppDB:

```
Seq Scan, Index Scan, Index Only Scan,
Bitmap Heap Scan, Bitmap Index Scan,
Nested Loop, Hash Join, Merge Join,
Sort, Hash, Aggregate, Limit,
Subquery Scan, CTE Scan, Materialize,
Gather, Gather Merge
```

**No es una lista cerrada:** el parser acepta cualquier `Node Type`
que Postgres emita (incluyendo `BitmapOr`, `Recursive Union`,
`WorkTable Scan` y futuros). Esta constante existe para validar
cobertura en tests y documentar contra qué se han escrito detectores.

---

## 4. Detectores: contrato y catálogo

### 4.1. `Detection` (frozen dataclass)

Salida común de todos los detectores:

| Campo | Tipo | Descripción |
|---|---|---|
| `found` | `bool` | `True` si el anti-pattern se detectó al menos una vez. |
| `confidence` | `float` | En `[0, 1]`. Determinístico cuando es estructural (1.0); heurístico cuando depende de umbrales. |
| `evidence` | `dict` | Convención: `evidence["matches"]` es `list[dict]` con un entry por ocurrencia. |

Cuando `found=False`, `matches` está vacío. Cuando `found=True`,
cada match contiene los hechos crudos que sostienen la detección
(tabla, columna, filtros relevantes, SQL sugerido, etc.).

### 4.2. Convenciones del módulo

Todas las funciones `detect_*` son **funciones puras** que:

- Reciben `(plan: ExplainResult | PlanNode, snapshot: SchemaSnapshot)`
  como argumentos posicionales obligatorios.
- Algunas aceptan `sql: str | None = None` como keyword-only adicional
  (los detectores que necesitan el SQL del usuario porque la
  información estructural no está en el EXPLAIN — D9, D11, D19, D20,
  D21).
- Devuelven `Detection(found, confidence, evidence)`.
- No tocan disco, ni red, ni el LLM, ni el sandbox.
- No hardcodean nombres de tablas/columnas — todo viene del schema /
  plan (protege el bonus de AppDB v2; ver R14).

### 4.3. Catálogo de detectores

Cada fila enlaza al doc del patrón en
[`docs/patterns/`](patterns/) y al archivo de implementación en
`motor/detectors/`. Confianza es la `Detection.confidence` típica
emitida por el detector.

| Código | Función | Antipattern | Confianza | Doc del patrón |
|---|---|---|---|---|
| **C1** | `detect_seq_scan_on_large_table` | Seq Scan sobre tabla ≥100k filas con índice btree disponible (síntoma de stats obsoletas) | 1.0 | [seq-scan-on-large-table.md](patterns/seq-scan-on-large-table.md) |
| **D2** | `detect_stale_statistics` | Ratio `plan_rows`/`actual_rows` ≥10× en un scan (excluye scans bajo `LIMIT`, ver fix 2026-05-13) | 0.85 | [stale-statistics.md](patterns/stale-statistics.md) |
| **D3** | `detect_sort_spill_to_disk` | Sort con `Sort Space Type="Disk"` o `sort_method` con `external merge/sort` | 0.95 | [sort-spill-to-disk.md](patterns/sort-spill-to-disk.md) |
| **D4** | `detect_like_leading_wildcard` | Filtro `col ~~ '%...'` (impide índice btree regular) | 0.9 | [like-leading-wildcard.md](patterns/like-leading-wildcard.md) |
| **D5** | `detect_function_in_where` | Función no-immutable (`lower`, `date_trunc`, etc.) sobre la columna en el `Filter` | 0.9 | [function-in-where.md](patterns/function-in-where.md) |
| **D6** | `detect_or_across_tables` | `OR` con lados que referencian tablas/alias distintos en un nodo join | 0.85 | [or-across-tables.md](patterns/or-across-tables.md) |
| **D7** | `detect_correlated_subquery` | Algún nodo con `subplan_name` que contiene `"SubPlan"` (no `InitPlan`) | 0.95 | [correlated-subquery.md](patterns/correlated-subquery.md) |
| **D8** | `detect_nested_loop_large_outer` | `Nested Loop` con outer de >10k filas (debería ser Hash/Merge Join) | 0.8 | [nested-loop-large-outer.md](patterns/nested-loop-large-outer.md) |
| **D9** | `detect_select_star` | `SELECT *` en el SQL del usuario; reporta `index_only_candidate` cruzando con el plan | 0.85 | [select-star.md](patterns/select-star.md) |
| **D10** | `detect_missing_covering_index` | `Index Scan` con ≥50 filas (oportunidad de pasar a `Index Only Scan` vía `INCLUDE`) | 0.7 | [missing-covering-index.md](patterns/missing-covering-index.md) |
| **D11** | `detect_type_mismatch` | `Filter` con notación `((col)::tipo = …)` que invalida el índice btree existente | 0.9 | [type-mismatch.md](patterns/type-mismatch.md) |
| **D12** | `detect_unnecessary_cte_materialize` | `CTE Scan` referenciado una sola vez sin `Recursive Union` en el plan | 0.85 | [unnecessary-cte-materialize.md](patterns/unnecessary-cte-materialize.md) |
| **D16** | `detect_missing_index` | Caso simétrico de C1: Seq Scan ≥100k filas **sin** índice btree | 0.95 | [missing-index.md](patterns/missing-index.md) |
| **D17** | `detect_partial_index_opportunity` | Filtro que mezcla `bool_col` con un predicado sobre otra columna conocida | 0.8 | [partial-index-opportunity.md](patterns/partial-index-opportunity.md) |
| **D18** | `detect_cardinality_misestimate` | Join con ratio plan/actual ≥5× y un scan descendiente con AND ≥2 columnas | 0.85 | [cardinality-misestimate.md](patterns/cardinality-misestimate.md) |
| **D19** | `detect_having_without_aggregate` | `HAVING` sin función de agregación (movible a `WHERE`) — requiere `sql=` | 0.9 | [having-without-aggregate.md](patterns/having-without-aggregate.md) |
| **D20** | `detect_in_subquery_to_exists` | `col IN (SELECT ...)` no correlacionado con señal del plan (Semi Join o Aggregate-bajo-join) — requiere `sql=` | 0.9 | [in-subquery-to-exists.md](patterns/in-subquery-to-exists.md) |
| **D21** | `detect_not_in_nullable_subquery` | `col NOT IN (SELECT inner_col …)` cuando `inner_col` es nullable (bug silencioso) — requiere `sql=` | 0.95 | [not-in-nullable-subquery.md](patterns/not-in-nullable-subquery.md) |
| **D22** | `detect_count_star_full_table` | `count(*)`/`sum`/`avg` sobre tabla ≥100k filas sin `WHERE` (recomienda `pg_class.reltuples`) | 0.95 | [count-star-full-table.md](patterns/count-star-full-table.md) |

> **Cobertura real medida:** 18/20 queries plantadas en AppDB v1 al
> 2026-05-13 (rúbrica del proyecto pide ≥16). Falsos positivos:
> 0/10 sobre queries sanas. Las 2 queries huérfanas (Q05, Q10) no
> son bugs de los detectores; son del seed sintético (un sort que
> cabe en `work_mem` y un ratio plan/actual de 6× bajo el umbral
> 10× de D2). Documentado en `PROGRESS.md` 2026-05-13.

### 4.4. Firmas extendidas (`sql=`)

Cinco detectores aceptan `sql: str | None = None` como
**keyword-only opcional** porque la información estructural relevante
no aparece en el EXPLAIN:

- **D9** — `SELECT *` se resuelve antes del plan; solo el SQL lo trae.
- **D11** — placeholder reservado para validar el tipo del cast
  contra el schema (hoy no se usa).
- **D19** — `HAVING` vs `WHERE` desaparece tras la planificación.
- **D20** — `IN (SELECT ...)` se reescribe internamente; necesitamos
  el SQL para confirmar la forma original.
- **D21** — `NOT IN` vs `NOT EXISTS` desaparece tras la planificación.

Los detectores sin el kwarg no lo aceptan — `backend/orchestrator.py`
detecta esto vía un registro estático `_DETECTORS: list[tuple[código,
fn, accepts_sql]]`. Si añades un detector nuevo que necesita `sql=`,
sigue el patrón keyword-only para no romper la firma estándar.

---

## 5. Recomendador

### 5.1. `Recommendation` (frozen dataclass)

| Campo | Tipo | Descripción |
|---|---|---|
| `kind` | `Literal[…]` | Tipo de acción (ver abajo). |
| `table` | `str` | `"<schema>.<tabla>"`. |
| `column` | `str` | Columna principal. |
| `index_method` | `str` | `"btree"` en v1; `"extended_statistics"` para D18. |
| `index_name` | `str` | Nombre sugerido (`idx_<tabla>_<col>`) o existente. |
| `create_index_sql` | `str` | SQL listo para mostrar. Vacío en `skipped_*`. |
| `justification` | `str` | Explicación textual derivada de stats. |
| `expected_impact` | `str` | Prosa corta del impacto esperado. |
| `selectivity` | `float \| None` | 0..1 si hay stats; `None` si la tabla nunca tuvo `ANALYZE`. |
| `partial_predicate` | `str \| None` | Cláusula `WHERE` del índice parcial (solo `create_partial_index`). |
| `statistics_columns` | `tuple[str, ...] \| None` | Columnas de `CREATE STATISTICS` (solo `create_statistics`). |

**Valores de `kind`:**

| `kind` | Cuándo | Ejemplo de SQL |
|---|---|---|
| `create_index` | Índice btree faltante | `CREATE INDEX idx_posts_author_id ON public.posts (author_id);` |
| `analyze` | El índice ya existe; problema probable son las stats | `ANALYZE public.posts;` |
| `create_partial_index` | Filtro mezcla bool + otra columna (D17) | `CREATE INDEX … ON … (other_col) WHERE bool_col = true;` |
| `create_statistics` | Cardinality misestimate por correlación entre columnas (D18) | `CREATE STATISTICS … ON col1, col2 FROM …;` |
| `skipped_low_selectivity` | Filtro deja pasar >20% de las filas; un btree no ayuda (D13) | _(vacío; ver `justification`)_ |

### 5.2. `recommend(detections, snapshot) -> list[Recommendation]`

Orquestador. Recibe `dict[código_detector → Detection]` y combina las
recomendaciones de **C1, D16, D17, D18** en una lista plana, ordenada
ascendente por código para determinismo.

Los otros 15 detectores **no tienen recomendador formal** — su salida
la consume el backend como `kind="finding"` con prosa derivada de la
evidencia.

```python
from motor import recommend, parse_explain, detect_seq_scan_on_large_table

plan = parse_explain(raw_explain)
detection = detect_seq_scan_on_large_table(plan, snapshot)

recommendations = recommend({"C1": detection}, snapshot)
for rec in recommendations:
    print(rec.kind, rec.create_index_sql, rec.selectivity)
```

### 5.3. Recomendadores per-detector

Cuando necesitas la recomendación de un solo detector (sin pasar por
`recommend()`):

| Función | Para |
|---|---|
| `recommend_for_seq_scan_on_large_table(detection, snapshot, *, min_selectivity=0.2)` | C1 |
| `recommend_for_missing_index(detection, snapshot, *, min_selectivity=0.2)` | D16 |
| `recommend_for_partial_index_opportunity(detection, snapshot)` | D17 (sin filtro D13) |
| `recommend_for_cardinality_misestimate(detection, snapshot)` | D18 (sin filtro D13) |

### 5.4. D13 — filtro de selectividad

El recomendador descarta `create_index` cuando la columna no es lo
suficientemente selectiva. Si la fracción estimada de filas que pasan
el filtro supera `MIN_SELECTIVITY_FOR_INDEX = 0.2` (20%), Postgres
preferiría un Seq Scan a millones de lookups en el índice.

En esos casos el recomendador emite `kind="skipped_low_selectivity"`
con `create_index_sql=""` y la razón en `justification` — útil para
logs y métricas, no se muestra en la UI principal.

**No se aplica** a `analyze`, `create_partial_index` ni
`create_statistics` (sus utilidades no dependen del cardinality del
filtro).

### 5.5. Helpers públicos

- `compute_selectivity(column_stats, estimated_rows) -> float | None`
  — selectividad estimada del filtro de igualdad sobre la columna.
  Pública para que el sandbox, backend y tests puedan reproducir el
  cálculo. `None` si no hay stats.
- `order_columns_by_selectivity(snapshot, table, columns) -> list[str]`
  — ordena por selectividad ascendente (más selectiva primero).
  Útil para índices compuestos y `CREATE STATISTICS`.

---

## 6. Cómo agregar un detector nuevo

La convención está cuajada con C1 (`motor/detectors/seq_scan_on_large_table.py`)
y D16 (mismo shape, predicado inverso, `missing_index.py`). Sigue
estos siete pasos:

### 6.1. Crea el archivo del detector

`motor/detectors/<snake_case_name>.py`:

```python
from motor.detection import Detection
from motor.nodes import find_nodes
from motor.parser import ExplainResult, PlanNode
from conector.types import SchemaSnapshot


def detect_<your_pattern>(
    plan: ExplainResult | PlanNode,
    snapshot: SchemaSnapshot,
) -> Detection:
    """Detector D-N. Una línea sobre qué detecta y por qué importa."""
    matches: list[dict] = []

    for node in find_nodes(plan, "Node Type Aquí"):
        # razonamiento sobre node.<campo>, node.<otro_campo>, snapshot...
        if <tu_predicado>:
            matches.append({
                "table": "<schema>.<tabla>",
                "column": <col>,
                # … hechos crudos relevantes
            })

    return Detection(
        found=bool(matches),
        confidence=<tu_confianza>,   # 0..1; 1.0 si es estructural pura
        evidence={"matches": matches},
    )
```

**Reglas que tu detector debe respetar:**

- **R1:** no consultas al LLM. Estática sobre `plan` y `snapshot`.
- **R2:** opera sobre la estructura del árbol y los atributos tipados
  de `PlanNode`. Regex sobre `node.filter` (texto que emite Postgres,
  estable entre versiones) está permitido; regex sobre el SQL crudo
  del usuario no — para eso usa `sqlglot` y la firma extendida `sql=`.
- **R9:** función pura. Sin I/O, sin red, sin estado global. Cada
  llamada se decide únicamente con los argumentos.
- **R14:** cero literales hardcoded de AppDB. Todo viene del schema/
  plan.

### 6.2. Registra el detector en el módulo

`motor/detectors/__init__.py`:

```python
from motor.detectors.<your_module> import detect_<your_pattern>

__all__ = [
    # …
    "detect_<your_pattern>",
]
```

`motor/__init__.py`: agrega el `from motor.detectors import …` y al
`__all__` del módulo.

### 6.3. Registra el detector en el orquestador

`backend/orchestrator.py`, en la lista `_DETECTORS`:

```python
("D23", detect_<your_pattern>, False),     # accepts_sql=False/True
```

Y añade el nombre humano en `_DETECTOR_NAMES`. Si tiene recomendador
formal, añadir el código a `_CODES_WITH_RECOMMENDER`.

### 6.4. Escribe los tests

`tests/motor/detectors/test_<your_module>.py`:

- **Happy path** (criterio "hecho cuando" del backlog).
- **Negativo** (caso donde NO debe disparar).
- **Frontera con detectores hermanos** (defensa contra solapamiento).
- **Robustez** (input degenerado: `filter=None`, `relation_name=None`,
  snapshot sin la tabla, etc.).

Tests son unit (no requieren AppDB); usa fixtures en
`tests/motor/fixtures/*.json` (planes reales) o sintéticos inline
cuando sirvan mejor.

### 6.5. Documenta el patrón

`docs/patterns/<your-pattern>.md` siguiendo la plantilla del catálogo
(`docs/patterns/README.md` — sección "Plantilla").

### 6.6. Actualiza el índice del catálogo

Marca la fila correspondiente en `docs/patterns/README.md` como
✅ Implementado y enlaza al archivo `.md` que acabás de crear.

### 6.7. Actualiza este doc

Añade una fila al catálogo de la sección 4.3 con el código nuevo y el
enlace al patrón.

---

## 7. Reglas que el motor respeta

| Regla | Cómo se aplica en `/motor` |
|---|---|
| **R1** — Motor decide, LLM explica | Cero llamadas al LLM en el módulo. Los detectores son funciones puras Python; las decisiones se toman antes de que cualquier prosa se genere. |
| **R2** — Estructura, no strings | Detección sobre el árbol de `PlanNode` y atributos tipados. Regex sobre `node.filter`/`node.index_cond` (texto de Postgres) permitido y documentado en cada detector. Regex sobre SQL crudo solo dentro de detectores con `sql=` y mediado por `sqlglot`. |
| **R9** — Funciones puras | Sin I/O, sin red, sin estado global. Tests deterministas con fixtures versionados. |
| **R10** — Tests con cada feature | Cada detector incluye happy path, negativo, frontera con hermanos y robustez. Sin tests no se mergea. |
| **R14** — Cero hardcoded | Nombres de tabla/columna vienen del `snapshot`/`plan`. El bonus de AppDB v2 depende de esto. |

---

## 8. Tests

Viven en `tests/motor/`:

| Archivo | Cobertura |
|---|---|
| `test_parser.py` | Formas de entrada de `parse_explain`, estructura del árbol, EXPLAIN sin ANALYZE, errores claros. |
| `test_parser_node_types.py` | Los 17 tipos de nodo aparecen en al menos un fixture y exponen sus campos específicos correctamente. |
| `test_find_nodes.py` | DFS pre-order, formas de entrada (`PlanNode`/`ExplainResult`, `str`/iterable), casos negativos. |
| `tests/motor/detectors/test_<name>.py` | Un archivo por detector — 19 archivos en total. |
| `tests/motor/fixtures/*.json` | 12 planes reales de AppDB v1 + 1 sintético. Documentados en `fixtures/README.md`. |

**Cómo correrlos** (no requieren Docker — fixtures versionados):

```bash
pip install -r requirements.txt
pytest tests/motor
pytest tests/motor -v          # más verbose
pytest tests/motor/detectors   # solo detectores
```

Ningún test del motor está marcado con `@pytest.mark.integration` —
todo es unit. Esto es deliberado: los detectores son funciones puras
y mantener tests rápidos sin Postgres es más sano.

---

## 9. Limitaciones conocidas (transversales)

Las limitaciones específicas de cada detector están en su archivo de
patrón. Estas son las que afectan al motor entero:

- **Resolución de tabla por sufijo de schema.** El plan trae
  `Relation Name = "posts"` (sin schema). Los detectores buscan en
  el snapshot el primer key que termine en `.posts`. Si en el futuro
  hay homónimos (`public.posts` y `archive.posts`), el detector
  elige por orden de iteración. Solución: capturar `Schema` en
  `PlanNode` (no aparece hoy en planes de AppDB v1).
- **Regex sobre `node.filter` para extraer columnas.** Los detectores
  que necesitan la columna del filtro extraen la primera con un
  regex monocolumna. Filtros tipo `((col1 = 1) AND (col2 = 2))` solo
  reportan `col1`. Aceptable en AppDB v1 (queries plantadas son
  monocolumna). Solución cuando importe: parsear con `sqlglot`.
- **Los detectores no miden impacto, reportan presencia.** La
  cuantificación (cuántas filas se ahorran, cuánto baja el costo)
  vive en el sandbox (`sandbox/validator.py`) y en la prosa del LLM,
  no en el motor.
- **El parser ignora silenciosamente campos nuevos de Postgres.** Si
  una versión futura introduce un campo en EXPLAIN que no está en
  `PlanNode`, queda fuera. Mitigación: pinneamos Postgres 16 vía
  `docker-compose.yml`; añadir un campo es trivial.
- **No hay agregación entre detectores.** Si C1 y D9 disparan ambos
  sobre la misma query, son detecciones independientes. La
  priorización y deduplicación viven en el orquestador del backend.

---

## 10. Cómo extender (otros caminos)

Más allá de "añadir un detector":

- **Soporte para un nuevo tipo de nodo** (ej. `Hash SetOp`): agregar
  campos relevantes a `PlanNode` en `parser.py` como `Optional[X] =
  None`, mapearlos en `_parse_node` con `node.get("Title Case")`,
  sumar el tipo a `KNOWN_NODE_TYPES` y a algún fixture de test.
- **Subclases por tipo de nodo:** descartado deliberadamente (ver
  `PROGRESS.md` 2026-05-09 "Subclases por tipo de nodo descartadas").
  El boilerplate de 16+ subclases no justifica la ganancia
  marginal en type-checking.
- **Detección sobre estadísticas extendidas (`pg_statistic_ext`):**
  hoy `D18` reportan presencia pero no leen MCF/correlación
  cruzada. Cuando el conector las exponga
  (`pg_restore_attribute_stats` en sandbox PG18), añadir
  cross-checks en D17/D18.
- **Detección cross-query (workload-aware):** hoy un detector analiza
  un plan a la vez. Si `/workload` empieza a ofrecer el top-N de
  pg_stat_statements, un detector "índice candidato a varias queries"
  podría vivir aquí leyendo varios planes — la firma actual seguiría
  funcionando llamándolo en loop.

---

## 11. Referencias

- **Código fuente:** [`motor/`](../motor/) en la raíz del repo.
- **Notas internas para mantenedores:**
  [`motor/CLAUDE.md`](../motor/CLAUDE.md).
- **Catálogo de patrones** (uno por detector):
  [`docs/patterns/`](patterns/).
- **Decisiones técnicas:** `PROGRESS.md` — entradas relevantes
  2026-05-09 (parser, find_nodes), 2026-05-10 (D13 selectividad),
  2026-05-12 (D17/D18), 2026-05-13 (D19-D22 + fix D2 bajo LIMIT +
  fix D20 forma real Q17).
- **Doc del conector** (snapshot, garantías read-only):
  [`docs/conector.md`](conector.md).
- **Doc del sandbox** (validación de recomendaciones C3):
  `sandbox/CLAUDE.md` por ahora; doc externo pendiente.
- **Reglas del proyecto** (R1, R2, R9, R10, R14):
  [`RULES.md`](../RULES.md) en la raíz del repo.

Si encuentras algo confuso o falta documentar un detector, abrí un
issue en el repo de PgPilot.

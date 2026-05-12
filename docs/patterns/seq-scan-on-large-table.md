# Seq Scan sobre tabla grande con índice disponible

> **Detector:** `motor.detect_seq_scan_on_large_table` (C1)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 1.0 (determinístico)

## Problema

Postgres está leyendo una tabla grande (≥100k filas) de principio a
fin con un `Seq Scan`, aun cuando existe un índice btree sobre la
columna del filtro `WHERE`. Cada query así toca todas las páginas de
la tabla en lugar de unas pocas hojas del índice — el costo de I/O y
la latencia P99 se disparan, y el planner suele elegir este camino
cuando las estadísticas del optimizador están desactualizadas, cuando
el `random_page_cost` está mal calibrado, o cuando el filtro es lo
suficientemente poco selectivo como para que el planner crea que el
Seq Scan es más barato (a veces erróneamente).

Este es uno de los anti-patterns más comunes en Postgres en
producción y el primero que PgPilot detecta porque casi siempre tiene
una recomendación accionable: o el índice está mal calibrado en stats
(`ANALYZE`) o no es tan útil como creímos al crearlo (lo cual también
es información valiosa).

## Cómo aparece en el plan

El detector busca en el árbol del `EXPLAIN (ANALYZE, BUFFERS, FORMAT
JSON)` nodos `Seq Scan` cuya tabla escaneada cumpla:

- Tiene `≥ 100_000` filas estimadas (vía `pg_class.reltuples`,
  capturado en el snapshot del conector).
- Tiene un índice btree cuya **primera** columna coincide con la
  columna del filtro `WHERE` del nodo (un índice `(a, b)` no
  acelera `WHERE b = X` — así funciona el planner).

La columna del filtro se extrae del campo `Filter` del nodo (texto
generado por Postgres, estable). Esto cumple R2 de `RULES.md`: la
detección opera sobre la estructura del plan, no sobre el SQL crudo.

## Regla de detección

Pseudocódigo (mapea 1:1 contra
`motor/detectors/seq_scan_on_large_table.py`):

```
para cada nodo Seq Scan en el plan:
    si node.relation_name es None: skip
    resolver "<schema>.<tabla>" en snapshot.sizes
    si no se encuentra: skip
    si estimated_rows < 100_000: skip
    column = primera_columna_del_filtro(node.filter)
    si column es None: skip
    si NO existe índice btree con primera_columna == column: skip   # frontera con D16
    matches.append({table, column, estimated_rows, index_name, filter, ...})

devolver Detection(found=bool(matches), confidence=1.0, evidence={"matches": matches})
```

Constantes y helpers documentados en
`/motor/detectors/seq_scan_on_large_table.py` (`LARGE_TABLE_MIN_ROWS`,
`_FILTER_COLUMN_RE`, `_has_btree_index_on_column`).

## Recomendación

El recomendador `motor.recommend_for_seq_scan_on_large_table` traduce
cada match a una `Recommendation`:

- **Caso normal — índice existe pero el planner lo ignora:** emite
  `kind="analyze"` con SQL `ANALYZE <schema>.<tabla>;`. La hipótesis
  del producto es que las estadísticas que usa el planner están
  desactualizadas: refrescarlas suele ser suficiente para que vuelva
  a elegir el `Index Scan`. Justificación apuntando al índice
  existente y a la selectividad estimada.

(Cuando el índice **no** existe, ese caso lo cubre el detector
hermano D16 con `kind="create_index"` y SQL
`CREATE INDEX idx_<tabla>_<col> ON <tabla> (<col>);`. Frontera
explícita: C1 nunca emite `create_index` para mantener la separación
de diagnósticos.)

La selectividad reportada en `Recommendation.selectivity` se computa
desde `pg_stats`:

- `n_distinct > 0` → `selectividad ≈ 1 / n_distinct`
- `n_distinct < 0` → `selectividad ≈ -n_distinct` (convención
  Postgres: negativo = ratio respecto a las filas totales)
- Sin stats → `None` y la justificación lo declara explícito.

## Validación

Antes de mostrar la recomendación al usuario:

- **Sandbox (`sandbox.validate_index_recommendation`):** corre el
  `EXPLAIN` de la query original, ejecuta el `ANALYZE` (o
  `CREATE INDEX` para D16), y vuelve a correr el `EXPLAIN`. Verifica
  con `sandbox.verdict_from_plans` que el costo bajó y/o el planner
  cambió de `Seq Scan` a `Index Scan`/`Bitmap Heap Scan`. Si el
  sandbox no está disponible, el verdict queda en `null` y la
  recomendación se sigue mostrando como informativa (R5).
- **LLM (`/ia/cross_validator.py`):** la prosa explicativa generada
  por el LLM se valida cruzando con el snapshot. Si el LLM menciona
  una columna o índice que no existe, la sugerencia se descarta y
  se cae a la plantilla determinística (`/ia/templates.py`). Esto
  cumple R3.

## Falsos positivos conocidos

Documentados también en `/motor/CLAUDE.md` como limitaciones del
detector (sección `detect_seq_scan_on_large_table`):

- **(D1) Resolución de tabla por sufijo.** El plan trae
  `Relation Name: "posts"` sin schema; el detector resuelve al primer
  key del snapshot que termine en `.posts`. Para AppDB v1 (todo en
  `public`) no aplica; ante homónimos (`public.posts` y
  `archive.posts`) la elección depende del orden de iteración. Mitigar
  capturando `Schema` en `PlanNode` cuando importe.
- **(D2) Filtro multi-columna.** El detector toma la primera columna
  del filtro vía regex (`_FILTER_COLUMN_RE`). Un filtro como
  `((likes_count > 950) AND (created_at > ...))` con índice solo
  sobre `created_at` queda **no detectado**. La medición empírica
  (`scripts/measure_c1_coverage.py`, 2026-05-11) capturó este caso
  como FN en Q15. Mitigar parseando `node.filter` con `sqlglot` y
  buscando todas las columnas con índice utilizable.
- **Filtros que no matchean el regex** (`LIKE`, `IS NULL`, casts
  `((col)::tipo)`): el detector se abstiene por diseño. Falso negativo
  voluntario — prefiere callarse a recomendar mal.
- **Tabla pequeña (<100k filas):** ignorada por diseño. Sobre tablas
  pequeñas el `Seq Scan` suele ser óptimo (lectura secuencial barata,
  cache caliente).

## Ejemplo de query

Sobre AppDB v1 (sin las stats apropiadas / con un índice que el
planner descarta):

```sql
SELECT id, title, body
FROM posts
WHERE created_at > '2024-01-01';
```

`posts` tiene ~500k filas y existe `idx_posts_created_at`. Si el
planner elige `Seq Scan` (típicamente porque las estadísticas están
viejas o `random_page_cost` mal calibrado), C1 dispara.

## Ejemplo de plan

Fragmento de `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`:

```json
{
  "Plan": {
    "Node Type": "Seq Scan",
    "Parallel Aware": false,
    "Relation Name": "posts",
    "Alias": "posts",
    "Startup Cost": 0.00,
    "Total Cost": 12543.50,
    "Plan Rows": 124850,
    "Plan Width": 312,
    "Actual Startup Time": 0.020,
    "Actual Total Time": 187.443,
    "Actual Rows": 124820,
    "Actual Loops": 1,
    "Filter": "(created_at > '2024-01-01'::date)",
    "Rows Removed by Filter": 375180
  },
  "Planning Time": 0.412,
  "Execution Time": 198.110
}
```

Lo que C1 evalúa de este nodo:

- `Node Type == "Seq Scan"` ✓
- `Relation Name == "posts"` → resuelve `"public.posts"`
- `sizes["public.posts"].estimated_rows` = 500_000 ≥ 100_000 ✓
- `_column_from_filter("(created_at > '2024-01-01'::date)")` →
  `"created_at"` ✓
- `schema["public.posts"].indexes` contiene un btree
  `idx_posts_created_at` con `columns[0] == "created_at"` ✓
- ⇒ `Detection(found=True, confidence=1.0, evidence={"matches": [...]})`

## Tests

`tests/motor/detectors/test_seq_scan_on_large_table.py`. Cubre:

- Happy path: Seq Scan + tabla grande + índice btree presente sobre
  la columna del filtro → dispara con confianza 1.0.
- Negativo (frontera con D16): mismo plan pero sin índice → no
  dispara (lo cubrirá D16 con `create_index`).
- Negativo (tabla pequeña): Seq Scan sobre tabla con `<100k` filas →
  no dispara.
- Negativo (filtro no parseable): `Filter: "col IS NULL"` → no
  dispara.
- Robustez: `relation_name=None`, `filter=None`, snapshot sin la
  tabla → no levanta excepción, devuelve `found=False`.

## Referencias

- `/motor/detectors/seq_scan_on_large_table.py` (implementación)
- `/motor/recommender.py` (`recommend_for_seq_scan_on_large_table`)
- `/motor/CLAUDE.md` (sección "detect_seq_scan_on_large_table" con
  decisiones del módulo y limitaciones)
- `/sandbox/CLAUDE.md` (validación con `validate_index_recommendation`
  y `verdict_from_plans`)
- Backlog `C1` en `/PgPilot_Backlog.md`
- Medición empírica de cobertura: `scripts/measure_c1_coverage.py`
  (entrada de PROGRESS.md del 2026-05-11)

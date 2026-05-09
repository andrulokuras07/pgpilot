# motor — parser de EXPLAIN, detectores y recomendador

## Propósito

`/motor` es el cerebro determinístico de PgPilot. Recibe el output de
Postgres (`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`) y la metadata
del schema (de `/conector`), y produce:

1. Un árbol estructurado del plan (B7+B8) que reemplaza el JSON crudo.
2. Helpers para navegar el árbol (B9 — `find_nodes`).
3. *(próximo)* Detectores de anti-patterns que operan sobre el árbol.
4. *(próximo)* Recomendador de índices.

**Lo que NO hace este módulo:**
- No habla con el LLM (eso vive en `/ia`).
- No conecta a la BD (eso vive en `/conector`).
- No ejecuta queries en sandbox (eso vive en `/sandbox`).
- No serializa output al frontend (eso vive en `/backend`).

**Regla #1 vigente aquí (ver `RULES.md` R1+R2):** los detectores
deciden sobre la estructura del árbol, no sobre el texto del SQL ni
del EXPLAIN. Cualquier código que haga `if "Seq Scan" in raw_output`
está prohibido.

## API pública

Exportada desde `motor/__init__.py`:

### `parse_explain(raw) -> ExplainResult`
Convierte el output de `EXPLAIN (FORMAT JSON)` en un árbol propio.
Acepta tres formas de entrada para evitar boilerplate:

- `str` con el JSON crudo (ej. `psql -tAq` o `cur.fetchone()[0]` cuando
  Postgres devuelve string).
- `list[dict]` (forma típica al hacer `cur.execute().fetchone()[0]`;
  Postgres siempre envuelve EXPLAIN en una lista de un elemento).
- `Mapping` (un entry suelto, útil en tests con fixtures cargados con
  `json.load`).

Devuelve `ExplainResult(root, planning_time_ms, execution_time_ms)`.
Lanza `ValueError` con mensaje claro si la estructura no contiene un
nodo `Plan`. Propaga `json.JSONDecodeError` si el string no es JSON.

### `ExplainResult` (frozen dataclass)
- `root: PlanNode` — raíz del árbol del plan.
- `planning_time_ms: float | None` — `None` cuando se corrió EXPLAIN
  sin ANALYZE.
- `execution_time_ms: float | None` — idem.

### `PlanNode` (frozen dataclass)
Un nodo del plan. Inmutable (`frozen=True`) para impedir mutaciones
accidentales en los detectores. Atributos:

**Comunes a todo nodo:**
- `node_type: str` — tal cual viene de Postgres (`"Seq Scan"`,
  `"Index Scan"`, etc.).
- `startup_cost: float`, `total_cost: float`
- `plan_rows: int`, `plan_width: int`
- `actual_startup_time | actual_total_time: float | None`
- `actual_rows: int | None`, `actual_loops: int | None`

**Identidad de la relación escaneada:**
- `relation_name`, `alias`, `parent_relationship`

**Específicos por tipo de nodo (todos `Optional`):**
- Scan: `index_name`, `index_cond`, `recheck_cond`, `filter`,
  `rows_removed_by_filter`, `rows_removed_by_index_recheck`,
  `scan_direction`, `heap_fetches`
- Joins: `join_type`, `inner_unique`, `hash_cond`, `merge_cond`
- Sort: `sort_key` (tupla), `sort_method`, `sort_space_type`,
  `sort_space_used`
- Aggregate: `strategy`, `partial_mode`, `group_key` (tupla)
- CTE/Subquery: `cte_name`, `subplan_name`
- Hash: `hash_buckets`, `hash_batches`, `peak_memory_kb`
- Paralelismo: `parallel_aware`, `workers_planned`, `workers_launched`

**Jerarquía:**
- `children: tuple[PlanNode, ...]` — tupla, no lista, para preservar
  inmutabilidad y permitir `__hash__`.

Si Postgres no envía un campo, queda en `None` (nunca se inventa). Si
EXPLAIN se corrió sin `ANALYZE`, todos los `actual_*` son `None`.

### `find_nodes(tree, node_type) -> list[PlanNode]`
Recorre el árbol en DFS pre-order y devuelve todos los nodos cuyo
`node_type` matchea. Acepta:

- `tree`: un `PlanNode` o un `ExplainResult` (en el segundo caso
  recorre desde `result.root`).
- `node_type`: `str` (match exacto) o cualquier iterable de `str`
  (match si está en la colección).

Devuelve lista vacía si no hay matches; nunca lanza por "no
encontrado". Es la primitiva sobre la que cualquier detector futuro
opera (R2: estructura, no strings).

### `KNOWN_NODE_TYPES: frozenset[str]`
Los 17 tipos de nodo que el parser ha visto en AppDB:

```
Seq Scan, Index Scan, Index Only Scan,
Bitmap Heap Scan, Bitmap Index Scan,
Nested Loop, Hash Join, Merge Join,
Sort, Hash, Aggregate, Limit,
Subquery Scan, CTE Scan, Materialize,
Gather, Gather Merge
```

No es una lista cerrada: el parser acepta cualquier `Node Type` que
Postgres emita (incluyendo `BitmapOr`, `Recursive Union`,
`WorkTable Scan` y futuros). Esta constante existe para validar
cobertura en tests y para documentar contra qué se han escrito
detectores.

### Uso típico

```python
from motor import find_nodes, parse_explain

# 1. ejecutar EXPLAIN contra el conector
with pool.connection() as conn:
    cur = conn.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + user_query
    )
    raw = cur.fetchone()[0]   # list[dict]

# 2. parsear
result = parse_explain(raw)
print(result.execution_time_ms, "ms")
print(result.root.node_type)

# 3. buscar nodos por tipo (base de los detectores)
seq_scans = find_nodes(result, "Seq Scan")
joins = find_nodes(result, ("Hash Join", "Merge Join", "Nested Loop"))
```

## Estructura interna

```
motor/
├── __init__.py     # exporta API pública del módulo
├── parser.py       # PlanNode, ExplainResult, parse_explain (B7+B8)
├── nodes.py        # find_nodes, KNOWN_NODE_TYPES (B9)
└── CLAUDE.md       # este archivo
```

A medida que B17+ aterricen, se sumarán:
- `detectors/` — un archivo por anti-pattern (ej.
  `detect_seq_scan_on_large_table.py`)
- `recommender.py` — generador de candidatos a índice
- `detection.py` — el dataclass `Detection(found, confidence, evidence)`

## Cómo extender

### Agregar soporte para un nuevo tipo de nodo
1. Si el JSON trae campos nuevos relevantes, agregarlos al `dataclass`
   `PlanNode` en `parser.py` como `Optional[X] = None`.
2. Mapearlos en `_parse_node` con `node.get("Nombre Title Case")`.
3. Sumar el tipo a `KNOWN_NODE_TYPES` en `nodes.py`.
4. Agregar (idealmente) un fixture real en `tests/motor/fixtures/`
   o un fixture sintético si Postgres no lo elige naturalmente con
   AppDB.
5. Agregar un test en `tests/motor/test_parser_node_types.py` que
   verifique los campos específicos.

### Agregar un detector
*(Pendiente: la convención formal sale en B17. Borrador:)*
1. Un archivo nuevo en `motor/detectors/` con función pura
   `detect_X(plan: ExplainResult, schema: dict, sizes: dict) -> Detection`.
2. La función usa `find_nodes` para localizar nodos sospechosos y
   compara contra el schema/stats.
3. Devuelve `Detection(found, confidence, evidence)`.
4. Test "happy path" + test "negativo" (caso donde NO debe disparar)
   en `tests/motor/detectors/`.
5. Registrar el detector en algún index del `motor/__init__.py`.

## Decisiones específicas del módulo

- **Parser construye estructura tipada, no guarda el JSON crudo.** El
  backlog (B7) lo dice explícito: "NO basta con guardar el JSON crudo".
  Cada campo relevante vive como atributo nombrado en `PlanNode`. Si
  un campo nuevo aparece en una versión futura de Postgres, hay que
  agregarlo al dataclass — el parser lo ignora silenciosamente hoy.
- **`PlanNode` es `frozen=True`.** Los detectores son funciones puras
  (R9): inmutabilidad por construcción evita bugs por mutación
  accidental. El costo es que para "mutar" un nodo en tests hay que
  reconstruirlo, lo cual también es deseable.
- **`children` es `tuple` en lugar de `list`.** Inmutable por
  construcción y permite `__hash__` si en el futuro queremos cachear
  resultados de detección por subárbol.
- **`find_nodes` devuelve lista, no generador.** Los detectores
  típicamente cuentan, intersectan o iteran varias veces sobre los
  matches; un generador se consume una sola vez. Lista es más
  ergonómica.
- **`find_nodes` recorre DFS pre-order.** Determinista, replicable en
  tests, intuitivo: un Seq Scan listado antes que otro corresponde a
  estar más arriba/a la izquierda en el árbol.
- **El parser no falla por campos faltantes**, solo por el faltante
  duro de `Plan` o `Node Type`. Esto tolera EXPLAIN sin ANALYZE
  (todos los `actual_*` quedan en `None`) y emisiones sutilmente
  distintas entre versiones de Postgres.
- **`Sort Key` y `Group Key` se serializan como `tuple[str, ...]`.**
  En el JSON vienen como listas; convertirlas a tupla preserva la
  inmutabilidad del nodo.
- **Tests son unit (no requieren AppDB corriendo).** Los fixtures
  JSON están versionados en `tests/motor/fixtures/`, junto con un
  `README.md` que documenta qué query produjo cada uno y cómo
  regenerarlos.

## Tests

Viven en `tests/motor/`:
- `test_parser.py`: cobertura del parser (B7) — formas de entrada,
  estructura de árbol, jerarquía padre-hijo, EXPLAIN sin ANALYZE,
  errores claros.
- `test_parser_node_types.py`: cobertura B8 — los 16 tipos de nodo
  requeridos aparecen en al menos un fixture y exponen sus campos
  específicos correctamente.
- `test_find_nodes.py`: cobertura B9 — encuentra todos los Seq Scan
  en plan complejo (criterio explícito del backlog), formas de
  entrada, orden DFS, casos negativos.
- `fixtures/*.json`: 12 planes reales de AppDB v1 + 1 fixture
  sintético (`13_materialize.json`). Documentados en
  `fixtures/README.md`.

**Cómo correrlos:**
```bash
# Todo (no requiere AppDB; los fixtures están versionados)
pip install -r requirements.txt
pytest tests/motor

# Más verbose
pytest tests/motor -v
```

Ningún test del módulo motor requiere `@pytest.mark.integration`
(diferente al conector). Esto es a propósito: el parser y find_nodes
son funciones puras, y mantener tests rápidos sin dependencias
externas es más sano.

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

### `Detection` (frozen dataclass)
Resultado común de todos los detectores. Campos:
- `found: bool` — True si el anti-pattern se detectó al menos una vez.
- `confidence: float` — en [0, 1]. C1 emite 1.0 (detección determinística).
- `evidence: dict` — abierto. Convención: `evidence["matches"]` es
  `list[dict]` con un entry por ocurrencia.

### `detect_seq_scan_on_large_table(plan, snapshot) -> Detection`
Detector C1. Dispara cuando hay un `Seq Scan` sobre una tabla con
≥100k filas (`sizes[t].estimated_rows`) y existe un índice btree
cuya primera columna coincide con la columna del filtro `WHERE` del
nodo. Cada match en `evidence["matches"]` incluye `table`, `column`,
`estimated_rows`, `rows_removed_by_filter`, `index_name`, `filter`.

### `detect_stale_statistics(plan, snapshot) -> Detection`
Detector D2. Dispara sobre nodos scan (`Seq Scan`, `Index Scan`,
`Index Only Scan`, `Bitmap Heap Scan`) cuya razón `plan_rows` vs
`actual_rows` supera `STALE_STATS_RATIO = 10.0` en cualquier
dirección. Requiere EXPLAIN ANALYZE (sin `actual_rows` no hay
comparación). Caso especial: `actual_rows == 0` con
`plan_rows > UMBRAL` cuenta como overestimación total. Cada match
incluye `table`, `node_type`, `plan_rows`, `actual_rows`, `ratio`
(redondeado a 2 decimales), `direction` (`overestimated` /
`underestimated`) y `suggested_sql` (`ANALYZE <table>;`). Confianza
0.85 (heurístico: el ratio identifica el síntoma pero no demuestra
causalidad). Frontera con D18: D2 dispara solo en scans; el error de
cardinalidad en *joins* causado por correlación entre columnas es
competencia de D18, que recomienda `CREATE STATISTICS` multi-columna.

**Fix 2026-05-13 (scan bajo LIMIT):** D2 ahora propaga un flag
`under_limit` mientras recorre el plan y se abstiene en scans cuyo
ancestro es un nodo `Limit`. Postgres push-down detiene el scan
cuando el LIMIT está saciado, así que `actual_rows` refleja el cap
del LIMIT, no el universo real de filas que match'ean. Comparar
`plan_rows` contra ese valor truncado producía FP en queries sanas
como `SELECT … FROM tags ORDER BY x LIMIT 10` (S05 de la suite
anti-FP). El recorrido usa un walker propio en vez de `find_nodes`
para llevar el contexto del LIMIT (PlanNode es frozen, sin punteros
al padre).

### `detect_sort_spill_to_disk(plan, snapshot) -> Detection`
Detector D3. Dispara en nodos `Sort` con `sort_space_type == "Disk"`
(campo authoritativo emitido por Postgres). Fallback defensivo: si por
algún motivo la versión de Postgres omite `Sort Space Type`, también
dispara cuando `sort_method` contiene `"external merge"` o
`"external sort"` (case-insensitive). Cada match incluye `sort_key`,
`sort_method`, `sort_space_type`, `sort_space_used_kb`, `plan_rows`,
`actual_rows`, `suggested_set_work_mem_sql` (`SET work_mem = '<N>MB';`
dimensionado a 2x lo usado, default 64MB) y `suggested_create_index_sql`
sobre la primera columna del sort_key cuando es parseable como
`tabla.col` o `schema.tabla.col`; si la sort key es una expresión
(`lower(name)`, etc.), el campo queda en `None` y la decisión del
índice funcional la toma el recomendador. Confianza 0.95 (estructural).

**Limitaciones conocidas:**

- **(D1) Schema implícito en la resolución de tabla.** El plan trae
  `Relation Name = "posts"` (sin schema). La búsqueda contra el
  snapshot toma el primer key que termine en `.posts`, así que si en
  el futuro hay homónimos (`public.posts` y `archive.posts`) el
  detector elige por orden de iteración. Para AppDB v1 no aplica
  (todo está en `public`). Solución cuando importe: capturar `Schema`
  en `PlanNode` y usarlo aquí.
- **(D2) Columna del filtro = primera coincidencia del regex.** El
  detector extrae la primera columna que aparece en `node.filter`
  (`(col = X)`). Si el filtro es `((col1 = 1) AND (col2 = 2))` y el
  índice está sobre `col2`, C1 NO dispara. En AppDB v1 todas las
  queries plantadas son filtros monocolumna, así que no quema; cuando
  lo haga, la solución limpia es parsear `node.filter` con `sqlglot`
  (ya está en el stack del proyecto) y buscar todas las columnas
  con índice utilizable.
- El detector se abstiene ante filtros que no matchean su regex
  simple (`LIKE`, `IS NULL`, casts `((col)::tipo)`). Falso negativo
  por diseño: prefiere no recomendar a recomendar mal.

### `detect_like_leading_wildcard(plan, snapshot) -> Detection`
Detector D4. Dispara cuando un nodo scan (`Seq Scan`, `Bitmap Heap
Scan`, `Bitmap Index Scan`) tiene un filtro `col ~~ '%...'` — patrón
generado por Postgres a partir de `column LIKE '%texto'`. El wildcard
al inicio impide el uso de índices btree regulares. Inspecciona
`node.filter`, `node.recheck_cond` e `node.index_cond`. Cada match en
`evidence["matches"]` incluye `table`, `column`, `filter`,
`node_type`. Confianza 0.9.

**Limitaciones conocidas:**
- El regex `_LIKE_LEADING_WILDCARD_RE` matchea `\w+` para la columna,
  por lo que no captura columnas entrecomilladas (`"weird name"`) ni
  con caracteres especiales. Para AppDB v1 está OK.
- Solo detecta el operador `~~` (forma interna de `LIKE`). Si en
  algún plan apareciera `~~*` (ILIKE) también debería disparar; vale
  añadirlo cuando lo encontremos en AppDB v2.

### `detect_function_in_where(plan, snapshot) -> Detection`
Detector D5. Dispara cuando un nodo scan tiene en `node.filter` una
llamada a función típicamente no-immutable (`lower`, `upper`, `trim`,
`btrim`, `coalesce`, `concat`, `replace`, `substring`, `left`,
`right`, `reverse`, `length`, `date_trunc`, `extract`, `to_char`,
`to_date`, `to_timestamp`, `to_number`, `abs`, `ceil`, `floor`,
`round`, `trunc`, `regexp_replace`, `regexp_match`). Estas funciones
sobre la columna impiden uso de índices btree planos; el detector
sugiere índice funcional. Cada match incluye `table`, `function`,
`filter`, `node_type`. Confianza 0.9.

**Limitaciones conocidas:**
- **Falso positivo si la función se aplica sobre un literal**
  (`name = lower('X')`). La función ahí es inmutable, no impide
  índice. Mitigación pendiente: parsear `node.filter` con `sqlglot`
  y verificar que el argumento sea una columna, no un literal.
- **Falso positivo si una columna se llama exactamente como una
  función** (`lower TEXT` en una tabla custom). En AppDB v1 no
  ocurre. Mitigación: el mismo parseo con sqlglot lo distinguiría.
- La lista de funciones es cerrada (no consulta `pg_proc`).
  Funciones custom marcadas como `VOLATILE` o `STABLE` que también
  rompen índices no se detectan. Aceptable para el alcance del
  producto.

### `detect_or_across_tables(plan, snapshot) -> Detection`
Detector D6. Dispara cuando `node.filter` de un nodo join
(`Nested Loop`, `Hash Join`, `Merge Join`) — o, defensivamente, de un
`Seq Scan` — contiene un `OR` cuyos lados referencian columnas
calificadas por tablas/alias distintos (`t1.col OR t2.col`). Este
patrón impide el uso de índices en cualquiera de las tablas y suele
reescribirse como `UNION`. Cada match incluye `tables` (lista
ordenada de alias/tablas implicados), `filter`, `node_type`.
Confianza 0.85.

**Limitaciones conocidas:**
- **Heurística por regex `\w+\.\w+`:** asume `table.column` o
  `alias.column`. Si la query usa `schema.tabla.col`, el regex
  captura `schema.tabla`. En AppDB v1 (todo `public`) no aplica.
- **No detecta `OR` cruzando tablas sin calificador** (`status = 1
  OR category = 'x'` sin prefijo). Por diseño: sin prefijo no hay
  evidencia estructural de cruce, podrían ser dos columnas de la
  misma tabla. Falso negativo voluntario.
- El detector reporta los alias tal cual aparecen en el filtro, no
  las tablas físicas. Si el frontend necesita la tabla real, debe
  cruzar con la metadata del plan.

### `detect_missing_index(plan, snapshot) -> Detection`
Detector D16. Caso simétrico de C1: dispara cuando hay un `Seq Scan`
sobre una tabla ≥100k filas, con `Filter` cuya columna se puede
inferir, y NO existe un índice btree apuntable. Es la frontera
explícita de C1: el mismo regex de columna, el mismo umbral de
tamaño, el mismo helper de resolución de tabla — pero el predicado
de índice invertido. Recomendación natural: `CREATE INDEX`. Cada
match incluye `table`, `column`, `estimated_rows`, `filter`,
`suggested_index_name`, `suggested_sql`. Confianza 0.95.

**Limitaciones conocidas:**
- Comparte las limitaciones D1/D2 de C1 (resolución de tabla por
  primer match de sufijo; columna del filtro = primer match del
  regex monocolumna).
- No mira selectividad real. Una columna con 3 valores distintos en
  10M filas no debería indexarse — D13 (recomendador con stats) hará
  ese filtrado antes de mostrar la recomendación.
- Sin filtro inferible, NO dispara (frontera con D22, que cubre
  `count(*)` sin WHERE).

### `detect_partial_index_opportunity(plan, snapshot) -> Detection`
Detector D17. Dispara sobre nodos scan (`Seq Scan`, `Bitmap Heap
Scan`, `Bitmap Index Scan`, `Index Scan`, `Index Only Scan`) cuyo
filtro mezcla un predicado booleano con un predicado sobre otra
columna conocida. Reconoce tres formas del booleano que emite
Postgres: `NOT col`, `col = true|false`, `col IS TRUE|FALSE`.
Recomendación: `CREATE INDEX … (other_col) WHERE bool_col = valor`.
Cada match incluye `table`, `column` (la no-bool), `bool_column`,
`bool_value`, `filter`, `node_type`, `suggested_index_name`,
`suggested_sql`. Confianza 0.8.

**Limitaciones conocidas:**
- **No mira `most_common_freqs`.** Si la distribución del bool es
  ~50/50 el índice parcial no ahorra, pero D17 igual dispara. La
  mitigación pendiente es extender B4 (conector) para capturar MCF
  y filtrar matches con frecuencia cercana a 0.5; mientras tanto el
  recomendador y/o sandbox descartan los casos sin ganancia real.
- **Heurística de "otra columna":** se toma el primer identificador
  del texto del predicado que coincida con una columna del schema y
  no sea la bool. Si hay varios candidatos, se elige el primero por
  orden de aparición. Aceptable para AppDB v1.
- **Falso positivo si la bool aparece en literales:** un filtro como
  `nombre = 'NOT read'` (string raro) no llegaría aquí porque el
  regex `\bNOT\s+\w+` requiere bordes de palabra y la validación
  contra `bool_cols` filtra falsos matches. Pero queda registrado
  como riesgo si en el futuro hay strings con palabras reservadas.

### `detect_having_without_aggregate(plan, snapshot, *, sql=None) -> Detection`
Detector D19. Usa la firma extendida con `sql=` (igual que D9/D11)
porque la distinción entre `HAVING` y `WHERE` no es recuperable desde
el plan. Parsea el SQL con sqlglot, localiza los SELECT con `HAVING` y
verifica si todas las referencias del HAVING son columnas del `GROUP BY`
(ninguna función de agregación). En ese caso el filtro puede moverse a
`WHERE` antes de la agregación, lo que reduce las filas que llegan al
nodo `Aggregate` y puede habilitar el uso de índices. Cada match
incluye `from_table`, `having_expr`, `group_by_cols` y
`suggested_rewrite` (SQL completo reescrito con WHERE en lugar de
HAVING). Confianza 0.9.

**Limitaciones conocidas:**
- Detecta correlación en `HAVING` solo sobre `Column` nodes simples; GROUP
  BY con expresiones complejas (`EXTRACT(...)`) produce `group_cols`
  vacío y el detector no dispara (falso negativo voluntario).
- Nota de sqlglot: la cláusula FROM se accede con `args.get("from_")`
  (clave con guión bajo, porque `from` es palabra reservada de Python).

### `detect_in_subquery_to_exists(plan, snapshot, *, sql=None) -> Detection`
Detector D20. Usa firma extendida con `sql=`. Detecta
`col IN (SELECT ...)` no correlacionados cuando el plan confirma que
el planner gastó trabajo en resolver la forma IN. **Acepta dos
variantes estructurales del plan** (cualquiera satisface la señal):

1. **Semi Join:** `Hash Join` / `Nested Loop` / `Merge Join` con
   `join_type="Semi"`. La forma "limpia" cuando el planner detecta
   que el IN es semánticamente un Semi Join.
2. **Aggregate descendiente bajo un join:** el planner dedupó la
   salida de la subquery con un HashAggregate antes del join. Q17
   real en AppDB v1 produce esta forma (`Nested Loop Inner` con
   `Aggregate` bajo el lado outer en lugar de Semi Join). El
   `Aggregate` aquí no proviene de un GROUP BY del usuario; esos
   quedan POR ENCIMA del join, no debajo.

Las dos señales (SQL + alguna del plan) son obligatorias: sin SQL o
sin señal del plan, D20 se abstiene. La correlación se verifica
buscando referencias calificadas (`tabla.columna`) de las tablas
externas dentro de la subquery. La recomendación es reescribir como
`WHERE EXISTS (SELECT 1 ...)`. Cada match incluye `column`,
`inner_table`, `has_in_signal_in_plan` (renombrado desde
`has_semi_join_in_plan` para reflejar la dualidad) y
`suggested_rewrite`. Confianza 0.9.

**Limitaciones conocidas:**
- No detecta correlación sin calificador de tabla (`WHERE col = outer`
  sin `outer_table.col`). En AppDB v1 las queries usan calificadores.
- El `suggested_rewrite` reemplaza todo el WHERE por `EXISTS`. Si la
  query tiene otras condiciones además del IN, el rewrite pierde esas
  condiciones (limitación documentada). Para Q17 esto no aplica.
- Nota de sqlglot: `IN (SELECT ...)` se representa como
  `In(query=Subquery(this=Select(...)))` — el Select real está en
  `subquery_node.this`, no en `subquery_node.expressions`.
- La segunda variante del plan (Aggregate bajo join) podría aparecer
  por razones distintas a un IN (e.g. subconsulta materializada en el
  FROM con GROUP BY). El requisito SQL (`IN (SELECT ...)` no
  correlacionado) previene los FP correspondientes.


### `detect_not_in_nullable_subquery(plan, snapshot, *, sql=None) -> Detection`
Detector D21. Usa firma extendida con `sql=`. Cubre el bug silencioso
y de performance de `WHERE col NOT IN (SELECT inner_col FROM t ...)`
cuando `inner_col` admite NULL en el schema. La detección vive 100%
en SQL + snapshot: el plan se acepta por uniformidad de firma pero
no se inspecciona (la información estructural relevante —
`is_nullable` — no aparece en el EXPLAIN; viene del catálogo vía B2).

**Por qué dispara:** la semántica trivaluada de SQL hace que un solo
NULL en la subquery vacíe el resultado completo (`x <> NULL` →
UNKNOWN; AND con UNKNOWN nunca es TRUE). Además, el planner no
puede convertir el `NOT IN` a Anti Join cuando la columna interna
es nullable; típicamente queda como `SubPlan`/`hashed SubPlan` sin
short-circuit. `NOT EXISTS` resuelve ambos problemas.

Cada match incluye `column` (la del outer), `inner_table`,
`inner_column`, `inner_is_nullable` (True por construcción),
`null_trap` (True; señal para que la capa de prosa diga
"bug silencioso" y no solo "lento") y `suggested_rewrite` con
`NOT EXISTS` correlacionado parseable por sqlglot. Confianza 0.95
— el bug es estructural, no heurístico.

**Frontera con detectores hermanos:**
- **D7 (correlated_subquery)** dispara en Q19 también porque
  Postgres resuelve el `NOT IN` con `SubPlan`. La coexistencia es
  intencional (regla #1 del proyecto: el motor reporta hechos
  estructurales; la capa de prosa prioriza). D7 dice "hay un
  SubPlan"; D21 dice "es específicamente el NULL trap".
- **D20 (in_subquery_to_exists)** cubre `IN`, no `NOT IN`. La
  exclusión es por construcción: `_is_negated` filtra opuestos.

**Limitaciones conocidas:**
- Si `inner_col` es una expresión (`COALESCE(col, 0)`,
  `col + 1`), `_first_projected_column` devuelve `None` y D21 se
  abstiene. Falso negativo voluntario: la expresión puede o no
  introducir NULLs y razonar sobre eso requiere análisis semántico
  fuera de scope.
- `_is_correlated` exige calificador de tabla (`t.col`) — sin él,
  no podemos distinguir referencia exterior. Misma decisión que D20.
- El rewrite reemplaza todo el WHERE del outer; si la query tiene
  `WHERE status = 1 AND id NOT IN (SELECT ...)`, las condiciones
  adicionales se pierden. Limitación documentada heredada de D20.
- Snapshot ausente / tabla desconocida / columna no encontrada →
  abstención (no FP). Preferimos perder Q19 antes que recomendar
  un rewrite sobre supuestos no verificados.

### `detect_count_star_full_table(plan, snapshot) -> Detection`
Detector D22. Estructural puro. Dispara cuando:
1. La raíz es `Aggregate` con `strategy="Plain"` y sin `group_key`.
2. No hay joins (`Nested Loop` / `Hash Join` / `Merge Join`) en el
   subárbol.
3. En el subárbol existe al menos un scan (`Seq Scan`, `Index Scan`,
   `Index Only Scan`, `Bitmap Heap Scan`) sobre **una sola** relación
   y ninguno tiene `filter`, `index_cond` ni `recheck_cond`.
4. La relación tiene `estimated_rows >= LARGE_TABLE_MIN_ROWS` en
   `snapshot["sizes"]`.

Cubre `SELECT count(*) FROM tabla_grande` (Q20) y también
`sum`/`avg`/`max`/`min` sin WHERE — el plan es estructuralmente
idéntico. Cada match incluye `table`, `estimated_rows`,
`scan_node_type` y `suggested_alternatives` (tupla con
`pg_class.reltuples`, tabla de contadores, o filtrar la query).
Confianza 0.95.

**Limitaciones conocidas:**
- Aplica también a `sum/avg/max/min` sin WHERE, no solo a `count(*)`.
  El plan es idéntico; la prosa del LLM debe moderar la recomendación
  de `pg_class.reltuples` cuando no es intercambiable.
- Si Postgres usa `Index Only Scan` con visibility map al 100% (tabla
  append-only con `VACUUM` reciente), el costo real baja
  significativamente. El detector sigue disparando — la alternativa
  `pg_class.reltuples` sigue siendo más barata.
- No persigue queries con `count(DISTINCT col)` específicamente; el
  plan podría tener un `Aggregate Hashed` que sí matchea la
  condición (1) — pero `group_key` quedaría vacío y `Strategy` no
  sería `Plain`. Si en el futuro encontramos un caso real, ajustar.

### `detect_cardinality_misestimate(plan, snapshot) -> Detection`
Detector D18. Recorre joins (`Hash Join`, `Merge Join`, `Nested
Loop`), compara `plan_rows` vs `actual_rows`, y si la razón en
cualquier dirección es ≥5× **y** algún scan descendiente tiene un
`Filter` con AND de ≥2 columnas distintas de la misma tabla, dispara
con recomendación `CREATE STATISTICS` multi-columna. Cada match
incluye `join_node_type`, `plan_rows`, `actual_rows`, `table`,
`columns`, `filter`, `scan_node_type`, `suggested_statistics_name`,
`suggested_sql`. Confianza 0.85.

**Limitaciones conocidas:**
- **Requiere `Actual Rows`:** sin `EXPLAIN ANALYZE` el detector se
  abstiene. Es por diseño — sin el dato real no hay cómo saber si
  el planner se equivocó.
- **`AND` se cuenta por presencia de la palabra en el texto del
  predicado.** Estructuras `(a AND b) OR c` cuentan como "AND
  multi-col" aunque el ramal sin AND también sea válido. Mitigación
  pendiente cuando aparezca el caso en AppDB v2: parsear el filtro
  con sqlglot.
- **Misma tabla = misma `relation_name`.** Si el filtro mezcla
  columnas de la tabla scaneada y de un alias join, solo cuentan las
  de la tabla del scan (lo cual es correcto para D18 — `CREATE
  STATISTICS` es por tabla).
- **El umbral 5× no escala con el tamaño de la tabla.** En tablas
  muy pequeñas (cientos de filas) un factor 5× puede ser ruido. D13
  filtrará por tamaño cuando aplique.

### `detect_correlated_subquery(plan, snapshot) -> Detection`
Detector D7. Dispara cuando algún nodo del árbol tiene
`subplan_name` que contiene la cadena `"SubPlan"`. Postgres usa
`SubPlan N` para subqueries correlacionadas (se evalúan una vez por
cada fila de la query externa) e `InitPlan N` para las no
correlacionadas (una sola evaluación). El detector explícitamente NO
matchea `InitPlan`. La recomendación documentada es reescribir como
JOIN o `EXISTS`. Cada match incluye `subplan_name`, `node_type`,
`inner_table` (tabla del SubPlan) y `outer_table` (relación del nodo
con `subplan_name`). Confianza 0.95.

**Características que lo hacen el detector más limpio en R2:**
- No usa regex. Lee `node.subplan_name` directo del atributo tipado.
- Recorrido propio DFS (no usa `find_nodes` con tipo, porque el
  SubPlan puede colgar de muchos `node_type` distintos).
- La sustring `"SubPlan"` viene del nombre que Postgres asigna, no
  del SQL del usuario.

**Limitaciones conocidas:**
- No mide qué tan correlacionado está el SubPlan ni cuántas veces se
  ejecuta. Reporta presencia, no impacto. La validación de impacto
  vive en el sandbox (cuando se conecte el recomendador hermano).
- `outer_table` se aproxima como `relation_name` del nodo que tiene
  `subplan_name`; si el SubPlan cuelga de un join, devuelve la
  primera relación interna que encuentra recorriendo hijos.

### `detect_nested_loop_large_outer(plan, snapshot) -> Detection`
Detector D8. Dispara cuando un nodo `Nested Loop` tiene como hijo
externo (Outer) un subárbol que emite >10k filas. Postgres ejecuta
el lado interno una vez por cada fila del externo, así que un Nested
Loop con outer grande casi siempre debería ser `Hash Join` o
`Merge Join`. El detector resuelve qué hijo es el outer con
`Parent Relationship == "Outer"`; si no está marcado (Postgres no
siempre lo emite), toma el primer hijo por convención. Usa
`actual_rows` cuando EXPLAIN ANALYZE las trae, si no `plan_rows`.
Cada match incluye `outer_table`, `outer_node_type`, `outer_rows`,
`outer_rows_source` (`"actual"` o `"plan"`), `join_type`. Confianza
0.8.

**Umbral:** `LARGE_OUTER_MIN_ROWS = 10_000`. Por debajo de eso,
Nested Loop suele ser óptimo y disparar sería FP.

**Limitaciones conocidas:**
- No mide cuántas veces se ejecuta el inner ni el costo real de
  cada loop. Reporta presencia, no impacto. La cuantificación va al
  recomendador (cruzando con snapshot y, eventualmente, sandbox).
- Reporta `outer_table` como la primera relación que encuentra
  recorriendo hijos. En joins anidados puede no ser intuitivo;
  útil para la prosa, no parte del criterio de detección.

### `detect_select_star(plan, snapshot, *, sql=None) -> Detection`
Detector D9. **Único detector del módulo con firma extendida**:
acepta `sql: str | None` como keyword-only opcional. Sin SQL no hay
forma estructural de detectar `SELECT *` (Postgres ya resolvió la
lista de proyección antes de generar el EXPLAIN), así que cuando
`sql is None` el detector devuelve `Detection(found=False)` en lugar
de levantar.

Parsea el SQL con `sqlglot.parse_one(sql, dialect="postgres")`,
recorre todos los nodos `Select` del árbol, y dispara cuando la
lista de proyección contiene un `Star` (no calificado o `tabla.*`).
Para cada match añade `index_only_candidate: bool` cruzando con el
plan: True si hay al menos un `Index Scan` en el árbol (oportunidad
de pasar a `Index Only Scan` con índice cubriente). Cada match
incluye `table`, `index_only_candidate`, `from_text`. Confianza 0.85.

**Robustez:** ante SQL no parseable (`sqlglot.errors.ParseError`)
devuelve `found=False` silenciosamente.

**Convención de firma extendida:** el orquestador (`/backend`)
detecta esta firma vía inspección de parámetros y pasa `sql=`
explícitamente solo a los detectores que lo aceptan. Si en el
futuro otro detector necesita la query (D11 con cast implícito,
por ejemplo), debe seguir el mismo patrón keyword-only para no
romper la firma estándar de los detectores estructurales.

**Limitaciones conocidas:**
- **No reporta qué columnas se usan realmente.** Determinar eso
  requiere análisis de WHERE/JOIN/ORDER y queda en el recomendador.
  D9 solo señala la oportunidad estructural.
- **Detecta `SELECT *` en cada subquery por separado.** Una outer
  con columnas explícitas y una inner con `*` dispara un match (la
  inner es el problema).
- **No distingue `SELECT *` justificado** (e.g.
  `INSERT INTO t SELECT * FROM staging`) de no justificado. El
  recomendador y el LLM deben moderar la prosa en esos contextos.

### `detect_missing_covering_index(plan, snapshot) -> Detection`
Detector D10. Estructural puro. Dispara una vez por cada `Index Scan`
en el plan (NO matchea `Index Only Scan`, que ya resuelve sin heap
fetch) **que devuelva ≥ `INDEX_SCAN_MIN_ROWS = 50` filas**. Cada
`Index Scan` implica un heap fetch por fila devuelta: si todas las
columnas que la query necesita cupieran en el índice (via `INCLUDE`
o columnas extra del índice), el plan pasaría a `Index Only Scan`.
La lista exacta de columnas a incluir la decide el recomendador
(cruzando con el SQL sanitizado); D10 solo reporta la oportunidad y
enriquece el match con metadata del índice existente desde el
snapshot. Cada match incluye `table`, `index_name`, `index_cond`,
`indexed_columns`, `include_columns`. Confianza 0.7.

**Umbral de filas:** `INDEX_SCAN_MIN_ROWS = 50`. Un `Index Scan` que
devuelve <50 filas (lookup por PK, filtros muy selectivos) casi
nunca se beneficia de un cubriente: el heap fetch ahorrado es
despreciable y el `INCLUDE` solo encarece el índice. Filtrar aquí
elimina la mayoría de FPs estructurales obvios. El detector prefiere
`actual_rows` sobre `plan_rows` cuando EXPLAIN ANALYZE las trae.

**Limitaciones conocidas:**
- **Confianza 0.7 — más laxa del catálogo.** Por encima del umbral,
  no todo `Index Scan` se beneficia: si las columnas extra son
  enormes (`text`), el `INCLUDE` cuesta más de lo que ahorra. El
  recomendador (con sandbox) debe filtrar el caso antes de emitir
  prosa enfática.
- **No reporta `Heap Fetches` numéricos.** Postgres no expone ese
  contador en `Index Scan` (solo en `Index Only Scan` con visibility
  map). El detector se conforma con la señal estructural.
- **No detecta `Bitmap Heap Scan` como candidato.** Bitmap con
  muchas filas también podría beneficiarse, pero la decisión es
  más compleja y queda fuera de scope.

### `detect_type_mismatch(plan, snapshot, *, sql=None) -> Detection`
Detector D11. Dispara cuando un nodo scan (`Seq Scan`, `Bitmap Heap
Scan`, `Bitmap Index Scan`) tiene en `node.filter` el patrón
`((col)::tipo = valor)` — notación de Postgres para un cast sobre la
columna. Un cast sobre la columna impide usar el índice btree sobre
esa columna: el planner no puede evaluarlo sin transformar cada
entrada del índice. El detector adicionalmente verifica que existe
un índice btree (primera columna = `col`) en el snapshot; sin índice,
el Seq Scan es inevitable y el pattern correcto es D16. Cada match
incluye `table`, `column`, `cast_type`, `filter`, `node_type`,
`index_name`. Confianza 0.9.

**Firma extendida:** acepta `sql: str | None = None` como
keyword-only, siguiendo el patrón de D9 (`detect_select_star`).
Hoy el parámetro no se usa; reservado para validación futura del
tipo declarado en el schema contra el tipo del cast. Los detectores
que necesiten el SQL del usuario deben seguir este mismo patrón.

**Regex interno:** `_CAST_ON_COLUMN_RE = r"\(\((\w+)\)::(\w+)"`.
Opera sobre el campo `node.filter` emitido por Postgres (estable en
PG 12-16). Permitido por R2: el campo es generado por Postgres, no es
el SQL crudo del usuario.

**Limitaciones conocidas:**
- **Formatos alternativos de cast.** `CAST(col AS tipo)` (forma
  estándar SQL) y `col::tipo` sin dobles paréntesis no matchean el
  regex. En EXPLAIN de Postgres 12-16 el formato `((col)::tipo` es
  el estándar; si una versión futura cambia la representación, el
  detector deja de funcionar silenciosamente (FN, no crash).
- **Cast sobre expresión compuesta.** `((a + b)::integer = 5)` no
  matchea porque `a + b` no es `\w+`. Falso negativo voluntario.
- **Sin filtro de tamaño de tabla.** Un cast en una tabla de 50 filas
  dispara con la misma confianza que en una de 10M. El recomendador
  debe moderar la prosa para tablas pequeñas.

### `detect_unnecessary_cte_materialize(plan, snapshot) -> Detection`
Detector D12. Dispara cuando el plan contiene nodos `CTE Scan` cuya
`cte_name` aparece exactamente una vez y el plan no tiene ningún
nodo `Recursive Union`. Cuando una CTE no recursiva se referencia
una sola vez, materializarla como tabla temporal interna (el
comportamiento por defecto hasta Postgres 11) es innecesario en
Postgres 12+: el planner puede inlinar la CTE y optimizar la query
entera. La recomendación es añadir `NOT MATERIALIZED` a la cláusula
WITH. Si la misma `cte_name` aparece en dos nodos `CTE Scan`, la
materialización es útil (evita recalcular); no se reporta. Si hay
un `Recursive Union` en cualquier lugar del plan, el detector es
conservador y no reporta ninguna CTE (no podemos distinguir cuál
nodo corresponde a la CTE recursiva sin contexto adicional). Cada
match incluye `cte_name`, `reference_count`, `node_type`,
`plan_rows`. Confianza 0.85.

**Limitaciones conocidas:**
- **Heurístico conservador ante `Recursive Union`.** Cualquier
  `Recursive Union` en el plan bloquea todos los matches, aunque
  el `CTE Scan` candidato no sea el de la CTE recursiva. La
  alternativa (intentar correlacionar `CTE Scan` con `Recursive
  Union`) es frágil en planes anidados; el FN ocasional es
  preferible al FP de recomendar `NOT MATERIALIZED` sobre una CTE
  recursiva.
- **CTEs DML.** Una CTE con `INSERT`/`UPDATE`/`DELETE` debe
  materializarse. D12 no parsea el SQL del usuario, así que en
  queries DML podría reportar FP. En AppDB v1 (queries de lectura
  puras) no aplica; para producción el recomendador debe verificar
  el SQL antes de emitir prosa.
- **Planner con razón al materializar.** En algunos planes el
  planner de Postgres 12+ elige materializar aunque solo haya una
  referencia porque estima que el costo de recalcular la CTE en el
  contexto del plan es mayor. El sandbox confirma antes de mostrar.

### `Recommendation` (frozen dataclass) — C2 + D13
Salida del recomendador. Campos:
- `kind: Literal["create_index", "analyze", "create_partial_index",
  "create_statistics", "skipped_low_selectivity"]` — la acción
  sugerida. `"analyze"` aparece cuando ya existe un índice
  equivalente (problema probable: stats desactualizadas).
  `"create_partial_index"` y `"create_statistics"` se introdujeron en
  D13 para D17 y D18 respectivamente. `"skipped_low_selectivity"` es
  el marcador D13 cuando un `create_index` se descarta por baja
  selectividad — el SQL está vacío y la justificación explica por qué.
- `table: str` — clave `"<schema>.<tabla>"` del snapshot.
- `column: str` — columna principal (para `create_statistics` apunta
  a la más selectiva).
- `index_method: str` — `"btree"` para v1; `"extended_statistics"` en
  el caso de `create_statistics`.
- `index_name: str` — nombre sugerido para el índice/stats nuevo
  (`idx_<tabla>_<columna>`, `stats_<tabla>_<cols>`). En `analyze`
  apunta al índice existente.
- `create_index_sql: str` — SQL final listo para mostrar al usuario.
  Para `analyze` es `ANALYZE <schema>.<tabla>;`; para
  `create_statistics` es `CREATE STATISTICS …`; vacío en
  `skipped_low_selectivity`.
- `justification: str` — explicación textual derivada de
  `n_distinct`/`null_frac`/tamaño.
- `expected_impact: str` — prosa corta con el impacto esperado.
- `selectivity: float | None` — selectividad estimada del filtro (0..1).
  `None` si la tabla nunca tuvo `ANALYZE` o el kind no aplica
  (`create_statistics`).
- `partial_predicate: str | None` — cláusula `WHERE` del índice
  parcial (`"<col> = <valor>"`). Solo en `create_partial_index`.
- `statistics_columns: tuple[str, ...] | None` — columnas listadas en
  `CREATE STATISTICS`, ordenadas por selectividad descendente. Solo
  en `create_statistics`.

### `MIN_SELECTIVITY_FOR_INDEX: float = 0.2`
Umbral D13 para descartar `create_index`. Si el filtro pasa más del
20% de las filas, un btree no aporta (Postgres prefiere Seq Scan).
Override por test usando el keyword-only `min_selectivity` de los
recomendadores que lo aceptan.

### `recommend_for_seq_scan_on_large_table(detection, snapshot, *, min_selectivity=MIN_SELECTIVITY_FOR_INDEX) -> list[Recommendation]`
Recomendador C2 ampliado con D13. Recibe una `Detection` de C1 y
produce una `Recommendation` por entrada en `evidence["matches"]`.

- Si ya existe un índice btree apuntable, emite `kind="analyze"`.
  Nunca se filtra por selectividad (es barato y útil).
- Si NO existe ese índice y la selectividad estimada > `min_selectivity`,
  emite `kind="skipped_low_selectivity"` (marker para logs; no se
  muestra en UI principal).
- En el resto de los casos, emite `kind="create_index"`.

La selectividad se calcula a partir de `snapshot["stats"][table][col]`
con la convención Postgres (n_distinct positivo = absoluto;
negativo = ratio). Si no hay stats, queda en `None` y NO se descarta
(la decisión la toma el sandbox C3).

### `recommend_for_missing_index(detection, snapshot, *, min_selectivity=MIN_SELECTIVITY_FOR_INDEX) -> list[Recommendation]`
Recomendador para D16. Lee `suggested_sql` y `suggested_index_name`
del evidence del detector, enriquece con stats y aplica el mismo
filtro de selectividad que C1. Cuando la selectividad supera el
umbral, sustituye por `skipped_low_selectivity` con razón.

### `recommend_for_partial_index_opportunity(detection, snapshot) -> list[Recommendation]`
Recomendador para D17. Construye `Recommendation` con
`kind="create_partial_index"` y `partial_predicate="<bool_col> =
<valor>"`. **NO se aplica el filtro D13:** la selectividad efectiva
del índice parcial depende del valor del bool (D17 no consulta
`most_common_freqs`); la decisión real la toma el sandbox C3 al
medir el costo con/sin el índice.

### `recommend_for_cardinality_misestimate(detection, snapshot) -> list[Recommendation]`
Recomendador para D18. Construye `Recommendation` con
`kind="create_statistics"`. Las columnas se ordenan por selectividad
descendente vía `order_columns_by_selectivity`. **NO se aplica el
filtro D13:** una estadística extendida no tiene costo de espacio
comparable a un índice, así que vale la pena emitirla siempre.

### `recommend(detections: dict[str, Detection], snapshot, *, min_selectivity=MIN_SELECTIVITY_FOR_INDEX) -> list[Recommendation]`
Orquestador D13. Recibe un mapa `código_detector → Detection` (mismo
shape que `scripts/measure_coverage.py.DETECTORS`) y combina las
recomendaciones de **C1, D16, D17, D18** en una lista plana, en orden
ascendente por código de detector para determinismo. Detectores sin
recomendador asociado (D4-D12) se ignoran silenciosamente — su salida
la consume el LLM/template como prosa explicativa.

### `compute_selectivity(column_stats, estimated_rows) -> float | None`
Selectividad estimada del filtro de igualdad sobre la columna.
Pública (D13) para que otros módulos (sandbox, backend) puedan
reproducir el cálculo. Devuelve `None` cuando no hay stats.

### `order_columns_by_selectivity(snapshot, table, columns) -> list[str]`
Ordena `columns` por selectividad ascendente (más selectiva primero).
Útil para índices compuestos y para presentar columnas en `CREATE
STATISTICS`. Sin stats → la columna queda al final preservando orden
original.

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
├── detection.py    # Detection (contrato compartido) (C1)
├── detectors/
│   ├── __init__.py
│   ├── _common.py                       # helpers compartidos C1/D16
│   ├── seq_scan_on_large_table.py       # C1
│   ├── stale_statistics.py              # D2
│   ├── sort_spill_to_disk.py            # D3p
│   ├── like_leading_wildcard.py         # D4
│   ├── function_in_where.py             # D5
│   ├── or_across_tables.py              # D6
│   ├── correlated_subquery.py           # D7
│   ├── nested_loop_large_outer.py       # D8
│   ├── select_star.py                   # D9
│   ├── missing_covering_index.py        # D10
│   ├── type_mismatch.py                 # D11
│   ├── unnecessary_cte_materialize.py   # D12
│   ├── missing_index.py                 # D16
│   ├── partial_index_opportunity.py     # D17
│   ├── cardinality_misestimate.py       # D18
│   ├── having_without_aggregate.py      # D19
│   ├── in_subquery_to_exists.py        # D20
│   └── count_star_full_table.py         # D22
├── recommender.py  # Recommendation + recommenders por detector (C2 + D13)
└── CLAUDE.md       # este archivo
```

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

Convención cuajada con C1 (ver `detectors/seq_scan_on_large_table.py`)
y D16 (mismo shape, predicado inverso, ver `detectors/missing_index.py`):

1. Un archivo nuevo en `motor/detectors/` con función pura
   `detect_X(plan: ExplainResult | PlanNode, snapshot: SchemaSnapshot) -> Detection`.
   - **Firma**: dos argumentos. El `snapshot` viene completo (no se
     descompone en `schema`/`sizes`/`stats` separados) — los detectores
     hacen sus propios `snapshot.get("schema", {})` según lo que necesiten.
   - **Pura**: no toca disco ni red; solo lee de los argumentos.
2. Internamente usa `find_nodes` para localizar candidatos. Cualquier
   inspección posterior va sobre los atributos tipados de `PlanNode`
   (R2: nunca regex sobre el SQL crudo ni sobre el texto entero del
   EXPLAIN; el regex sobre campos específicos como `node.filter` está
   permitido cuando el texto lo emite Postgres y es estable — ver el
   uso de `_FILTER_COLUMN_RE` en C1 con su justificación).
3. **Convención de `evidence`**: siempre devuelve
   `evidence={"matches": [...]}`. La lista puede estar vacía cuando
   `found=False`. Esto permite que los callers iteren sin chequear
   `found` primero y elimina ramas de `KeyError`.
4. Cada entrada de `matches` es un `dict` libre con los hechos crudos
   que sostienen la detección. Convenciones útiles:
   - `table: str` — `"<schema>.<tabla>"`, misma clave del snapshot
   - `column: str` — columna implicada cuando aplica
   - campos extra específicos del detector (ej. `index_name`,
     `estimated_rows`, `filter`)
5. **Tests** en `tests/motor/detectors/test_X.py`:
   - Happy path (criterio "hecho cuando" del backlog)
   - Negativo (caso donde NO debe disparar)
   - Frontera con detectores hermanos (defensa contra solapamiento)
   - Robustez (input degenerado: `filter=None`, `relation_name=None`,
     snapshot sin la tabla, etc.)
   - Fixtures de snapshot sintético en
     `tests/motor/detectors/conftest.py`; planes en
     `tests/motor/fixtures/*.json` (reales de AppDB) o sintéticos
     inline en el test cuando sirven mejor.
6. Registrar en `motor/detectors/__init__.py` y re-exportar desde
   `motor/__init__.py`.
7. Si los helpers que necesita ya viven en
   `motor/detectors/_common.py` (`column_from_filter`,
   `has_btree_index_on_column`, `resolve_table_key`,
   `LARGE_TABLE_MIN_ROWS`), usarlos en lugar de duplicar. Si necesitas
   un helper compartible nuevo, agrégalo a `_common.py` con prefijo
   sin guión bajo (los helpers privados al archivo sí van con `_`).

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

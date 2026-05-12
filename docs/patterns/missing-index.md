# Seq Scan sobre tabla grande sin índice en la columna del filtro

> **Detector:** `motor.detect_missing_index` (D16)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.95 (heurístico — la decisión final del
> recomendador depende de selectividad real del filtro)

## Problema

La query tiene un `WHERE col = X` (o `>`, `<`, `BETWEEN`) sobre una
tabla grande, pero la columna no está indexada. Postgres no tiene más
remedio que leer la tabla entera. En tablas de millones de filas el
costo se mide en cientos de miles de páginas leídas y latencias de
segundos por consulta — la receta para tumbar un endpoint en horas
pico.

Es el caso simétrico de C1 (`seq-scan-on-large-table`): C1 dispara
cuando el índice **existe** pero el planner lo ignora (síntoma de
stats desactualizadas); D16 dispara cuando el índice **falta**.

## Cómo aparece en el plan

Un nodo `Seq Scan` sobre una tabla con `Plan Rows`/`reltuples`
≥100 000, con un campo `Filter` que referencia una columna concreta.
La tabla puede aparecer envuelta en `Gather` (Postgres paraleliza el
Seq Scan en producción) o por debajo de un `Limit`/`Sort` — el
detector recorre el árbol entero buscando todos los `Seq Scan`.

## Regla de detección

Pseudocódigo (ver `motor/detectors/missing_index.py`):

```
for node in find_nodes(plan, "Seq Scan"):
    if node.relation_name is None:                 continue
    table_key = resolve_table_key(sizes, ...)      # "public.posts"
    if table_key is None:                          continue
    if sizes[table_key].estimated_rows < 100_000:  continue
    col = column_from_filter(node.filter)
    if col is None:                                continue
    if has_btree_index_on_column(schema[table_key], col):
        continue          # frontera con C1
    match!
```

Los helpers (`column_from_filter`, `has_btree_index_on_column`,
`resolve_table_key`) viven en `motor/detectors/_common.py` y son los
mismos que usa C1 — ese reuso es deliberado, garantiza que C1 y D16
se mantienen mutuamente excluyentes.

## Recomendación

`kind = "create_index"`, con SQL:

```sql
CREATE INDEX idx_<tabla>_<col> ON <schema>.<tabla> (<col>);
```

El `evidence["matches"]` incluye ya `suggested_index_name` y
`suggested_sql`, listos para que el recomendador los enriquezca con
selectividad y costo esperado.

## Validación

- **Sandbox (`sandbox.validate_index_recommendation`):** monta el
  schema en el sandbox efímero, ejecuta el `CREATE INDEX` propuesto,
  corre `EXPLAIN` antes y después y compara el `Total Cost`. La
  recomendación solo se muestra al usuario si el sandbox confirma que
  el planner usaría el índice nuevo y el costo baja.
- **LLM (`/ia/cross_validate`):** comprueba que la columna mencionada
  por el LLM coincide con la del detector (R3 — el motor decide, el
  LLM explica).

## Falsos positivos conocidos

- **Selectividad real desconocida sin stats.** Si la columna tiene
  solo 3 valores distintos en una tabla de 10M filas, el índice no
  ayuda (Postgres seguirá eligiendo Seq Scan o un Bitmap caro). D13
  (recomendador con selectividad real) descartará el `CREATE INDEX`
  antes de mostrarlo. D16 dispara estructuralmente; D13 filtra.
- **Función envolvente.** Si el filtro es `lower(col) = 'x'`, el
  regex de `column_from_filter` no extrae la columna porque empieza
  con `(` de apertura de función. Es D5 quien debe disparar.
- **Filtros multi-columna.** El regex toma la **primera** columna
  comparada. Si el filtro real es `(col1 = 1) AND (col2 = 2)` y el
  candidato indexable es `col2`, D16 no lo cubre (mismo trade-off
  documentado en C1, ver `motor/CLAUDE.md`).

## Ejemplo de query

```sql
-- Q01 plantada en AppDB v1
SELECT * FROM posts WHERE author_id = 5000;

-- Q06: BETWEEN sobre la misma columna
SELECT p.id, c.content
FROM posts p, comments c
WHERE p.id = c.post_id AND p.author_id BETWEEN 1 AND 100;

-- Q08: ORDER BY + LIMIT no salva si falta el índice
SELECT id, created_at FROM posts
WHERE author_id = 5000 ORDER BY created_at DESC LIMIT 20;
```

## Ejemplo de plan

```jsonc
{
  "Plan": {
    "Node Type": "Gather",
    "Workers Planned": 2,
    "Plans": [
      {
        "Node Type": "Seq Scan",
        "Relation Name": "posts",
        "Total Cost": 12000.0,
        "Plan Rows": 1,
        "Plan Width": 100,
        "Filter": "(author_id = 5000)",
        "Rows Removed by Filter": 499999
      }
    ]
  }
}
```

## Tests

`tests/motor/detectors/test_missing_index.py`:

- `test_dispara_q01_author_id_sin_indice` — happy path
- `test_dispara_q06_between_es_mismo_caso` — variante BETWEEN
- `test_dispara_dentro_de_gather` — recorre paralelismo
- `test_dispara_bajo_limit` — recorre `Limit > Sort > Seq Scan`
- `test_no_dispara_con_indice_existente` — frontera con C1
- `test_no_dispara_en_tabla_pequena` — umbral 100k
- `test_no_dispara_sin_filtro` — frontera con D22
- `test_no_dispara_sobre_tabla_desconocida` — abstención

## Referencias

- `/motor/detectors/missing_index.py` (implementación)
- `/motor/detectors/_common.py` (helpers compartidos con C1)
- `/motor/CLAUDE.md` (decisiones del módulo)
- Backlog D16 en `/PgPilot_Backlog.md`

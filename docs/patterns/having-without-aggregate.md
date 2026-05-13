# HAVING que debería ser WHERE

> **Detector:** `motor.detect_having_without_aggregate` (D19)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.9

## Problema

Cuando la cláusula `HAVING` solo contiene referencias a columnas del
`GROUP BY` y ninguna función de agregación (`count(*)`, `sum(...)`,
etc.), el filtro puede moverse a `WHERE` antes de la agregación. El
motor aplica la agregación a un conjunto de filas ya filtrado en lugar
de agregar todo y filtrar después, lo que reduce las filas que se
procesan en el nodo `Aggregate` y puede habilitar el uso de índices
sobre la columna filtrada.

## Cómo aparece en el plan

El plan muestra un nodo `Aggregate` sobre un `Seq Scan` sin filtro
previo, seguido de un `Filter` aplicado post-agregación. La señal de
detección viene del SQL (no del plan): el parser sqlglot identifica la
cláusula `HAVING` con condición movible.

## Regla de detección

Pseudocódigo (ver `motor/detectors/having_without_aggregate.py`):

```
for select in sqlglot_parse(sql).find_all(Select):
    having = select.HAVING
    if having is None:                          continue
    group_cols = {col.name for col in select.GROUP_BY if col is Column}
    if not group_cols:                          continue
    # ¿HAVING tiene agregados?
    if any(node is AggFunc for node in having.walk()):
        continue  # HAVING legítimo — no tocar
    # ¿Todas las columnas del HAVING están en GROUP BY?
    if any(col.name not in group_cols for col in having.columns):
        continue
    match!  → suggested_rewrite moviendo la condición a WHERE
```

La detección usa la firma extendida `sql=` (igual que D9 y D11) porque
la distinción entre `HAVING` y `WHERE` no es recuperable desde el plan
— Postgres ya normalizó el AST antes de generar el EXPLAIN.

## Recomendación

Rewrite del SQL: la condición del `HAVING` se mueve al `WHERE`, antes
de la cláusula `GROUP BY`. El `suggested_rewrite` en `evidence` es SQL
completo y parseable con sqlglot.

```sql
-- Original (ineficiente):
SELECT author_id, count(*)
FROM posts
GROUP BY author_id
HAVING author_id = 1000

-- Rewrite propuesto:
SELECT author_id, count(*)
FROM posts
WHERE author_id = 1000
GROUP BY author_id
```

## Validación

- **Sandbox:** ejecutar `EXPLAIN ANALYZE` de la query original y de la
  versión reescrita (`suggested_rewrite`) sobre el schema temporal y
  comparar el costo total. El rewrite es válido si:
  1. El plan reescrito ya no muestra el `Filter` después del
     `Aggregate` (el filtro se aplica antes).
  2. El costo total baja o se mantiene (nunca debería subir; si lo
     hace, descartar la sugerencia y reportar al log).
- **LLM (`/ia/cross_validator.py`):** valida que las columnas y la
  tabla mencionadas en el rewrite existan en el snapshot. El rewrite
  emitido por D19 ya viene parseable con sqlglot (test
  `test_rewrite_q16_es_parseable_y_tiene_where`); si el LLM intenta
  modificar más allá del rewrite original, se valida contra el
  snapshot y se cae a la plantilla determinística si menciona
  columnas inexistentes.

## Falsos positivos conocidos

- **HAVING con mezcla legítima.** Si el HAVING combina una columna del
  GROUP BY con un agregado (`HAVING author_id = 1000 AND count(*) > 5`),
  el detector no dispara porque detecta el `count(*)` como AggFunc.
  Comportamiento correcto: la parte de `count(*) > 5` debe quedarse en
  HAVING.
- **GROUP BY con expresiones no-columna.** Si el GROUP BY contiene
  expresiones (`GROUP BY EXTRACT(YEAR FROM created_at)`), el detector
  no extrae el nombre de columna (solo `Column` nodes se extraen de
  `group_cols`). Falso negativo voluntario: preferimos no recomendar a
  recomendar una reescritura inválida.

## Ejemplo de query

```sql
-- Q16 plantada en AppDB v1
SELECT author_id, count(*)
FROM posts
GROUP BY author_id
HAVING author_id = 1000;
```

## Ejemplo de plan

```jsonc
{
  "Plan": {
    "Node Type": "Aggregate",
    "Strategy": "Hashed",
    "Filter": "(author_id = 1000)",   // <-- se aplica DESPUÉS de agregar
    "Plans": [
      {
        "Node Type": "Seq Scan",
        "Relation Name": "posts",
        "Plan Rows": 500000
        // sin Filter previo → agrega TODAS las filas
      }
    ]
  }
}
```

## Tests

`tests/motor/detectors/test_having_without_aggregate.py`:

- `test_dispara_q16_having_author_id` — happy path Q16
- `test_rewrite_q16_es_parseable_y_tiene_where` — rewrite válido, sin HAVING
- `test_rewrite_preserva_group_by` — GROUP BY se conserva
- `test_no_dispara_sin_sql` — abstención sin SQL
- `test_no_dispara_sin_having` — sin HAVING no dispara
- `test_no_dispara_having_con_agregado` — HAVING con count(*) es legítimo
- `test_no_dispara_having_con_suma` — HAVING con sum() es legítimo
- `test_rewrite_preserva_where_existente` — WHERE existente se combina con AND
- `test_no_dispara_sobre_select_sin_tablas` — robustez ante SELECT sin tabla

## Referencias

- `/motor/detectors/having_without_aggregate.py` (implementación)
- `/motor/CLAUDE.md` (decisiones del módulo)
- Backlog D19 en `/PgPilot_Backlog.md`

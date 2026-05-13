# IN con subquery debería ser EXISTS

> **Detector:** `motor.detect_in_subquery_to_exists` (D20)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.9

## Problema

`WHERE col IN (SELECT ...)` con una subquery no correlacionada puede
reescribirse como `WHERE EXISTS (SELECT 1 ...)`. Semánticamente son
equivalentes cuando la columna exterior es NOT NULL, pero la forma
`EXISTS` permite al motor parar en cuanto encuentra la primera fila que
satisface la condición (short-circuit), mientras que `IN` puede
construir el conjunto completo de la subquery antes de hacer la
comparación. En tablas grandes esto se traduce en diferencias de costo
apreciables.

## Cómo aparece en el plan

Postgres puede emitir dos formas estructurales equivalentes:

1. **Hash/Nested Loop/Merge Join con `Join Type: "Semi"`** — la forma
   "limpia" cuando el planner detecta que el IN es semánticamente un
   Semi Join.
2. **Join Inner con un `Aggregate` descendiente en uno de los hijos**
   — Postgres deduplica la salida de la subquery con un HashAggregate
   y luego hace un Inner Join contra la lista única. Q17 real en
   AppDB v1 produce esta forma (Nested Loop Inner con HashAggregate
   bajo el lado outer). El `Aggregate` aquí no proviene de un GROUP
   BY del usuario (esos quedan POR ENCIMA del join, no debajo).

Ambas formas significan lo mismo: el motor materializó la lista del
IN antes de cruzarla con la tabla outer.

## Regla de detección

La detección requiere **ambas** señales:

1. **Plan:** alguna de estas dos formas en el árbol:
   - `Hash Join` / `Nested Loop` / `Merge Join` con
     `join_type = "Semi"`, **o**
   - Un join cualquiera con un `Aggregate` descendiente bajo alguno
     de sus subárboles.
2. **SQL:** la query contiene `col IN (SELECT ...)` (no `NOT IN`, que es
   D21) con una subquery que no referencia columnas calificadas de la
   tabla exterior (no correlacionada).

Pseudocódigo:

```
has_semi_join = any(
    node.join_type == "Semi"
    for node in find_nodes(plan, ["Hash Join", "Nested Loop", "Merge Join"])
)

for select in parse(sql).find_all(Select):
    outer_tables = {table.name for table in select.FROM}
    for in_expr in select.WHERE.find_all(In):
        subquery = in_expr.query               # IN (SELECT ...)
        if is_not_in(in_expr):                 continue  # NOT IN → D21
        if is_correlated(subquery, outer_tables): continue  # → D7
        match!

if matches and has_semi_join → found=True
```

Requiere la firma extendida `sql=` porque la estructura interna del
plan no conserva la sintaxis `IN`/`EXISTS` original.

## Por qué exigir AMBAS señales

- Si solo se usara SQL: un `IN (SELECT ...)` sobre una tabla pequeña no
  genera Semi Join (el planner usa otro plan), y recomendaríamos EXISTS
  sin necesidad.
- Si solo se usara el plan: un Hash Semi Join puede venir de otras
  fuentes (como `ANY`).
- Con ambas señales, la precisión es alta y se evita solapamiento con
  D7 (subqueries correlacionadas → SubPlan, sin Semi Join).

## Recomendación

Rewrite del SQL: `IN (SELECT col FROM tabla WHERE ...)` →
`EXISTS (SELECT 1 FROM tabla WHERE col = outer_col AND ...)`.

```sql
-- Original:
SELECT id FROM users
WHERE id IN (SELECT author_id FROM posts WHERE created_at > $1)

-- Rewrite propuesto:
SELECT id FROM users
WHERE EXISTS (
  SELECT 1 FROM posts
  WHERE author_id = id AND created_at > $1
)
```

## Validación

- **Sandbox:** correr `EXPLAIN ANALYZE` de la query original
  (`IN (SELECT ...)`) y del rewrite (`EXISTS (SELECT 1 ...)`) sobre el
  schema temporal. El rewrite se valida si:
  1. El `Execution Time` baja respecto al original (típico: short-circuit
     de EXISTS gana en outers grandes).
  2. El plan reescrito conserva la semántica (mismo `Plan Rows` y
     mismo conjunto de filas esperado).
  Si el costo sube (improbable, pero posible cuando la outer es muy
  pequeña), se descarta y se mantiene la prosa explicativa sin
  recomendar el rewrite.
- **LLM (`/ia/cross_validator.py`):** valida que las tablas y columnas
  del `EXISTS` existan en el snapshot. Si el LLM altera el `WHERE` del
  EXISTS más allá del `suggested_rewrite` original y referencia
  columnas inexistentes, se descarta y se cae a la plantilla.

## Falsos positivos conocidos

- **La correlación se detecta solo por calificador.** `WHERE id IN
  (SELECT col FROM t WHERE col = outer_col)` sin calificador de tabla
  (sin `outer.col`) no es detectado como correlacionado — podría ser un
  FP si `outer_col` es realmente una referencia exterior. En AppDB v1,
  las queries plantadas usan calificadores, por lo que esto no aplica.
- **Rewrite reemplaza todo el WHERE.** Si la query tiene
  `WHERE status = 1 AND id IN (SELECT ...)`, el rewrite generado
  reemplaza todo el WHERE por `EXISTS`. Limitación documentada — no
  afecta la correctitud del rewrite para Q17 (solo IN en el WHERE).

## Ejemplo de query

```sql
-- Q17 plantada en AppDB v1
SELECT id FROM users
WHERE id IN (
  SELECT author_id FROM posts
  WHERE created_at > NOW() - INTERVAL '7 days'
);
```

## Ejemplo de plan

```jsonc
{
  "Plan": {
    "Node Type": "Hash Join",
    "Join Type": "Semi",        // <-- señal estructural de D20
    "Hash Cond": "(users.id = posts.author_id)",
    "Plans": [
      { "Node Type": "Seq Scan", "Relation Name": "users" },
      {
        "Node Type": "Hash",
        "Plans": [
          {
            "Node Type": "Seq Scan",
            "Relation Name": "posts",
            "Filter": "(created_at > ...)"
          }
        ]
      }
    ]
  }
}
```

## Tests

`tests/motor/detectors/test_in_subquery_to_exists.py`:

- `test_dispara_q17_in_subquery_con_semi_join` — happy path Q17
- `test_rewrite_q17_es_parseable_y_usa_exists` — rewrite válido con EXISTS
- `test_dispara_con_nested_loop_semi_join` — variante Nested Loop Semi
- `test_no_dispara_sin_sql` — abstención sin SQL
- `test_no_dispara_sin_semi_join_en_plan` — sin señal del plan → no dispara
- `test_no_dispara_in_con_lista_literal` — IN con literal no es subquery
- `test_no_dispara_inner_join_en_plan` — Hash Join Inner ≠ Semi Join
- `test_no_dispara_subquery_correlacionada` — frontera con D7
- `test_no_dispara_not_in_subquery` — frontera con D21
- `test_no_se_solapa_con_d7_subplan` — SubPlan en plan → D7 dispara, D20 no

## Referencias

- `/motor/detectors/in_subquery_to_exists.py` (implementación)
- `/motor/CLAUDE.md` (decisiones del módulo)
- Backlog D20 en `/PgPilot_Backlog.md`

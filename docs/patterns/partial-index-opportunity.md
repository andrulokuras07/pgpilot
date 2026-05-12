# Oportunidad de índice parcial

> **Detector:** `motor.detect_partial_index_opportunity` (D17)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.8 (heurístico — sin `most_common_freqs`)

## Problema

Una query filtra por dos columnas, una de ellas booleana. El índice
plano sobre la columna no-booleana incluye filas que el WHERE descarta
después (`WHERE user_id = ? AND read = false` recorre todas las
notificaciones del usuario aunque ya estén leídas). Un **índice
parcial** que solo indexa el subconjunto relevante (`WHERE read =
false`) es típicamente 5-50× más pequeño y rápido, además de que se
mantiene barato al escribir.

## Cómo aparece en el plan

Cualquier nodo scan (`Seq Scan`, `Bitmap Heap Scan`, `Index Scan`,
`Index Only Scan`, `Bitmap Index Scan`) con un filtro AND donde uno
de los predicados referencia una columna booleana. Postgres emite los
predicados booleanos de formas distintas según el SQL del usuario:

- `read = false` → `(NOT read)`
- `read = true`  → `(read = true)` o simplemente `read`
- `read IS FALSE`/`IS TRUE` → se mantiene literal

El detector reconoce las tres formas en `Filter`, `Recheck Cond` e
`Index Cond` del nodo.

## Regla de detección

Pseudocódigo (ver `motor/detectors/partial_index_opportunity.py`):

```
for node in find_nodes(plan, ("Seq Scan", "Bitmap Heap Scan",
                              "Index Scan", "Index Only Scan",
                              "Bitmap Index Scan")):
    table_key = resolve_table_key(schema, node.relation_name)
    if not table_key:                              continue
    bool_cols = { c.name for c in schema[table_key].columns
                  if c.data_type startswith "bool" }
    if not bool_cols:                              continue
    text = filter + " AND " + recheck_cond + " AND " + index_cond
    (bool_col, value) = find_bool_predicate(text, bool_cols)
    if (bool_col, value) is None:                  continue
    other_col = find_other_referenced_column(text, schema cols, exclude=bool_col)
    if other_col is None:                          continue
    match!
```

La heurística NO consulta `most_common_freqs` para decidir si la
columna booleana está "muy concentrada". Se delega la decisión final
al recomendador con stats reales (D13) y/o al sandbox.

## Recomendación

`kind = "create_partial_index"`, con SQL:

```sql
CREATE INDEX idx_<tabla>_<otra_col>_partial
    ON <schema>.<tabla> (<otra_col>)
    WHERE <bool_col> = <true|false>;
```

El `evidence["matches"]` ya trae `suggested_index_name`,
`suggested_sql`, `bool_column` y `bool_value` para que el recomendador
los muestre sin reprocesar.

## Validación

- **Sandbox:** monta el índice parcial y verifica que el planner lo
  usa para la query problemática (vs el índice plano si existe).
  Comparativo de costo.
- **LLM:** la prosa debe mencionar la cláusula `WHERE` del índice y
  explicar que solo cubre filas con `bool_col = valor`. Si el LLM
  omite esa cláusula, `cross_validate` descarta la sugerencia.

## Falsos positivos conocidos

- **Booleana sin sesgo real.** Si la distribución es ~50/50 en
  `read`, el índice parcial no ahorra significativamente. Sin
  `pg_stats.most_common_freqs`, D17 no lo detecta. Mitigación
  pendiente: extender B4 con MCF y descartar matches con frecuencia
  cercana a 0.5.
- **Columna booleana sin AND.** Si el filtro es solo `(NOT read)`,
  no hay otra columna que indexar — el detector se abstiene.
- **`is_active` y similares siempre `true`.** Si la columna está
  permanentemente en un solo valor, un índice plano sería igual de
  bueno. Caso para D13.

## Ejemplo de query

```sql
-- Q11 plantada en AppDB v1
SELECT id FROM notifications WHERE user_id = 1000 AND read = false;
```

## Ejemplo de plan

```jsonc
{
  "Plan": {
    "Node Type": "Bitmap Heap Scan",
    "Relation Name": "notifications",
    "Recheck Cond": "(user_id = 1000)",
    "Filter": "(NOT read)",
    "Plans": [
      {
        "Node Type": "Bitmap Index Scan",
        "Index Name": "idx_notifications_user_id",
        "Index Cond": "(user_id = 1000)"
      }
    ]
  }
}
```

El detector dispara sobre el `Bitmap Heap Scan`: la bool `read` está
en el `Filter`, `user_id` aparece en el `Recheck Cond`. La
recomendación final indexa `user_id` con `WHERE read = false`.

## Tests

`tests/motor/detectors/test_partial_index_opportunity.py`:

- `test_dispara_q11_bitmap_heap_scan_con_filter_bool` — happy path
- `test_dispara_con_read_equal_true` — forma `col = true`
- `test_dispara_con_read_is_false` — forma `col IS FALSE`
- `test_no_dispara_sin_columna_booleana_en_schema` — robustez
- `test_no_dispara_si_solo_hay_bool` — falta otra columna
- `test_no_dispara_sobre_tabla_desconocida` — abstención

## Referencias

- `/motor/detectors/partial_index_opportunity.py` (implementación)
- `/motor/CLAUDE.md` (decisiones del módulo)
- Backlog D17 en `/PgPilot_Backlog.md`
- Postgres docs — Partial Indexes:
  <https://www.postgresql.org/docs/current/indexes-partial.html>

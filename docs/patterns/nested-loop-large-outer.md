# Nested Loop con tabla externa grande

> **Detector:** `motor.detect_nested_loop_large_outer` (D8)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.8 (heurístico estructural)

## Problema

Un `Nested Loop` evalúa el lado interno una vez por cada fila del
externo. Si la tabla externa devuelve 50k filas, el inner se ejecuta
50k veces — incluso cuando cada ejecución es barata, el total se
vuelve cuadrático. Para outer >10k filas, casi siempre debería ser
`Hash Join` (construye una tabla hash del inner una sola vez) o
`Merge Join` (cuando ambos lados llegan ordenados).

El planner suele elegir Nested Loop por dos razones erradas:
1. `work_mem` insuficiente para el hash del inner — cae a Nested
   Loop como último recurso.
2. Estadísticas viejas que subestiman el outer (`reltuples` mal
   calibrado, falta de `ANALYZE`).

El síntoma típico es "el query es rápido en staging pero en prod
tarda 30 s" — porque en prod el outer es 100× más grande, pero el
planner sigue eligiendo Nested Loop como en staging.

## Cómo aparece en el plan

El nodo `Nested Loop` lleva dos hijos. El detector identifica el
outer así:

- Prioridad: hijo con `Parent Relationship: "Outer"`.
- Fallback: primer hijo en la lista (Postgres no siempre marca el
  campo, depende de la versión y del shape del plan).

El detector mira las filas del outer:

- Si `Actual Rows` está disponible (EXPLAIN ANALYZE), se usa.
- Si no, se usa `Plan Rows`.

Si las filas ≥ `LARGE_OUTER_MIN_ROWS = 10_000`, dispara.

## Regla de detección

Pseudocódigo (mapea contra
`motor/detectors/nested_loop_large_outer.py`):

```
para cada nodo en find_nodes(plan, "Nested Loop"):
    outer = hijo con parent_relationship="Outer", o el primer hijo
    si outer es None: skip
    outer_rows = outer.actual_rows si está, si no outer.plan_rows
    si outer_rows < 10_000: skip
    matches.append({outer_table, outer_node_type, outer_rows,
                    outer_rows_source, join_type})

devolver Detection(found=bool(matches), confidence=0.8, evidence={"matches": matches})
```

## Recomendación

(Pendiente integración con `motor/recommender.py`.) El detector
documenta tres caminos posibles:

1. **Refrescar estadísticas:** `ANALYZE <tabla_outer>;`. Es la
   acción más barata y a menudo suficiente.
2. **Aumentar `work_mem`** para la sesión (`SET work_mem = '64MB'`):
   permite al planner considerar Hash Join.
3. **Reescribir la condición de join** para que el planner tenga
   alternativas (e.g. eliminar `OR` o cruces no equi-join que
   fuerzan Nested Loop).

El SQL exacto lo propone el LLM (`/ia`) y se valida con sandbox
(`sandbox.validate_index_recommendation`) cuando aplique.

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- Antes/después: correr `EXPLAIN ANALYZE` original y comparar
  con un `EXPLAIN ANALYZE SET work_mem = '64MB'; ...` en sandbox.
  Si el plan pasa a `Hash Join` y el costo cae, se reporta como
  verificado.
- LLM: `/ia/cross_validator.py` valida que las tablas mencionadas
  en la prosa existan en el snapshot. La sugerencia de `ANALYZE`
  contra una tabla inexistente se descarta.

## Falsos positivos conocidos

- **Outer de 10k–50k filas con inner muy selectivo y bien indexado.**
  En algunos casos, Postgres realmente elige Nested Loop porque es
  óptimo (5k loops × 0.01 ms = 50 ms, mejor que construir un hash).
  El detector dispara igual; el recomendador debería ponderar con
  el `actual_total_time` antes de emitir prosa enfática.
- **Joins paralelos.** Si Nested Loop está dentro de un `Gather`,
  el outer reportado puede ser solo el shard de un worker, no la
  cardinalidad total. El detector toma las filas tal cual aparecen
  en el nodo; el recomendador puede multiplicar por
  `workers_launched` cuando aplique.
- **`outer_table` aproximado.** Cuando el outer es a su vez un join
  o un Materialize, el detector reporta la primera relación que
  encuentra recorriendo hijos. Útil para la prosa, no para el
  criterio de detección.

## Ejemplo de query

```sql
SELECT p.id, u.email
FROM posts p
JOIN users u ON u.id = p.author_id
WHERE p.published_at > $LITERAL_3_0;
```

`posts` filtrada por `published_at` devuelve 50k filas; `users` se
busca por PK. El planner elige Nested Loop sin pensar en Hash Join.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Nested Loop",
    "Join Type": "Inner",
    "Plan Rows": 50000,
    "Actual Rows": 50000,
    "Plans": [
      {
        "Node Type": "Seq Scan",
        "Parent Relationship": "Outer",
        "Relation Name": "posts",
        "Plan Rows": 50000,
        "Actual Rows": 50000,
        "Filter": "(published_at > '2024-01-01'::date)"
      },
      {
        "Node Type": "Index Scan",
        "Parent Relationship": "Inner",
        "Relation Name": "users",
        "Index Name": "users_pkey",
        "Index Cond": "(id = p.author_id)",
        "Plan Rows": 1
      }
    ]
  }
}
```

D8 evalúa:

- Nodo `Nested Loop` ✓
- Hijo con `Parent Relationship: "Outer"` → `Seq Scan` sobre `posts`
- `actual_rows = 50_000 ≥ 10_000` ✓
- ⇒ `Detection(found=True, confidence=0.8, evidence={"matches": [{outer_table: "posts", outer_rows: 50000, outer_rows_source: "actual", join_type: "Inner", ...}]})`

## Tests

`tests/motor/detectors/test_nested_loop_large_outer.py`. Cubre:

- Happy path: Nested Loop con outer marcado y 50k filas → dispara.
- Negativo: outer <10k filas → no dispara (Nested Loop es óptimo).
- Negativo (frontera): Hash Join con outer enorme → no dispara
  (D8 solo aplica a Nested Loop).
- `Actual Rows` se prefiere a `Plan Rows` cuando ambos están
  disponibles.
- Outer inferido como primer hijo cuando `Parent Relationship` no
  viene en el JSON.

## Referencias

- `/motor/detectors/nested_loop_large_outer.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_nested_loop_large_outer`)
- Backlog `D8` en `/PgPilot_Backlog.md`
- Postgres docs:
  [Join Strategies](https://www.postgresql.org/docs/current/planner-optimizer.html)

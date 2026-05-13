# Mismatch entre `rows estimated` y `rows actual` (stats obsoletas)

> **Detector:** `motor.detect_stale_statistics` (D2)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.85 (heurístico — el ratio 10x es la frontera
> clásica pero no demuestra causalidad por sí solo)

## Problema

Postgres toma decisiones de planeación con `pg_class.reltuples`,
`pg_statistic.most_common_vals/freqs` y `pg_stats.histogram_bounds`.
Cuando esas estadísticas se quedan rezagadas frente a los datos
reales —por inserts/deletes/updates intensos, o por autovacuum mal
calibrado— el planner razona con un mundo que ya no existe. Resultado:
elige el orden de joins equivocado, pone Hash Joins donde no caben en
RAM, prefiere Seq Scan creyendo que la tabla es pequeña, dimensiona
mal el work_mem efectivo, y la latencia P99 se vuelve impredecible.

La firma diagnóstica es directa: `EXPLAIN ANALYZE` muestra el número
que el planner *creyó* (`Plan Rows`) y el que *fue* (`Actual Rows`)
en el mismo nodo. Cuando el ratio entre ambos supera un orden de
magnitud (10x), las estadísticas están podridas para esa tabla — y
la única respuesta correcta del DBA es `ANALYZE` (o `VACUUM ANALYZE`
si además hubo churn pesado).

## Cómo aparece en el plan

Cualquier nodo de scan con `Actual Rows` muy distinto a `Plan Rows`.
Las dos direcciones cuentan:

- **Overestimación** (`Plan Rows >> Actual Rows`): Postgres asignó
  memoria/loops por demás. Riesgo: subóptimo pero rara vez catastrófico.
- **Subestimación** (`Plan Rows << Actual Rows`): Postgres pensó "esto
  es chiquito" y eligió Nested Loop, Hash con pocas buckets, etc. Es
  el caso peligroso — el plan se cae a pedazos en producción.

Ejemplo (subestimación brutal):

```json
{
  "Node Type": "Bitmap Heap Scan",
  "Relation Name": "events",
  "Plan Rows": 10,
  "Actual Rows": 200000,
  "Recheck Cond": "(user_id = 7)"
}
```

El campo es estructurado — D2 nunca toca el SQL crudo del usuario.

## Regla de detección

Pseudocódigo (mapea contra `motor/detectors/stale_statistics.py`):

```
STALE_STATS_RATIO = 10.0
SCAN_TYPES = (Seq Scan, Index Scan, Index Only Scan, Bitmap Heap Scan)

para cada nodo en find_nodes(plan, SCAN_TYPES):
    si node.actual_rows is None: skip       # EXPLAIN sin ANALYZE
    si node.plan_rows is None: skip
    si node.relation_name is None: skip      # scan sintético
    if node.actual_rows == 0:
        si node.plan_rows > STALE_STATS_RATIO: match (overestimated)
        continue
    if node.plan_rows == 0:
        si node.actual_rows > STALE_STATS_RATIO: match (underestimated)
        continue
    ratio = max(plan/actual, actual/plan)
    si ratio < STALE_STATS_RATIO: skip
    direction = "overestimated" si plan>actual else "underestimated"
    matches.append({table, node_type, plan_rows, actual_rows, ratio,
                    direction, suggested_sql: "ANALYZE <table>;"})

devolver Detection(found=bool(matches), confidence=0.85, evidence={"matches": matches})
```

D2 dispara únicamente sobre nodos **scan** (no joins, no agregados):
el error de cardinalidad en un join suele ser síntoma de stats malas
del scan de abajo o de **correlación entre columnas** —este último
caso es competencia de D18 (`cardinality_misestimate`), que recomienda
`CREATE STATISTICS` multi-columna en lugar de `ANALYZE`.

## Recomendación

(Pendiente integración con `motor/recommender.py`.) El detector
documenta la recomendación textual a partir del campo `suggested_sql`
de cada match:

```sql
ANALYZE <table>;
-- o, si la tabla tiene mucho churn reciente:
VACUUM ANALYZE <table>;
```

Cuando el problema reincide pese a `ANALYZE`, la prosa del LLM puede
sugerir bajar `autovacuum_analyze_scale_factor` para esa tabla
específica con `ALTER TABLE ... SET (autovacuum_analyze_scale_factor = 0.02);`,
pero esa decisión queda fuera del recomendador determinístico.

## Validación

- **Sandbox:** el caso ideal sería re-ejecutar el `EXPLAIN ANALYZE`
  después del `ANALYZE` y verificar que el ratio cae. El sandbox de
  PgPilot no copia datos, así que esta validación queda pendiente —
  por ahora la confianza emitida (0.85) refleja que el detector
  identifica el *síntoma* sin demostrar la *causa* (R3: el motor
  decide con la evidencia que tiene; no afirma más).
- **LLM (`/ia/cross_validator.py`):** la prosa generada se valida
  contra el snapshot — si menciona una columna que no existe en la
  tabla, se cae a la plantilla.

## Falsos positivos conocidos

- **Joins mal estimados sin que el scan esté mal.** El ratio
  plan/actual de un `Hash Join` puede ser pésimo aunque cada scan
  de abajo esté bien estimado. D2 evita esto restringiendo el match
  a `_SCAN_TYPES`. El caso de joins con correlación es D18.
- **Filtros muy selectivos no capturados en `most_common_vals`.**
  Si una columna tiene 10 millones de valores y el filtro pide uno
  que no está en MCV, Postgres usa la fórmula genérica (1/n_distinct)
  y puede equivocarse fuerte aunque las stats estén "frescas". `ANALYZE`
  con `default_statistics_target` más alto mitiga; ampliar el catálogo
  para sugerirlo queda como trabajo futuro.
- **`actual_rows = 0` con plan grande.** Lo manejamos explícitamente
  como `overestimated` cuando `plan_rows > UMBRAL`, evitando la
  división por cero. El detector reporta `actual_rows: 0` en el match
  para que la prosa pueda decir "el planner esperaba ~5000 filas pero
  la query no devolvió ninguna".
- **`Index Scan` con `actual_loops > 1` (parte interior de Nested
  Loop).** Postgres divide `actual_rows` por `loops` antes de
  reportarlo en JSON, así que el campo ya viene normalizado por
  iteración. No re-multiplicamos. Esto significa que un Index Scan
  ejecutado 10000 veces con 1 fila por loop se ve como `actual_rows=1`
  —correcto, no engaña al detector.

## Ejemplo de query

```sql
SELECT id, title
FROM posts
WHERE author_id = 42;
```

Si `posts.author_id` tiene 50_000 filas para `author_id=42` pero las
stats dicen `n_distinct = 100`, Postgres estima 5_000 filas y elige
mal el plan que va arriba.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Seq Scan",
    "Relation Name": "posts",
    "Startup Cost": 0.0,
    "Total Cost": 1000.0,
    "Plan Rows": 50000,
    "Plan Width": 100,
    "Actual Rows": 100,
    "Actual Loops": 1,
    "Filter": "(author_id = 42)"
  }
}
```

Lo que D2 evalúa:

- Node Type ∈ _SCAN_TYPES ✓
- `actual_rows = 100`, `plan_rows = 50_000`
- `ratio = 50_000 / 100 = 500` ≥ 10 ✓
- `direction = "overestimated"`
- ⇒ `Detection(found=True, confidence=0.85, evidence={"matches": [{table:"posts", ratio:500.0, direction:"overestimated", suggested_sql:"ANALYZE posts;", ...}]})`

## Tests

`tests/motor/detectors/test_stale_statistics.py`. Cubre:

- Happy path overestimación (Seq Scan ratio 500x) → dispara.
- Happy path subestimación (Bitmap Heap Scan ratio 20_000x) → dispara.
- Variante: `Index Scan` también cuenta como scan.
- Negativo (frontera): ratio 5x → no dispara.
- Negativo: EXPLAIN sin ANALYZE → no dispara.
- Negativo (frontera con D18): join mal estimado pero scans bien → no dispara.
- Negativo: plan trivial sin scans → no dispara.
- Robustez: `actual_rows=0` con plan grande → dispara como overestimated.
- Robustez: `actual_rows=0` con plan chico → no dispara.
- Robustez: `relation_name=None` → no levanta excepción.
- Plurales: dos scans con stats malas en el mismo plan → dos matches.

## Referencias

- `/motor/detectors/stale_statistics.py` (implementación)
- `/motor/CLAUDE.md` (sección "detect_stale_statistics")
- Backlog `D2` en `/PgPilot_Backlog.md`
- Postgres docs: [`ANALYZE`](https://www.postgresql.org/docs/current/sql-analyze.html),
  [`pg_statistic`](https://www.postgresql.org/docs/current/catalog-pg-statistic.html)
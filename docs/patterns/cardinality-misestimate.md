# Error de cardinalidad en JOIN multi-condición

> **Detector:** `motor.detect_cardinality_misestimate` (D18)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.85

## Problema

Postgres estima la selectividad de cada predicado de un filtro de
forma independiente y multiplica. Si dos columnas están
correlacionadas (`is_verified=true` y `is_active=true` casi siempre
van juntas) la estimación es órdenes de magnitud menor a la realidad.
Como el planner decide el algoritmo de join (`Hash` vs `Nested Loop`)
con esa estimación, un error de 100× cambia un join de 30ms a 30s.

Postgres tiene la herramienta para arreglarlo desde la versión 10:
`CREATE STATISTICS` sobre las columnas correlacionadas. Pero no se
materializa por sí solo — hay que pedirlo explícito y luego
`ANALYZE`.

## Cómo aparece en el plan

Un nodo de join (`Hash Join`, `Merge Join`, `Nested Loop`) donde la
razón entre `Plan Rows` y `Actual Rows` es ≥5×, y donde un scan
descendiente tiene un `Filter` con dos o más columnas de la misma
tabla unidas por `AND`. La firma típica es la subestimación
(`Plan Rows: 1, Actual Rows: 50000`).

## Regla de detección

Pseudocódigo (ver `motor/detectors/cardinality_misestimate.py`):

```
for join in find_nodes(plan, ("Hash Join", "Merge Join", "Nested Loop")):
    if not is_misestimated(join):                 continue   # 5× threshold
    for scan in find_nodes(join, scan_types):
        table_key = resolve_table_key(schema, scan.relation_name)
        if not table_key:                         continue
        predicates = filter + recheck_cond + index_cond
        if "AND" not in predicates:               continue
        cols = columns_referenced(predicates, schema[table_key].columns)
        if len(cols) >= 2:
            match!
            break
```

El umbral 5× es el del backlog. La razón se calcula con
`max(plan/actual, actual/plan)` para capturar tanto subestimaciones
como sobreestimaciones; `actual_rows = 0` con `plan_rows > 5`
también cuenta (sobreestimación total). El detector requiere
`Actual Rows` — sin `EXPLAIN ANALYZE` no aplica.

## Recomendación

`kind = "create_statistics"`, con SQL:

```sql
CREATE STATISTICS stats_<tabla>_<col_a>_<col_b>
    ON <col_a>, <col_b>
    FROM <schema>.<tabla>;
ANALYZE <schema>.<tabla>;
```

`evidence["matches"]` incluye `suggested_statistics_name` y
`suggested_sql` además de los detalles del join afectado
(`plan_rows`, `actual_rows`, `join_node_type`).

## Validación

- **Sandbox:** ejecutar `CREATE STATISTICS` + `ANALYZE` y re-correr
  el `EXPLAIN`. Si la estimación nueva mejora ≥10× (acercándose al
  `Actual Rows` observado), la recomendación se valida.
- **LLM:** la prosa debe nombrar las columnas correlacionadas. Si
  el LLM nombra una columna distinta a las que aparecen en
  `evidence["matches"][0]["columns"]`, `cross_validate` lo descarta.

## Falsos positivos conocidos

- **Mal estimado por otra razón** (índice GIN sobre array, predicado
  funcional, FK no analizada). En esos casos `CREATE STATISTICS` no
  ayuda; ayudaría `ANALYZE` o cambiar el índice. D18 dispara por
  estructura — el sandbox debe verificar que `CREATE STATISTICS`
  efectivamente cambia la estimación.
- **Tablas pequeñas.** Por debajo de unos miles de filas, las
  estadísticas extendidas son ruido. D18 no filtra por tamaño hoy;
  D13 (recomendador con selectividad real) descarta cuando aplica.
- **`AND` dentro de un OR**. La heurística mira `AND` en el texto del
  predicado pero no entiende la estructura booleana completa. Un
  filtro `(a AND b) OR c` cuenta como "AND multi-col" aunque el
  ramal sin AND también sea válido. En AppDB v1 no aparece.

## Ejemplo de query

```sql
-- Q13 plantada en AppDB v1
SELECT p.id, u.username
FROM posts p
JOIN users u ON u.id = p.author_id
WHERE u.is_verified = true
  AND u.is_active = true
  AND p.is_deleted = false;
```

## Ejemplo de plan

```jsonc
{
  "Plan": {
    "Node Type": "Hash Join",
    "Plan Rows": 1,
    "Actual Rows": 50000,
    "Plans": [
      { "Node Type": "Seq Scan", "Relation Name": "posts",
        "Filter": "(NOT is_deleted)" },
      {
        "Node Type": "Hash",
        "Plans": [
          { "Node Type": "Seq Scan", "Relation Name": "users",
            "Filter": "(is_verified AND is_active)",
            "Plan Rows": 1, "Actual Rows": 100 }
        ]
      }
    ]
  }
}
```

## Tests

`tests/motor/detectors/test_cardinality_misestimate.py`:

- `test_dispara_q13_hash_join_mal_estimado` — happy path
- `test_no_dispara_si_ratio_es_bajo` — bajo umbral 5×
- `test_no_dispara_sin_actual_rows` — sin ANALYZE
- `test_no_dispara_con_filter_de_una_sola_columna` — frontera
- `test_no_dispara_sobre_simple_seq_scan_sin_join` — requiere join

## Referencias

- `/motor/detectors/cardinality_misestimate.py` (implementación)
- `/motor/CLAUDE.md` (decisiones del módulo)
- Backlog D18 en `/PgPilot_Backlog.md`
- Postgres docs — Extended Statistics:
  <https://www.postgresql.org/docs/current/sql-createstatistics.html>

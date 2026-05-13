# count(*) (o agregación) sobre tabla grande sin WHERE

> **Detector:** `motor.detect_count_star_full_table` (D22)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.95

## Problema

`SELECT count(*) FROM tabla_grande` exige al motor leer todas las filas
de la tabla. En Postgres, MVCC requiere validar visibilidad por fila,
así que ni siquiera un Index Only Scan elimina el costo en una tabla
con escrituras recientes. Las mismas consideraciones aplican a
`SELECT sum(x)`, `SELECT avg(x)`, `SELECT max(x)` sin WHERE: el plan
es estructuralmente equivalente — un `Aggregate` sobre un scan
completo.

En tablas de millones de filas esto suele ser un dolor crónico de
dashboards y heartbeats que ejecutan el conteo cada N segundos.

## Cómo aparece en el plan

Con paralelismo (lo común en tablas grandes):

```
Aggregate (Strategy=Plain, Partial Mode=Finalize)
  Gather (Workers Planned=2..N)
    Aggregate (Strategy=Plain, Partial Mode=Partial)
      Seq Scan on tabla_grande  (Parallel Aware=true, sin Filter)
```

Sin paralelismo:

```
Aggregate (Strategy=Plain)
  Seq Scan on tabla_grande  (sin Filter)
```

Lo distintivo:
- Raíz `Aggregate` con `Strategy=Plain` y sin `Group Key`.
- Bajo el subárbol hay scan(s) sobre **una sola** relación.
- Ninguno de esos scans tiene `Filter`, `Index Cond` ni `Recheck Cond`.
- No hay joins (la query no cruza tablas).

## Regla de detección

1. Raíz es `Aggregate` con `strategy == "Plain"` y `group_key` vacío.
2. `find_nodes(root, join_types)` está vacío (sin joins en el subárbol).
3. `find_nodes(root, scan_types)` devuelve al menos un scan; todos
   apuntan a la **misma relación** y ninguno tiene predicados.
4. La relación tiene `sizes[t].estimated_rows >= 100_000` en el snapshot.

Confianza 0.95: la forma del plan es estructural y unívoca.

## Recomendación

El detector emite hasta tres alternativas en `evidence["matches"][0]
["suggested_alternatives"]`:

1. **`pg_class.reltuples` para conteo aproximado O(1).**
   ```sql
   SELECT reltuples::bigint FROM pg_class WHERE relname = 'tabla';
   ```
   Costo despreciable. Precisión: actualizada por `ANALYZE`/`VACUUM`,
   típicamente <5% de error sobre tablas estables.

2. **Tabla materializada de contadores.** Una tabla con
   `(entity, count)` mantenida por triggers `AFTER INSERT/DELETE` en
   la tabla origen. Costo de escritura constante; lectura O(1) y
   exacta.

3. **Filtrar la query si el caso de uso lo permite.** A veces el
   conteo total es accidental — el dashboard solo necesita "filas
   creadas hoy".

La decisión final entre las tres la negocia el LLM (con el contexto
del usuario) o se deja al recomendador cuando aterricen plantillas
específicas para D22.

## Falsos positivos conocidos

- **Aplica también a `sum`, `avg`, `max`, `min` sin WHERE.** No es un
  FP — el plan es idéntico y el anti-pattern (full scan para producir
  un escalar) también. La prosa del LLM debe moderar la
  recomendación de `pg_class.reltuples` en esos casos (no es
  intercambiable con `sum`).
- **Tabla pequeña.** El umbral `LARGE_TABLE_MIN_ROWS = 100_000` filtra
  tablas chicas donde el conteo es barato (un Seq Scan de 50k filas
  toma decenas de ms).
- **Si el planner usa `Index Only Scan` con visibility map al 100%**
  (tabla append-only, `VACUUM` reciente), el costo real puede bajar
  mucho. El detector sigue disparando — la recomendación
  `pg_class.reltuples` sigue siendo más barata.

## Ejemplo de query

```sql
-- Q20 plantada en AppDB v1
SELECT count(*) FROM posts;
```

## Ejemplo de plan

Con paralelismo (forma típica sobre tablas grandes en AppDB v1):

```json
{
  "Plan": {
    "Node Type": "Aggregate",
    "Strategy": "Plain",
    "Partial Mode": "Finalize",
    "Plan Rows": 1,
    "Plan Width": 8,
    "Plans": [
      {
        "Node Type": "Gather",
        "Workers Planned": 2,
        "Plans": [
          {
            "Node Type": "Aggregate",
            "Strategy": "Plain",
            "Partial Mode": "Partial",
            "Plans": [
              {
                "Node Type": "Seq Scan",
                "Parallel Aware": true,
                "Relation Name": "posts",
                "Plan Rows": 250000,
                "Plan Width": 0
              }
            ]
          }
        ]
      }
    ]
  }
}
```

Lo que D22 evalúa:

- Raíz `Aggregate` con `Strategy="Plain"` y sin `Group Key` ✓
- `find_nodes(root, join_types)` está vacío (no hay joins) ✓
- Hay un único `Seq Scan` sobre `posts`, sin `Filter`/`Index Cond`/
  `Recheck Cond` ✓
- `sizes["public.posts"].estimated_rows >= 100_000` ✓
- ⇒ `Detection(found=True, confidence=0.95, evidence={"matches": [{table: "public.posts", estimated_rows: 500000, scan_node_type: "Seq Scan", suggested_alternatives: (...)}]})`

## Validación

- **Sandbox:** la alternativa `pg_class.reltuples` es trivialmente
  equivalente en costo (lookup O(1) sobre catálogo); el sandbox puede
  comparar costo del plan original vs. una query trivial sobre
  `pg_class` para confirmar el orden de magnitud. Para la alternativa
  "tabla materializada de contadores", la validación natural es
  comparar `EXPLAIN` original con `EXPLAIN` del lookup directo sobre
  la tabla de contadores.
- **LLM (`/ia/cross_validator.py`):** la prosa explicativa se valida
  contra el snapshot — la tabla mencionada en la recomendación debe
  existir; el `pg_class.reltuples` sugerido solo se muestra si la
  alternativa cubre `count(*)` (no `sum`, `avg`, etc., donde la
  prosa debe moderarse).

## Tests

`tests/motor/detectors/test_count_star_full_table.py`:

- `test_dispara_count_star_paralelo_tabla_grande` — happy path Q20 con paralelismo
- `test_dispara_count_star_serial` — variante serial sin Gather
- `test_dispara_con_otra_agregacion_full_table` — confirma cobertura de `avg`, `sum`, etc.
- `test_no_dispara_count_con_where` — frontera con anti-patterns con filtro
- `test_no_dispara_count_con_group_by` — frontera con agregaciones por grupos
- `test_no_dispara_count_con_join` — frontera con queries multi-tabla
- `test_no_dispara_tabla_pequena` — umbral de tamaño
- `test_no_dispara_sin_aggregate_raiz` — robustez ante plans no-agregación
- `test_no_dispara_sin_tabla_en_snapshot` — abstención si no hay metadata

## Referencias

- `/motor/detectors/count_star_full_table.py` (implementación)
- `/motor/CLAUDE.md` (decisiones del módulo)
- Backlog D22 en `/PgPilot_Backlog.md`

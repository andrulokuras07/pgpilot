# CTE materializada innecesariamente

> **Detector:** `motor.detect_unnecessary_cte_materialize` (D12)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.85 (heurístico — la recomendación es segura
> en la mayoría de los casos pero el planner puede tener razón al materializar)

## Problema

Las CTEs (`WITH nombre AS (SELECT ...)`) en Postgres ≤ 11 siempre se
materializaban como tablas temporales internas. Esto creaba un
"optimization fence": el planner no podía empujar predicados del
query exterior hacia dentro de la CTE ni fusionar los dos plans.

Desde Postgres 12, el comportamiento por defecto cambió: una CTE
simple, no recursiva, referenciada una sola vez puede ser **inlineada**
— el planner la trata como un subquery y puede optimizar la query
entera como un bloque. Sin embargo, si el desarrollador escribe
`WITH cte AS MATERIALIZED (...)`, o si el planner heurísticamente
decide materializarla, el resultado en el plan es un nodo `CTE Scan`.

Cuando un `CTE Scan` aparece en el plan y la CTE se usa solo una vez
y no es recursiva, probablemente vale la pena forzar el inline con
`WITH cte AS NOT MATERIALIZED (...)`. Esto permite al planner empujar
predicados, reordenar joins y estimar cardinalidades correctamente a
través de la frontera de la CTE.

Impacto práctico: en queries con CTEs que filtran tablas grandes,
materializar innecesariamente fuerza un scan completo de la CTE antes
de aplicar el filtro exterior. `NOT MATERIALIZED` puede reducir el
costo en 5x–100x en esos casos.

## Cómo aparece en el plan

El plan contiene un nodo de tipo `CTE Scan` con campo `CTE Name`:

```json
{
  "Node Type": "CTE Scan",
  "CTE Name": "recent_posts",
  "Plan Rows": 500,
  "Total Cost": 10.0
}
```

Si la misma CTE aparece dos veces como `CTE Scan` con el mismo
`CTE Name`, la materialización está justificada (el resultado se
reutiliza). D12 solo reporta las CTEs con exactamente un `CTE Scan`.

Si el plan contiene un nodo `Recursive Union` en cualquier lugar,
el detector no reporta nada: hay una CTE recursiva en la query y
no podemos distinguir cuál nodo `CTE Scan` corresponde a la recursiva
sin más contexto.

## Regla de detección

Pseudocódigo (mapea contra
`motor/detectors/unnecessary_cte_materialize.py`):

```
cte_scan_nodes = find_nodes(plan, "CTE Scan")
si no hay cte_scan_nodes: devolver found=False

is_recursive = bool(find_nodes(plan, "Recursive Union"))
si is_recursive: devolver found=False  # conservador

cte_reference_count = {}
para cada nodo en cte_scan_nodes:
    cte_reference_count[nodo.cte_name] += 1

matches = []
para cada nodo en cte_scan_nodes (deduplicando por cte_name):
    si cte_reference_count[cte_name] > 1: skip  # reutilizada → útil
    matches.append({ cte_name, reference_count: 1, node_type, plan_rows })

devolver Detection(found=bool(matches), confidence=0.85,
                   evidence={"matches": matches})
```

## Recomendación

Agregar `NOT MATERIALIZED` a la CTE detectada:

```sql
-- Antes (materializada, optimization fence):
WITH recent_posts AS (
    SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '7 days'
)
SELECT u.name, p.title
FROM recent_posts p
JOIN users u ON u.id = p.author_id
WHERE u.country = 'MX';

-- Después (inlineada, el planner puede empujar el filtro de users):
WITH recent_posts AS NOT MATERIALIZED (
    SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '7 days'
)
SELECT u.name, p.title
FROM recent_posts p
JOIN users u ON u.id = p.author_id
WHERE u.country = 'MX';
```

La sintaxis `AS NOT MATERIALIZED` está disponible desde Postgres 12.
Para Postgres ≤ 11 no hay fix sin reescribir la CTE como subquery.

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- En sandbox, correr `EXPLAIN` con la versión `NOT MATERIALIZED` y
  comparar el costo total. Si el costo baja → recomendación válida.
- Si el costo sube (el planner tenía razón al materializar), descartar
  la sugerencia. El sandbox es la última instancia de validación.
- El LLM explica el trade-off en prosa; el motor da el veredicto.

## Falsos positivos conocidos

- **Planner con razón al materializar.** El heurístico de Postgres 12+
  puede decidir materializar porque estima que el resultado se
  accederá múltiples veces internamente (por ejemplo, en un plan con
  muchos loops). La confianza 0.85 (no 1.0) refleja esto: el sandbox
  debe confirmar antes de mostrar la sugerencia al usuario.
- **CTEs con efectos secundarios.** Si la CTE contiene un INSERT,
  UPDATE o DELETE (CTEs DML), debe materializarse. D12 no parseea el
  SQL para detectar esto (solo ve el plan), así que podría reportar
  un falso positivo. En AppDB v1 todas las queries son SELECT; para
  queries con DML el recomendador debe añadir esta verificación.
- **CTE referenciada en múltiples subqueries dentro del mismo plan.**
  El contador de referencias usa los nodos `CTE Scan` en el árbol.
  Si una CTE se referencia en un subplan que no aparece como `CTE Scan`
  en el plan visible, el recuento podría ser incompleto. En la práctica
  Postgres siempre emite un `CTE Scan` por referencia; este FP es
  teórico.

## Ejemplo de query

```sql
-- CTE materializada innecesariamente: se usa una sola vez
WITH active_users AS (
    SELECT id, name FROM users WHERE is_active = true
)
SELECT p.title, au.name
FROM posts p
JOIN active_users au ON au.id = p.author_id
WHERE p.created_at > '2024-01-01';
```

El plan materializa `active_users` antes de aplicar el filtro
`p.created_at > ...`. Con `NOT MATERIALIZED`, el planner puede
fusionar todo y posiblemente usar un índice sobre `posts.created_at`
directamente.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Hash Join",
    "Plans": [
      {
        "Node Type": "CTE Scan",
        "CTE Name": "active_users",
        "Plan Rows": 50000,
        "Total Cost": 1200.0
      },
      {
        "Node Type": "Seq Scan",
        "Relation Name": "posts",
        "Filter": "(created_at > '2024-01-01')",
        "Plan Rows": 10000,
        "Total Cost": 800.0
      }
    ]
  }
}
```

D12 evalúa:
- Nodo `CTE Scan` con `CTE Name = "active_users"` ✓
- Sin `Recursive Union` en el plan ✓
- `active_users` aparece solo una vez ✓
- ⇒ `Detection(found=True, confidence=0.85, evidence={"matches": [{cte_name: "active_users", reference_count: 1, ...}]})`

## Tests

`tests/motor/detectors/test_unnecessary_cte_materialize.py`. Cubre:

- Happy path: CTE Scan referenciada una vez, sin recursión → dispara.
- Happy path 2: dos CTEs distintas, cada una una vez → dos matches.
- Negativo: plan sin CTE Scan → no dispara.
- Negativo: CTE referenciada dos veces (misma `cte_name`) → no dispara.
- Negativo: plan con `Recursive Union` → no dispara (conservador).
- Negativo: plan con `Recursive Union` + CTE simple → no dispara
  (el detector es conservador cuando hay recursión en cualquier lugar).
- Robustez: `CTE Name` ausente → no rompe el detector.
- Robustez: CTE Scan profundo en el árbol → `find_nodes` lo localiza
  en DFS.

## Referencias

- `/motor/detectors/unnecessary_cte_materialize.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_unnecessary_cte_materialize`)
- Backlog `D12` en `/PgPilot_Backlog.md`
- Postgres docs:
  [WITH Queries (Common Table Expressions)](https://www.postgresql.org/docs/current/queries-with.html)
- Release notes de Postgres 12: cambio en materialización por defecto.

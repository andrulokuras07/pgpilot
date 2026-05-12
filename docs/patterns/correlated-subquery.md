# Subquery correlacionada

> **Detector:** `motor.detect_correlated_subquery` (D7)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.95 (estructural, sin regex)

## Problema

Una subquery correlacionada
(`WHERE col > (SELECT avg(col) FROM t WHERE t.fk = outer.id)`) se
evalúa **una vez por cada fila** de la query externa. Si la externa
devuelve 1 M de filas, la subquery se ejecuta 1 M de veces — incluso
si el costo individual es bajo, el total se vuelve cuadrático en
tablas no triviales. Es el anti-pattern más caro del catálogo en
términos de impacto P99 sobre tablas grandes.

La reescritura suele ser un `JOIN` con `GROUP BY` o un `EXISTS` que
deja al planner decidir el orden de ejecución. Postgres tiene mucha
más libertad cuando ve la operación como una sola unidad relacional.

## Cómo aparece en el plan

Postgres etiqueta cada subquery con un nombre interno:

- `SubPlan N`: subquery correlacionada (re-ejecutada por fila).
- `InitPlan N`: subquery **no** correlacionada (una sola evaluación
  al inicio del plan).
- `hashed SubPlan`: SubPlan optimizado con hash (caso especial,
  todavía cuenta como SubPlan).

El detector dispara solo si `node.subplan_name` contiene la cadena
`"SubPlan"` (matchea `SubPlan 1`, `hashed SubPlan 2`, etc.) y NO
matchea `InitPlan`. Esta distinción es lo que hace al detector
correcto sin falsos positivos sobre subqueries inocuas.

## Regla de detección

Pseudocódigo (mapea contra `motor/detectors/correlated_subquery.py`):

```
recorrer árbol DFS:
    si node.subplan_name contiene "SubPlan":
        outer_table = primera relación encontrada recorriendo hijos
        matches.append({
            subplan_name, node_type,
            inner_table: node.relation_name,
            outer_table,
        })

devolver Detection(found=bool(matches), confidence=0.95, evidence={"matches": matches})
```

A diferencia de los otros tres detectores nuevos (D4/D5/D6), D7 no
usa regex sobre texto: lee `node.subplan_name` directo del atributo
tipado de `PlanNode`. Es el detector más fiel al espíritu de R2 en
el módulo.

## Recomendación

(Pendiente integración con `motor/recommender.py`.) Recomendación
textual: reescribir como `JOIN` (con `GROUP BY` cuando hay agregados)
o `EXISTS`/`NOT EXISTS` (cuando la subquery es solo un check de
presencia). El SQL alternativo lo propone el LLM (`/ia`) y se valida
contra el snapshot y el sandbox antes de mostrarlo (R3).

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- Antes/después: correr el `EXPLAIN ANALYZE` original y el de la
  versión reescrita en sandbox; el `Execution Time` debería caer
  fuertemente y desaparecer el nodo con `Subplan Name: SubPlan N`.
- LLM: `/ia/cross_validator.py` valida que las tablas y columnas
  mencionadas en la reescritura existan en el snapshot. Si el LLM
  inventa un JOIN sobre una FK inexistente, la sugerencia se descarta.

## Falsos positivos conocidos

- **El detector reporta presencia, no impacto.** Una subquery
  correlacionada sobre una tabla externa de 10 filas es prácticamente
  gratis. D7 dispara igual; el recomendador debería ponderar con el
  tamaño de la outer (via snapshot) antes de emitir prosa enfática.
- **`hashed SubPlan` es un caso optimizado.** Postgres a veces
  detecta que el SubPlan puede materializarse y reusarse con hash,
  bajando el costo. D7 sigue disparando porque el nombre contiene
  `"SubPlan"`. La distinción de impacto vive en el sandbox/recomendador.
- **`outer_table` se aproxima por DFS al primer hijo con
  `relation_name`.** Si el SubPlan cuelga de un join complejo, el
  outer reportado puede no ser la "tabla principal" intuitiva. Es
  best-effort para la prosa, no parte del criterio de detección.

## Ejemplo de query

```sql
SELECT u.id, u.name
FROM users u
WHERE u.salary > (
  SELECT avg(salary)
  FROM users u2
  WHERE u2.department_id = u.department_id   -- correlación con u
);
```

Por cada fila de `users` (potencialmente millones), la subquery se
re-evalúa filtrando por `department_id`. Si hay 10 departamentos y 1 M
de empleados, la subquery corre 1 M de veces a pesar de que solo hay
10 valores únicos posibles del agregado.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Seq Scan",
    "Relation Name": "users",
    "Alias": "u",
    "Filter": "(salary > (SubPlan 1))",
    "Plans": [
      {
        "Node Type": "Aggregate",
        "Subplan Name": "SubPlan 1",
        "Parent Relationship": "SubPlan",
        "Strategy": "Plain",
        "Plans": [
          {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Alias": "u2",
            "Filter": "(department_id = u.department_id)"
          }
        ]
      }
    ]
  }
}
```

D7 evalúa:

- DFS encuentra el nodo `Aggregate`.
- `node.subplan_name = "SubPlan 1"` contiene `"SubPlan"` ✓
- `outer_table = "users"` (recorriendo hijos del nodo SubPlan)
- ⇒ match con `subplan_name="SubPlan 1"`, `inner_table=None` (el
  Aggregate no tiene `relation_name`), `outer_table="users"`.

## Tests

`tests/motor/detectors/test_correlated_subquery.py`. Cubre:

- Happy path: `Aggregate` con `Subplan Name: "SubPlan 1"` →
  dispara con `subplan_name="SubPlan 1"`.
- Negativo: plan simple `Seq Scan` sin subqueries → no dispara.
- Negativo (frontera): `CTE Scan` con `cte_name` pero sin
  `subplan_name` → no dispara.
- Múltiples SubPlans en un mismo plan
  (`"SubPlan 1"` + `"SubPlan 2"`) → dos matches con nombres
  distintos.
- **Negativo crítico (frontera con InitPlan):** `Aggregate` con
  `Subplan Name: "InitPlan 1"`, `Parent Relationship: "InitPlan"`
  → **no** dispara. Esto valida que el detector distingue
  correlacionado de no-correlacionado.

## Referencias

- `/motor/detectors/correlated_subquery.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_correlated_subquery`)
- Backlog `D7` en `/PgPilot_Backlog.md`
- Postgres docs:
  [`SubPlan` vs `InitPlan`](https://www.postgresql.org/docs/current/using-explain.html)

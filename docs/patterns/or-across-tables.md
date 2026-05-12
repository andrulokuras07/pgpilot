# OR sobre columnas de tablas distintas

> **Detector:** `motor.detect_or_across_tables` (D6)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.85 (heurístico estructural)

## Problema

Un `WHERE` con `OR` que cruza tablas
(`WHERE t1.status = 1 OR t2.category = 'news'`) le bloquea al
planner cualquier estrategia con índice: no puede usar índices de
`t1` (no aplican cuando se cumple solo la condición de `t2`) ni de
`t2`. El resultado es un `Hash Join` o `Nested Loop` que recorre el
producto cartesiano filtrado en memoria — barato en datasets de
prueba, brutal cuando las tablas crecen.

La reescritura canónica es separar las dos ramas con `UNION`:

```sql
SELECT ... FROM t1 JOIN t2 ON ... WHERE t1.status = 1
UNION
SELECT ... FROM t1 JOIN t2 ON ... WHERE t2.category = 'news'
```

Cada rama puede usar su índice y el resultado se deduplica al final
(o `UNION ALL` si la lógica permite duplicados). En benchmarks
típicos esto es 10×–100× más rápido sobre tablas grandes.

## Cómo aparece en el plan

El `OR` viaja al campo `Filter` del nodo join (o, defensivamente,
del `Seq Scan` inferior cuando el planner decide evaluarlo abajo):

- `Hash Join` con `Filter: ((t1.status = 1) OR (t2.category = 'news'))`
- `Nested Loop` con el mismo patrón
- `Seq Scan` con un OR que mezcla referencias `tabla.col` de
  ≥2 tablas distintas

El detector parte el filtro por `\bOR\b` y, en cada lado, extrae
todas las referencias `tabla.columna`. Si entre todos los lados
aparecen ≥2 nombres de tabla/alias distintos, dispara.

## Regla de detección

Pseudocódigo (mapea contra `motor/detectors/or_across_tables.py`):

```
para cada nodo en find_nodes(plan, {Nested Loop, Hash Join, Merge Join, Seq Scan}):
    expr = node.filter
    si expr es None o no contiene \bOR\b: skip
    partes = split(expr, /\bOR\b/i)
    tablas = {}
    para cada parte en partes:
        para cada match `(\w+)\.(\w+)` en parte:
            tablas.add(match.group(1))
    si len(tablas) >= 2:
        matches.append({tables: sorted(tablas), filter, node_type})

devolver Detection(found=bool(matches), confidence=0.85, evidence={"matches": matches})
```

## Recomendación

(Pendiente integración con `motor/recommender.py`.) Recomendación
textual: reescribir como `UNION` (o `UNION ALL` si la lógica del
negocio permite duplicados). El detector no genera el SQL alternativo
automáticamente — eso lo propone el LLM (`/ia`) y se valida cruzando
con el snapshot y el sandbox antes de mostrarlo.

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- Antes/después: correr el `EXPLAIN` original y el de la versión con
  `UNION` en sandbox, comparar costos. El verdict se incluye en la
  recomendación.
- LLM: `/ia/cross_validator.py` valida que las tablas y columnas que
  el LLM mencione en la reescritura existan en el snapshot; si no,
  se descarta y se cae a la prosa de plantilla.

## Falsos positivos conocidos

- **Esquema explícito en el SQL.** Si la query usa
  `schema.tabla.col`, el regex `(\w+)\.(\w+)` captura `schema.tabla`
  como una "tabla". En AppDB v1 (todo `public`) no aplica. Mitigación
  cuando importe: capturar `Schema` en `PlanNode` y normalizar.
- **OR con un solo lado calificado.** Si el filtro es
  `(t1.status = 1) OR (status = 'admin')` (segundo sin prefijo), el
  detector cuenta una sola tabla y no dispara. Falso negativo por
  diseño: sin prefijo no hay evidencia estructural.
- **OR dentro de una subquery escalar.** Si el OR vive en un
  `SubPlan`, viaja en el `Filter` del nodo del subplan; el detector
  lo capta solo si ese nodo está en la lista de tipos soportados.
- **El detector reporta alias, no tabla física.** En el output,
  `tables: ["t1", "t2"]` puede requerir cruzar con `node.relation_name`
  / `node.alias` para resolver a tabla real cuando el frontend lo
  muestre.

## Ejemplo de query

```sql
SELECT p.id, p.title
FROM posts p
JOIN comments c ON c.post_id = p.id
WHERE p.status = 1 OR c.category = 'news';
```

`posts` y `comments` tienen índices respectivos sobre `status` y
`category`. El planner no puede usar ninguno porque el OR cruza las
dos tablas.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Hash Join",
    "Hash Cond": "(p.id = c.post_id)",
    "Filter": "((p.status = 1) OR (c.category = 'news'))",
    "Plans": [
      { "Node Type": "Seq Scan", "Relation Name": "posts", "Alias": "p" },
      { "Node Type": "Hash",
        "Plans": [
          { "Node Type": "Seq Scan", "Relation Name": "comments", "Alias": "c" }
        ]
      }
    ]
  }
}
```

D6 evalúa:

- Nodo `Hash Join` ✓
- `node.filter` contiene `OR` ✓
- Partes: `["((p.status = 1) ", " (c.category = 'news'))"]`
- Tablas extraídas: `{"p", "c"}` ⇒ 2 ⇒ dispara con
  `tables=["c", "p"]`.

## Tests

`tests/motor/detectors/test_or_across_tables.py`. Cubre:

- Happy path: `Hash Join` con `(t1.status = 1) OR (t2.category = 'x')`
  → dispara con `tables = {"t1", "t2"}`.
- Negativo: OR sobre columnas de la misma tabla
  (`(users.status = 1) OR (users.role = 'admin')`) → no dispara.
- Negativo: `Hash Join` con `AND` en vez de `OR` → no dispara.
- Negativo: `Hash Join` sin `Filter` → no dispara.
- Negativo: OR sin calificadores de tabla
  (`(status = 1) OR (role = 'admin')`) → no dispara (sin evidencia
  estructural de cruce).

## Referencias

- `/motor/detectors/or_across_tables.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_or_across_tables`)
- Backlog `D6` en `/PgPilot_Backlog.md`
- Postgres docs:
  [`UNION` vs `OR`](https://www.postgresql.org/docs/current/queries-union.html)

# NOT IN con subquery sobre columna nullable

> **Detector:** `motor.detect_not_in_nullable_subquery` (D21)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.95
> **Severidad:** ALTA (bug silencioso + performance)

## Problema

`WHERE col NOT IN (SELECT inner_col FROM t)` tiene dos problemas
graves cuando `inner_col` admite NULL:

### 1. Bug silencioso (lo serio)

SQL usa lógica trivaluada. Si la subquery interna devuelve aunque sea
un solo NULL, el resultado completo de la query externa es **vacío**,
sin error visible. La razón:

```
x NOT IN (a, b, NULL)
≡ x <> a  AND  x <> b  AND  x <> NULL
≡ x <> a  AND  x <> b  AND  UNKNOWN
≡ UNKNOWN o FALSE      ← nunca TRUE
```

Resultado típico: "el reporte aparece en blanco después de un deploy"
y el equipo busca durante horas un bug de aplicación que en realidad
es semántica de SQL.

### 2. Performance

Postgres **no puede** convertir `NOT IN` a `Anti Join` cuando la
columna interna es nullable (la conversión cambiaría la semántica por
la regla de arriba). El plan típico es `SubPlan` o `hashed SubPlan`
sin short-circuit posible. `NOT EXISTS` no tiene esta restricción y
permite Anti Join eficiente.

## Cómo aparece en el plan

D21 **no usa el plan** — la señal vive en SQL + snapshot. Pero a
título informativo, el plan de Q19 muestra un `SubPlan` (lo que D7
detecta a nivel plan):

```jsonc
{
  "Plan": {
    "Node Type": "Seq Scan",
    "Relation Name": "users",
    "Filter": "(NOT (hashed SubPlan 1))",
    "Plans": [
      {
        "Node Type": "Seq Scan",
        "Relation Name": "posts",
        "Subplan Name": "SubPlan 1",
        "Parent Relationship": "SubPlan"
      }
    ]
  }
}
```

D7 dispara por el `SubPlan`; D21 complementa con la explicación
específica del NULL trap. Ambos son TP.

## Regla de detección

Pseudocódigo (ver `motor/detectors/not_in_nullable_subquery.py`):

```
for select in sqlglot_parse(sql).find_all(Select):
    for in_expr in select.WHERE.find_all(In):
        if not is_negated(in_expr):              continue  # → D20
        subquery = in_expr.query
        if subquery is None:                     continue  # NOT IN (lit)
        if is_correlated(subquery, outer_tables): continue  # → D7
        inner_table  = first_from_table(subquery)
        inner_column = first_projected_column(subquery)  # Column simple
        is_nullable = snapshot["schema"][table]["columns"][...]["is_nullable"]
        if is_nullable is not True:              continue  # NOT NULL: ok
        match! → suggested_rewrite con NOT EXISTS correlacionado
```

La detección usa la firma extendida `sql=` (igual que D9/D19/D20)
porque la información de nullability **y** la distinción
`IN`/`NOT IN` no son recuperables desde el plan — la primera vive en
el catálogo (B2) y la segunda Postgres ya la resolvió antes del
EXPLAIN.

## Recomendación

Rewrite del SQL: `NOT IN (SELECT col FROM t WHERE ...)` →
`NOT EXISTS (SELECT 1 FROM t WHERE t.col = outer_col AND ...)`.

```sql
-- Original (bug + lento):
SELECT id FROM users
WHERE id NOT IN (SELECT author_id FROM posts);

-- Rewrite propuesto:
SELECT id FROM users
WHERE NOT EXISTS (
  SELECT 1 FROM posts WHERE posts.author_id = users.id
);
```

El rewrite arregla el bug semántico (NOT EXISTS es binario, no
trivaluado) y habilita Anti Join para performance. El
`suggested_rewrite` en `evidence` es SQL completo y parseable con
sqlglot.

## Falsos positivos conocidos

- **Si el dueño del schema sabe que la subquery nunca devuelve NULL en
  la práctica** (sin restricción NOT NULL pero por convención de
  app), D21 sigue disparando. Es correcto desde la perspectiva del
  motor: la garantía no está en el schema y un cambio futuro podría
  introducir NULLs sin avisar. La recomendación sigue siendo válida
  (NOT EXISTS también es más rápido).
- **Proyección con expresión (`COALESCE(col, 0)`, `col + 1`):** D21
  se abstiene — no podemos razonar estructuralmente sobre la
  nullability del resultado. Falso negativo voluntario para evitar
  recomendaciones inválidas.
- **El rewrite reemplaza el WHERE completo del outer.** Si la query
  tiene `WHERE status = 1 AND id NOT IN (...)`, el rewrite de D21
  pierde la condición extra. Limitación heredada de D20.
- **Resolución por nombre corto.** Si dos schemas distintos tienen
  una tabla con el mismo nombre y solo uno está en `public`, D21
  prefiere `public.<tabla>`. Si ninguno está en `public`, toma el
  primero por orden de iteración del dict. En AppDB v1 (un solo
  schema `public`) no es un riesgo; queda registrado para v2.

## Ejemplo de query

```sql
-- Q19 plantada en AppDB v1
SELECT id FROM users
WHERE id NOT IN (SELECT author_id FROM posts)
LIMIT 10;
```

`posts.author_id` es nullable por diseño en AppDB v1 (los posts de
usuarios borrados pueden quedar con `author_id IS NULL`), por lo que
la trampa NULL es real y reproducible.

## Frontera con detectores hermanos

- **D7 (`detect_correlated_subquery`):** dispara en Q19 a nivel plan
  porque Postgres emite `SubPlan` para resolver el `NOT IN`. La
  coexistencia es intencional — regla #1 del proyecto: el motor
  reporta hechos estructurales y la capa de prosa prioriza. D7 dice
  "hay un SubPlan"; D21 dice "es específicamente el NULL trap, con
  bug silencioso".
- **D20 (`detect_in_subquery_to_exists`):** cubre `IN`, no `NOT IN`.
  La exclusión es por construcción: `_is_negated` filtra opuestos.
  Mutuamente excluyentes.

## Tests

`tests/motor/detectors/test_not_in_nullable_subquery.py`. Cubre:

- Happy path Q19 → dispara con `null_trap=True`, confianza 0.95.
- Q19 con LIMIT → idéntico (el LIMIT no afecta la detección).
- Rewrite parseable con sqlglot y con `NOT EXISTS`, sin `NOT IN`.
- Columna NOT NULL → no dispara (no hay trampa).
- `IN` sin `NOT` → no dispara (territorio de D20).
- `NOT IN (1, 2, 3)` lista literal → no dispara.
- Subquery correlacionada → no dispara (territorio de D7).
- Sin SQL / SQL inválido / snapshot vacío / tabla desconocida →
  abstención silenciosa (no FP).
- Proyección con expresión (`COALESCE`) → no dispara.
- Resolución de tabla por nombre corto cuando el snapshot solo tiene
  el schema no-`public`.

## Referencias

- `/motor/detectors/not_in_nullable_subquery.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_not_in_nullable_subquery`)
- Backlog `D21` en `/PgPilot_Backlog.md`
- Postgres docs: [Subquery Expressions — NOT IN](https://www.postgresql.org/docs/current/functions-subquery.html)
- Postgres docs: [Boolean Logic with NULLs](https://www.postgresql.org/docs/current/functions-comparison.html)
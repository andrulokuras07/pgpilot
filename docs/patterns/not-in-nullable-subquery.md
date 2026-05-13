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

D21 **no usa el plan** — la señal vive en SQL + snapshot
(`is_nullable` viene del catálogo vía B2; no aparece en EXPLAIN).
El plan de Q19 (mostrado abajo en `## Ejemplo de plan`) sí contiene un
`SubPlan` que D7 captura a nivel estructura; D21 complementa con la
explicación específica del NULL trap. Ambos detectores son TP sobre
Q19 — coexisten por diseño (D7 dice "hay un SubPlan", D21 dice "es
específicamente el NULL trap, con bug silencioso").

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

## Validación

- **Sandbox:** correr `EXPLAIN ANALYZE` de la query original
  (`NOT IN`) y del rewrite (`NOT EXISTS`) sobre el schema temporal.
  El rewrite se valida si:
  1. El `Execution Time` baja (típico: el planner puede usar Anti
     Join sobre `NOT EXISTS`, lo cual era imposible con `NOT IN` sobre
     columna nullable).
  2. La forma estructural del plan cambia: el `SubPlan`/`hashed SubPlan`
     desaparece y aparece un `Anti Join` (Hash o Nested Loop).
  Si el plan no muestra el cambio estructural, la validación falla y
  se reporta — la recomendación se conserva como prosa explicativa
  pero no se ofrece como acción ejecutable.
- **LLM (`/ia/cross_validator.py`):** valida que la tabla y la columna
  del `NOT EXISTS` existan en el snapshot. La correlación del rewrite
  (`t.col = outer.col`) se chequea: si el LLM rompe la correlación
  proponiendo un EXISTS no correlacionado, la sugerencia se descarta
  porque cambia la semántica.
- **Nota crítica de R3 + R4:** D21 detecta un **bug semántico real**,
  no solo un problema de performance. La validación con sandbox debe
  además ejecutar la query original y la reescrita sobre un par de
  datos sintéticos que incluyan al menos un NULL en la columna interna
  para confirmar que los resultados son distintos (el original devuelve
  vacío, el rewrite devuelve filas). Esta verificación queda como
  trabajo de C3 cuando el sandbox aterrice datos sintéticos para
  validar semántica además de costo.

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

## Ejemplo de plan

Plan de Q19 emitido por Postgres 16 sobre AppDB v1:

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

A título informativo: D21 **no inspecciona este plan**. La detección
vive 100% en SQL + snapshot (`is_nullable` viene del catálogo vía B2).
El plan se incluye para entender la frontera con D7 (que sí dispara
estructuralmente por el `SubPlan`) y para que el lector vea por qué
el rewrite a `NOT EXISTS` habilita Anti Join — Postgres podrá
sustituir el `SubPlan` por un nodo `Hash Anti Join` o `Nested Loop
Anti Join` cuando la nullability deje de ser un riesgo semántico.

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
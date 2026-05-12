# SELECT * con pocas columnas usadas

> **Detector:** `motor.detect_select_star` (D9)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.85 (parser SQL via sqlglot)

## Problema

`SELECT *` trae todas las columnas de la tabla aun cuando la query
solo usa unas pocas. Costos concretos:

- **Más bytes por fila** moviéndose desde disco al cliente.
- **Imposibilidad de `Index Only Scan`:** el planner descarta
  índices cubrientes porque el `*` exige columnas que no están en
  el índice — fuerza un `Index Scan` con heap fetch por fila.
- **Plan frágil ante DDL:** cuando se agrega una columna nueva a
  la tabla (un `BLOB`, un `JSONB` grande), todos los `SELECT *` que
  vivan en el código bajan de performance sin que nadie lo cambie.

La reescritura es la más simple de todo el catálogo: listar
explícitamente las columnas que la query usa. Si esas columnas
caben en un índice existente, además habilita `Index Only Scan` —
salto de performance de 10× típico.

## Cómo aparece en el plan

**Aquí está la trampa:** el plan **no** muestra `SELECT *`.
Postgres ya resolvió la lista de proyección antes de generar el
EXPLAIN, así que `Output` (cuando EXPLAIN se corre con `VERBOSE`)
lista las columnas reales, no el `*` original.

Por eso D9 es **el único detector del módulo con firma extendida**:
acepta la query sanitizada como argumento adicional para parsearla
con `sqlglot`. Sin SQL, el detector se abstiene.

## Regla de detección

Pseudocódigo (mapea contra `motor/detectors/select_star.py`):

```
firma: detect_select_star(plan, snapshot, *, sql=None)

si sql es None: devolver found=False, matches=[]

intentar parsear el SQL con sqlglot:
    en caso de ParseError: devolver found=False, matches=[]

para cada nodo Select en el árbol AST:
    si la lista de proyección contiene `Star` (no calificado) o
       `Column(this=Star)` (`tabla.*`):
        scanned = primera relación encontrada en el plan (DFS)
        index_only_candidate = existe al menos un Index Scan en el plan
        matches.append({table: scanned, index_only_candidate, from_text})

devolver Detection(found=bool(matches), confidence=0.85, evidence={"matches": matches})
```

## Recomendación

(Pendiente integración con `motor/recommender.py`.) Dos niveles:

1. **Reescritura mínima:** listar las columnas explícitamente.
   El LLM (`/ia`) genera la versión con columnas a partir del SQL
   sanitizado, y se valida cruzando contra el snapshot.
2. **Índice cubriente (opcional):** si `index_only_candidate == True`
   y las columnas listadas caben en un índice existente con
   `INCLUDE`, recomendar la versión con cubriente.

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- LLM: `/ia/cross_validator.py` valida que las columnas en la
  reescritura existan en el snapshot. Si el LLM inventa una columna,
  se descarta.
- Sandbox: correr `EXPLAIN` original y de la reescritura, comparar
  costos y plan node types (Index Scan → Index Only Scan cuando
  aplique).

## Falsos positivos conocidos

- **`SELECT *` justificado.** Algunos casos legítimos:
  - `INSERT INTO t SELECT * FROM staging` cuando ambas tablas son
    estructurales hermanas.
  - Vistas materializadas que reflejan la tabla original.
  - Queries diagnósticas / debugging puntual.
  El detector dispara igual; el LLM debe moderar la prosa en esos
  contextos (e.g. detectar el `INSERT INTO` que envuelve el SELECT).
- **`tabla.*` con muchas tablas.** Si la query es
  `SELECT u.*, p.id FROM users u JOIN posts p`, dispara una vez
  por el `u.*`. El contexto del JOIN hace la reescritura más
  delicada — vale anotar todas las columnas, no es trivial.
- **SQL no parseable.** sqlglot maneja PostgreSQL bastante bien
  pero tiene límites con DSLs o sintaxis muy específica
  (procedural). En esos casos, el detector se abstiene
  silenciosamente (no eleva).
- **Subqueries con `*`.** El detector recorre todos los `Select` del
  AST, incluyendo anidados. Un `*` en una subquery dispara aunque
  la outer use columnas explícitas — eso suele ser intencional
  (correcto), no FP.

## Ejemplo de query

```sql
SELECT *
FROM users
WHERE email = $LITERAL_1_0;
```

`users` tiene 30 columnas pero la app solo lee `id` y `email`.
Postgres no puede hacer `Index Only Scan` con el índice
`idx_users_email` porque `*` exige el resto.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Index Scan",
    "Relation Name": "users",
    "Index Name": "idx_users_email",
    "Index Cond": "(email = 'x'::text)",
    "Plan Rows": 1,
    "Plan Width": 200
  }
}
```

D9 evalúa:

- `sql` provisto ✓
- sqlglot parsea OK ✓
- El nodo `Select` tiene `Star` en la lista de proyección ✓
- En el plan hay un `Index Scan` ⇒ `index_only_candidate = True`.
- ⇒ `Detection(found=True, confidence=0.85, evidence={"matches": [{table: "users", index_only_candidate: True, from_text: "users"}]})`

## Tests

`tests/motor/detectors/test_select_star.py`. Cubre:

- Happy path: `SELECT *` sobre Index Scan → dispara con
  `index_only_candidate=True`.
- `SELECT u.*` (table-qualified star) → también dispara.
- Negativo: `SELECT id, email FROM ...` → no dispara.
- Negativo (robustez): `sql=None` → `found=False` sin excepción.
- Negativo (robustez): SQL no parseable → `found=False` sin excepción.
- Subquery con `*`: outer explícita + inner `*` → dispara una vez.
- `index_only_candidate=False` cuando el plan es Seq Scan.

## Referencias

- `/motor/detectors/select_star.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_select_star` — incluye nota
  sobre la convención de firma extendida)
- Backlog `D9` en `/PgPilot_Backlog.md`
- Postgres docs:
  [Index Only Scans](https://www.postgresql.org/docs/current/indexes-index-only-scans.html)

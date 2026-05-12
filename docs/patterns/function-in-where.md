# Función no-immutable en WHERE

> **Detector:** `motor.detect_function_in_where` (D5)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.9 (heurístico sobre lista cerrada de funciones)

## Problema

Aplicar una función sobre una columna en el `WHERE`
(`WHERE lower(email) = 'x@y.com'`) impide que Postgres use un índice
btree plano sobre esa columna. El índice está ordenado por los
valores originales, no por los transformados, así que el planner
descarta el índice y cae a `Seq Scan`. El síntoma típico es código
"defensivo" copiado de un tutorial — `lower(email)` para hacer match
case-insensitive — que mata la performance sin que nadie lo note
hasta que la tabla crece.

La solución no suele ser "quita la función": muchas veces la lógica
la necesita. La solución estructural es un **índice funcional**
(`CREATE INDEX ON tabla (lower(email))`).

## Cómo aparece en el plan

Postgres preserva la llamada en `Filter` del nodo scan:

- `Seq Scan` con `Filter: (lower((email)::text) = 'x'::text)`
- `Seq Scan` con `Filter: (date_trunc('month', created_at) = ...)`
- `Index Scan` con `Filter: (extract(year FROM created_at) = 2024)`

El detector lee `node.filter` (texto generado por Postgres, estable)
y busca llamadas a un conjunto cerrado de funciones típicamente
no-immutable o que rompen índices.

## Regla de detección

Pseudocódigo (mapea contra `motor/detectors/function_in_where.py`):

```
para cada nodo en find_nodes(plan, {Seq Scan, Index Scan, Index Only Scan, Bitmap Heap Scan}):
    si node.filter es None: skip
    para cada match de regex `(funcion_conocida)\s*\(` en node.filter:
        matches.append({table, function, filter, node_type})

devolver Detection(found=bool(matches), confidence=0.9, evidence={"matches": matches})
```

Funciones reconocidas (`_FUNCTION_CALL_RE`, case-insensitive):
`lower`, `upper`, `trim`, `ltrim`, `rtrim`, `btrim`, `coalesce`,
`concat`, `replace`, `substring`, `left`, `right`, `reverse`,
`length`, `date_trunc`, `extract`, `to_char`, `to_date`,
`to_timestamp`, `to_number`, `abs`, `ceil`, `floor`, `round`,
`trunc`, `regexp_replace`, `regexp_match`.

## Recomendación

(Pendiente integración con `motor/recommender.py`.) Recomendación
textual: índice funcional sobre la expresión exacta del filtro.
Ejemplo para `lower(email)`:

```sql
CREATE INDEX idx_users_lower_email ON users (lower(email));
```

Si la función ya es inmutable (la mayoría de las listadas lo son
sobre tipos básicos), Postgres usará el índice automáticamente para
filtros que repitan la misma expresión.

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- Antes/después en sandbox: aplicar el índice funcional y verificar
  que el plan pasa a `Index Scan` y el costo cae.
- LLM (`/ia/cross_validator.py`): valida que la columna mencionada
  exista; si la prosa propone un índice sobre una columna inexistente,
  se cae a la plantilla.

## Falsos positivos conocidos

- **Función sobre un literal**, no sobre la columna. Ejemplo:
  `WHERE name = lower('JOHN')`. La función es inmutable y se evalúa
  una sola vez en planning; no impide índice. Mitigación pendiente:
  parsear `node.filter` con `sqlglot` y verificar que el argumento
  sea una columna.
- **Columna llamada como una función**. Ejemplo: una tabla custom
  con columna `lower TEXT NOT NULL`. En AppDB v1 no ocurre.
- **Funciones marcadas como `IMMUTABLE`** que el optimizer ya sabe
  precomputar. Algunas funciones de la lista (como `length` o `abs`)
  son inmutables sobre tipos básicos pero igual se reportan porque
  el detector no consulta `pg_proc`. Es un FP voluntario: la
  recomendación de índice funcional sigue siendo válida; el
  recomendador debería decidir si vale la pena emitirla.
- **Funciones custom no listadas** (`mi_normalizador(col)`) no se
  detectan. Falso negativo por diseño: la lista es cerrada para
  evitar ruido. Cuando aparezca un caso real, se amplía.

## Ejemplo de query

```sql
SELECT id, email
FROM users
WHERE lower(email) = 'admin@example.com';
```

`users` tiene índice btree sobre `email` pero no sobre `lower(email)`.
El planner descarta el btree y cae a `Seq Scan`.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Seq Scan",
    "Relation Name": "users",
    "Startup Cost": 0.00,
    "Total Cost": 2543.50,
    "Plan Rows": 1,
    "Plan Width": 40,
    "Filter": "(lower((email)::text) = 'admin@example.com'::text)"
  }
}
```

D5 evalúa:

- Node Type ∈ scans soportados ✓
- `node.filter` contiene `lower(` ✓
- ⇒ match con `function="lower"`, `table="users"`.

## Tests

`tests/motor/detectors/test_function_in_where.py`. Cubre:

- `lower(email)` → dispara con `function="lower"`.
- `upper(title)` → dispara con `function="upper"`.
- `date_trunc('month', created_at)` → dispara con
  `function="date_trunc"`.
- `extract(year FROM created_at)` → dispara con `function="extract"`.
- Negativo: filtro `(author_id = 5)` (sin función) → no dispara.
- Negativo: nodo sin `Filter` → no dispara.
- Múltiples funciones en un mismo filtro
  (`(lower(email) = 'x') AND (trim(name) = 'y')`) → dos matches.

## Referencias

- `/motor/detectors/function_in_where.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_function_in_where`)
- Backlog `D5` en `/PgPilot_Backlog.md`
- Postgres docs:
  [Index on Expression](https://www.postgresql.org/docs/current/indexes-expressional.html)

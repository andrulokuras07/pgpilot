# LIKE con wildcard al inicio

> **Detector:** `motor.detect_like_leading_wildcard` (D4)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.9 (heurístico sobre texto de `Filter`)

## Problema

Una query con `WHERE col LIKE '%texto'` (o `'%texto%'`) obliga a
Postgres a examinar todas las filas: los índices btree están
ordenados por el prefijo del valor, así que un wildcard al inicio
deshace el orden y vuelve inservible al índice. El planner cae a
`Seq Scan` (o, ocasionalmente, a `Bitmap Heap Scan` con recheck que
hace el mismo trabajo en memoria).

En producción esto se manifiesta como latencia que crece linealmente
con el tamaño de la tabla — típicamente "el buscador funciona en
staging pero en prod tarda 8 s". La solución no es agregar otro
índice btree: hay que cambiar el tipo de índice o el approach de
búsqueda.

## Cómo aparece en el plan

Postgres reescribe `col LIKE '%abc'` como `col ~~ '%abc'::text` en
el campo `Filter` de los nodos scan. Por ejemplo:

- `Seq Scan` con `Filter: ((name)::text ~~ '%john'::text)`
- `Bitmap Heap Scan` con `Recheck Cond: ((email)::text ~~ '%@gmail.com'::text)`
- `Bitmap Index Scan` con `Index Cond: ...`

El detector opera sobre estos campos tipados de `PlanNode` (R2):
nunca sobre el SQL crudo del usuario.

## Regla de detección

Pseudocódigo (mapea contra
`motor/detectors/like_leading_wildcard.py`):

```
para cada nodo en find_nodes(plan, {Seq Scan, Bitmap Heap Scan, Bitmap Index Scan}):
    para cada expr en (node.filter, node.recheck_cond, node.index_cond):
        para cada match de regex `(\w+)(?:::tipo)? ~~ '%'` en expr:
            matches.append({table, column, filter, node_type})

devolver Detection(found=bool(matches), confidence=0.9, evidence={"matches": matches})
```

El regex (`_LIKE_LEADING_WILDCARD_RE`) busca específicamente el
operador `~~` seguido de `'%` para distinguir wildcard al inicio
(`'%abc'`) de wildcard al final (`'abc%'`, que sí puede usar btree).

## Recomendación

(Pendiente integración con `motor/recommender.py`.) El detector
documenta la recomendación textual: **índice de trigrams**
(`CREATE EXTENSION pg_trgm; CREATE INDEX ... USING gin (col gin_trgm_ops);`)
o **búsqueda full-text** (`tsvector` + GIN). Para casos de
autocompletado donde el prefijo varía pero el sufijo no,
`reverse(col)` + índice btree sobre la expresión también funciona.

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- Antes/después: correr `EXPLAIN` con el índice trigram aplicado en
  sandbox y verificar que el costo cae y el plan usa
  `Bitmap Index Scan` sobre el índice GIN.
- LLM (`/ia/cross_validator.py`): la prosa generada se valida
  cruzando con el snapshot — si menciona una columna que no existe,
  se cae a la plantilla.

## Falsos positivos conocidos

- **Columnas con caracteres especiales.** El regex captura `\w+`,
  por lo que columnas entrecomilladas (`"weird name"`) no se
  detectan. Falso negativo, no positivo. Acceptable para AppDB v1.
- **Operador `~~*` (ILIKE).** El detector solo busca `~~`. Si en
  AppDB v2 aparece ILIKE con wildcard al inicio, se documenta como
  ampliación pendiente.
- **`Filter: "col NOT LIKE '%abc'"`.** Postgres emite `!~~`, no
  matchea el regex. Falso negativo por diseño: NOT LIKE con wildcard
  inicial es un caso distinto (suele requerir full scan de todos
  modos, y el rewrite no es trivial).

## Ejemplo de query

```sql
SELECT id, name
FROM users
WHERE name LIKE '%admin';
```

`users` con índice btree `idx_users_name`. Postgres ignora el índice
porque el wildcard inicial deshace el orden.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Seq Scan",
    "Relation Name": "users",
    "Startup Cost": 0.00,
    "Total Cost": 1543.50,
    "Plan Rows": 1,
    "Plan Width": 32,
    "Filter": "((name)::text ~~ '%admin'::text)"
  }
}
```

Lo que D4 evalúa:

- Node Type ∈ scans soportados ✓
- `node.filter = "((name)::text ~~ '%admin'::text)"`
- Regex matchea: `column = "name"`, operador `~~`, literal empieza
  con `'%`
- ⇒ `Detection(found=True, confidence=0.9, evidence={"matches": [{table: "users", column: "name", ...}]})`

## Tests

`tests/motor/detectors/test_like_leading_wildcard.py`. Cubre:

- Happy path: `Seq Scan` con `name ~~ '%abc'` → dispara.
- Negativo (frontera): `name ~~ 'abc%'` (wildcard al final) → no
  dispara.
- Negativo (sin filtro): nodo sin `Filter` → no dispara.
- `Bitmap Heap Scan` con `Recheck Cond` → dispara (el wildcard
  puede aparecer en cualquiera de los tres campos).
- Múltiples nodos con el patrón en un mismo plan → reporta uno por
  ocurrencia.

## Referencias

- `/motor/detectors/like_leading_wildcard.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_like_leading_wildcard`)
- Backlog `D4` en `/PgPilot_Backlog.md`
- Postgres docs: [`pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html)

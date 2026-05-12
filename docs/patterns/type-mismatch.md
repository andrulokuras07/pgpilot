# Índice no usado por mismatch de tipo

> **Detector:** `motor.detect_type_mismatch` (D11)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.9 (heurístico con evidencia estructural clara)

## Problema

Cuando el tipo de dato de la columna no coincide con el tipo del valor
de comparación, Postgres aplica un cast implícito sobre la columna
antes de evaluar el filtro. Ese cast hace que el planner no pueda usar
el índice btree sobre la columna: para comparar cada entrada del índice
con el valor tendría que transformarla primero, lo que destruye la
ventaja del índice.

El resultado: Seq Scan sobre una tabla que tiene un índice perfectamente
válido, desperdiciando I/O y latencia. El problema es especialmente
silencioso porque la query devuelve resultados correctos — solo es 10x
a 1000x más lenta de lo que debería.

Ejemplo clásico: columna `status VARCHAR`, query `WHERE status::int = 1`.
Postgres hace Seq Scan aunque exista `idx_orders_status`. La fix: quitar
el cast y comparar del mismo tipo (`WHERE status = '1'`) o bien crear un
índice funcional sobre la expresión `((status)::integer)`.

## Cómo aparece en el plan

El plan muestra un nodo `Seq Scan` (o `Bitmap Heap Scan`) con un campo
`Filter` que contiene el patrón `((col)::tipo = valor)`. El doble
paréntesis y el `::` son la notación que Postgres usa para representar
un cast sobre la columna en el texto del filtro:

```
"Node Type": "Seq Scan",
"Relation Name": "orders",
"Filter": "((status)::integer = 1)"
```

Compare con el filtro normal (sin cast) donde el índice sí se usa:

```
"Node Type": "Index Scan",
"Index Cond": "(status = 'active'::text)"
```

En el caso normal, el cast `'active'::text` está sobre el **literal**,
no sobre la columna. D11 distingue estos dos casos.

## Regla de detección

Pseudocódigo (mapea contra `motor/detectors/type_mismatch.py`):

```
CAST_ON_COLUMN_RE = r"\(\((\w+)\)::(\w+)"

para cada nodo en find_nodes(plan, ["Seq Scan", "Bitmap Heap Scan", "Bitmap Index Scan"]):
    si node.filter es None: skip
    para cada match de CAST_ON_COLUMN_RE en node.filter:
        col = match.group(1)
        cast_type = match.group(2)
        table_key = resolver "schema.tabla" en snapshot["schema"]
        index = primer índice btree cuya primera columna sea col
        si index es None: skip  # sin índice, no hay oportunidad perdida → D16
        matches.append({
            table, column: col, cast_type,
            filter: node.filter, node_type, index_name: index.name
        })

devolver Detection(found=bool(matches), confidence=0.9, evidence={"matches": matches})
```

El detector solo reporta cuando existe un índice sobre la columna con
cast: si no hay índice, el Seq Scan sería inevitable de todos modos y
el anti-pattern correcto es D16 (falta de índice), no D11.

## Recomendación

(Pendiente integración con `motor/recommender.py`.) Dos caminos según
el contexto:

1. **Corregir el tipo en la query** (preferible):
   ```sql
   -- Antes (cast implícito sobre la columna):
   WHERE status::int = 1
   -- Después (comparación del mismo tipo):
   WHERE status = '1'
   ```

2. **Crear un índice funcional** sobre la expresión casteada si el cast
   es intencional y no se puede cambiar la query:
   ```sql
   CREATE INDEX idx_orders_status_int ON orders (((status)::integer));
   ```

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- **Opción 1 (fix en query):** en sandbox, correr `EXPLAIN` con la
  query corregida y verificar que el plan cambia de `Seq Scan` a
  `Index Scan`. Si el planner sigue eligiendo Seq Scan (tabla pequeña,
  stats desactualizadas), descartar la sugerencia.
- **Opción 2 (índice funcional):** en sandbox, crear el índice
  funcional, correr `EXPLAIN` con la query original y verificar que
  el plan lo usa. El LLM solo explica; el motor valida.

## Falsos positivos conocidos

- **Cast sobre literal mal formateado en el filter.** El regex
  `\(\(col\)::tipo` es específico: captura `((col)::` y no
  `col::tipo` ni `cast(col AS tipo)`. Formatos alternativos de EXPLAIN
  en versiones futuras de Postgres podrían no matchear. Para AppDB v1
  (Postgres 16) el formato es estable.
- **Cast sobre expresión compuesta** como `((a + b)::integer = 5)`. El
  regex `(\w+)` no matchea `a + b`, así que el detector lo ignora
  silenciosamente. Falso negativo voluntario para evitar FPs con
  expresiones complejas.
- **Índice GIN o HASH sobre la columna.** El detector busca solo índices
  btree (los únicos que aceleran comparaciones de igualdad y rango). Un
  índice GIN sobre la columna no es equivalente para este patrón.
- **Tablas pequeñas.** El detector no filtra por tamaño de tabla: un
  cast en una tabla de 100 filas podría producir un match aunque el
  impacto sea nulo. El recomendador debe moderar la prosa en esos casos.

## Ejemplo de query

```sql
-- status es VARCHAR, el dev compara con entero → cast implícito
SELECT id, amount
FROM orders
WHERE status::int = 1;
```

```sql
-- author_id es integer, el dev lo compara como texto
SELECT *
FROM posts
WHERE author_id::text = '42';
```

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Seq Scan",
    "Relation Name": "orders",
    "Filter": "((status)::integer = 1)",
    "Plan Rows": 5000,
    "Total Cost": 450.0
  }
}
```

D11 evalúa:
- Nodo `Seq Scan` ✓
- `node.filter` contiene `((status)::integer` ✓ (match del regex)
- `table_key = "public.orders"` resuelto desde snapshot.
- Índice btree `idx_orders_status (status)` existe en snapshot ✓
- ⇒ `Detection(found=True, confidence=0.9, evidence={"matches": [{table: "public.orders", column: "status", cast_type: "integer", index_name: "idx_orders_status", ...}]})`

## Tests

`tests/motor/detectors/test_type_mismatch.py`. Cubre:

- Happy path: Seq Scan con `((status)::integer` + índice btree → dispara.
- Happy path 2: `((author_id)::text` sobre `public.orders` → dispara.
- Múltiples casts en el mismo filtro → un match por columna con índice.
- Negativo: cast presente pero **sin índice** en esa columna → no dispara.
- Negativo: filtro sin cast (forma normal) → no dispara.
- Negativo: cast sobre literal (`'5'::integer`) no sobre columna → no dispara.
- Negativo: `Index Scan` (índice ya en uso) → no dispara.
- Robustez: `filter=None` → no dispara sin lanzar.
- Robustez: snapshot vacío → no dispara (no hay índice conocido).
- Kwarg `sql=` acepta la firma extendida sin cambiar el resultado.
- **Frontera D5:** `lower(status) = ...` no matchea el regex de D11.

## Referencias

- `/motor/detectors/type_mismatch.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_type_mismatch`)
- Backlog `D11` en `/PgPilot_Backlog.md`
- Postgres docs:
  [Operator Type Resolution](https://www.postgresql.org/docs/current/typeconv-oper.html)

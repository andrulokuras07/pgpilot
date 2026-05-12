# Falta de índice cubriente

> **Detector:** `motor.detect_missing_covering_index` (D10)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.7 (heurístico laxo)

## Problema

Un `Index Scan` usa el índice para encontrar las filas que matchean
el `WHERE`, pero después tiene que ir al heap (tabla) por cada fila
para leer las columnas que el índice no guarda. Es el costo invisible
de los índices "normales": cada fila vista cuesta una lectura
adicional de página, y la latencia escala lineal con la cardinalidad
del resultado.

Si todas las columnas que el `SELECT` realmente necesita cupieran en
el índice (via `INCLUDE` o como columnas extra), el plan pasaría a
`Index Only Scan`: el heap fetch desaparece, y la query corre 5×–20×
más rápido sobre tablas frías.

La trampa: muchos ingenieros backend agregan índices para acelerar
`WHERE` pero olvidan que el `SELECT` también puede beneficiarse.
D10 es el recordatorio estructural.

## Cómo aparece en el plan

El detector busca **`Index Scan` que NO sean `Index Only Scan`**:

- `Index Scan using idx_x on tabla`: cada fila devuelta toca el heap.
- `Index Only Scan using idx_x on tabla`: el heap solo se toca si la
  visibility map indica que la página tuvo cambios recientes (con
  `VACUUM` reciente, ≈ 0 heap fetches).

D10 reporta `Bitmap Heap Scan` como NO candidato directo (decisión
de diseño: la mejora hacia `Index Only Scan` no es directa cuando
el plan usa bitmap). Y `Seq Scan` queda fuera por definición.

## Regla de detección

Pseudocódigo (mapea contra
`motor/detectors/missing_covering_index.py`):

```
INDEX_SCAN_MIN_ROWS = 50

para cada nodo en find_nodes(plan, "Index Scan"):
    si node.relation_name es None: skip
    rows = node.actual_rows si está, si no node.plan_rows
    si rows < INDEX_SCAN_MIN_ROWS: skip       # filtro de FPs obvios
    table_key = resolver "schema.tabla" en snapshot["schema"]
    existing_index = índice del snapshot cuyo name == node.index_name
    matches.append({
        table, index_name, index_cond,
        indexed_columns: existing_index.columns si está, si no None,
        include_columns: existing_index.include si está, si no None,
    })

devolver Detection(found=bool(matches), confidence=0.7, evidence={"matches": matches})
```

D10 dispara una vez por `Index Scan` que supere el umbral. El
umbral elimina los lookups por PK y los filtros muy selectivos
(devuelven 1-30 filas) donde el heap fetch es despreciable y un
`INCLUDE` solo encarece el índice. La oportunidad real de mejora
para los que pasan el filtro depende de las columnas que la query
pide — ese análisis lo hace el recomendador cruzando con el SQL
sanitizado.

## Recomendación

(Pendiente integración con `motor/recommender.py`.) Dos formas:

1. **Extender el índice existente con `INCLUDE`:**
   ```sql
   DROP INDEX idx_posts_author_id;
   CREATE INDEX idx_posts_author_id
     ON posts (author_id) INCLUDE (title, created_at);
   ```
2. **Crear un índice cubriente paralelo** si el original está siendo
   usado por queries muy diferentes.

El recomendador, no D10, decide cuáles columnas van en `INCLUDE`:
parsea el SQL sanitizado con sqlglot, extrae las columnas del
`SELECT` y del `WHERE`, y verifica que su tamaño total sea
razonable (no incluir un `TEXT` enorme).

## Validación

(Pendiente conexión al sandbox.) La validación natural sería:

- Antes/después: en sandbox, dropear el índice viejo, crear el
  cubriente, correr `EXPLAIN ANALYZE`. Verificar que el nodo pasa
  a `Index Only Scan` y el costo cae. Si no, descartar la sugerencia.
- LLM: `/ia/cross_validator.py` valida que las columnas en el
  `INCLUDE` existan en la tabla. Si el LLM inventa columnas, se
  descarta.

## Falsos positivos conocidos

- **`Index Scan` con muchas filas pero columnas INCLUDE enormes.**
  El umbral `INDEX_SCAN_MIN_ROWS = 50` ya filtra los Index Scan
  triviales (PK lookup, filtros muy selectivos). Por encima del
  umbral siguen quedando casos donde el cubriente no ayuda: si las
  columnas extra son `text` o `jsonb` grandes, el `INCLUDE` cuesta
  más mantener de lo que ahorra. El recomendador (con sandbox)
  debe filtrar este caso antes de emitir prosa enfática.
- **Columnas `INCLUDE` enormes.** Si la query lee `body TEXT`,
  agregar ese `body` al `INCLUDE` puede hacer el índice más caro
  que el heap fetch que ahorra. El recomendador debe rechazar el
  caso cuando el ancho de las columnas extra es alto.
- **Tablas con UPDATE frecuente.** Cada UPDATE invalida la
  visibility map de la página afectada, y `Index Only Scan` cae a
  heap fetch real. En tablas con write rate alto el cubriente puede
  no mejorar nada en producción. D10 no mide esto; el recomendador
  con sandbox sí puede aproximarlo.
- **Bitmap Heap Scan no se reporta como candidato.** Es una
  decisión de scope, no un bug: la mejora hacia `Index Only Scan`
  desde Bitmap no es directa.

## Ejemplo de query

```sql
SELECT id, author_id, title
FROM posts
WHERE author_id = $LITERAL_2_0;
```

`posts` tiene un índice `idx_posts_author_id (author_id)` sin
`INCLUDE`. El plan usa `Index Scan` y va al heap por `title`.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Index Scan",
    "Relation Name": "posts",
    "Index Name": "idx_posts_author_id",
    "Index Cond": "(author_id = 5)",
    "Plan Rows": 100,
    "Plan Width": 200
  }
}
```

D10 evalúa:

- Nodo `Index Scan` ✓ (no es `Index Only Scan`)
- `relation_name = "posts"` ✓
- Resuelve `table_key = "public.posts"` desde snapshot.
- Encuentra `idx_posts_author_id` con `columns = ["author_id"]`,
  `include = []`.
- ⇒ `Detection(found=True, confidence=0.7, evidence={"matches": [{table: "public.posts", index_name: "idx_posts_author_id", indexed_columns: ["author_id"], include_columns: [], ...}]})`

## Tests

`tests/motor/detectors/test_missing_covering_index.py`. Cubre:

- Happy path: `Index Scan` sobre `posts` con índice en snapshot →
  dispara con `indexed_columns` poblado.
- Negativo (frontera): `Index Only Scan` → no dispara (ya cubierto).
- Negativo (frontera): `Seq Scan` → no dispara (no usa índice).
- Robustez: sin snapshot, sigue disparando con
  `indexed_columns = None`.
- Múltiples `Index Scan` en un mismo plan → un match por cada uno
  que supere el umbral.
- **Umbral:** `Index Scan` con `plan_rows < 50` → no dispara.
- **Umbral con `actual_rows`:** estimación inflada (`plan_rows=5000`)
  pero real bajo (`actual_rows=3`) → no dispara, prefiere `actual_rows`.

## Referencias

- `/motor/detectors/missing_covering_index.py` (implementación)
- `/motor/CLAUDE.md` (sección `detect_missing_covering_index`)
- Backlog `D10` en `/PgPilot_Backlog.md`
- Postgres docs:
  [Covering Indexes (`INCLUDE`)](https://www.postgresql.org/docs/current/sql-createindex.html)

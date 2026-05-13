# Sort en disco (`external merge Disk`)

> **Detector:** `motor.detect_sort_spill_to_disk` (D3)
> **Estado:** ✅ Implementado
> **Confianza emitida:** 0.95 (estructural — el campo `Sort Space Type`
> es autoritativo: Postgres lo emite con certeza)

## Problema

Cuando un `ORDER BY` (o un `DISTINCT`, `UNION`, `GROUP BY` que
internamente ordena) tiene más datos de los que caben en `work_mem`,
Postgres no falla — *desborda al disco*. Crea archivos temporales en
`base/pgsql_tmp/`, hace un *external merge sort*, y los borra al
terminar. La query devuelve los datos correctos, pero a un costo
brutal: I/O secuencial pesada, latencia 10x–100x peor que un sort en
RAM, presión sobre el filesystem y, en casos extremos, errores de
espacio en disco.

El síntoma típico en producción es "esta query era rápida y ahora
tarda 8 segundos sin que nadie haya tocado nada". Suele coincidir con
crecimiento del dataset o con queries que antes pasaban por un `LIMIT`
chico y ahora ordenan todo antes de paginar.

## Cómo aparece en el plan

Un nodo `Sort` con:

- **`Sort Space Type: "Disk"`** — campo authoritativo. Si Postgres
  emite este valor, el sort definitivamente desbordó.
- **`Sort Method: "external merge"`** o `"external sort"` — texto
  que confirma el método. Se usa como fallback defensivo si por
  alguna razón la versión de Postgres omite `Sort Space Type`.
- **`Sort Space Used: N`** — KB de disco que se usaron. Es la base
  para dimensionar `work_mem`: idealmente la nueva configuración debe
  ser un poco mayor que este valor.

Ejemplo:

```json
{
  "Node Type": "Sort",
  "Sort Key": ["public.posts.created_at DESC"],
  "Sort Method": "external merge",
  "Sort Space Type": "Disk",
  "Sort Space Used": 24576
}
```

D3 opera sobre estos campos tipados de `PlanNode` (R2). El SQL crudo
del usuario nunca se inspecciona.

## Regla de detección

Pseudocódigo (mapea contra `motor/detectors/sort_spill_to_disk.py`):

```
para cada nodo Sort en find_nodes(plan, "Sort"):
    spilled = False
    si node.sort_space_type == "Disk":
        spilled = True
    elif "external merge" in node.sort_method.lower()
         or "external sort" in node.sort_method.lower():
        spilled = True
    si no spilled: skip
    matches.append({
        sort_key: node.sort_key,
        sort_method, sort_space_type, sort_space_used_kb,
        plan_rows, actual_rows,
        suggested_set_work_mem_sql,        # "SET work_mem = '<N>MB';"
        suggested_create_index_sql,        # CREATE INDEX si sort_key es simple
    })

devolver Detection(found=bool(matches), confidence=0.95, evidence={"matches": matches})
```

La condición primaria es `sort_space_type == "Disk"`; el fallback al
método protege contra variantes textuales entre versiones de Postgres.

## Recomendación

D3 emite dos hechos accionables — el recomendador final puede priorizar
uno u otro según contexto:

**1. Subir `work_mem` para esta sesión** (barato, reversible, sin tocar
la query):

```sql
SET work_mem = '48MB';  -- 2x lo que usó, redondeado al MB siguiente
```

Si no hay `Sort Space Used`, sugerimos `64MB` como punto de partida.
Importante: `work_mem` es **por nodo de sort**, no por sesión — una
query con 3 sorts puede usar 3 × `work_mem`. Por eso la sugerencia es
de sesión (`SET`) y no `ALTER ROLE` ni `ALTER SYSTEM`: el usuario
puede validar y revertir sin compromiso global.

**2. Crear un índice btree sobre la primera columna del `sort_key`**
(arregla el problema de raíz):

```sql
CREATE INDEX idx_posts_created_at ON public.posts (created_at);
```

El planner puede entonces servir el orden directamente del índice con
`Index Scan` y eliminar el `Sort` por completo. Esta sugerencia solo
se emite si el `sort_key` está en forma `tabla.col` o `schema.tabla.col`;
si es una expresión (`lower(name)`, `coalesce(a, b)`), el detector
deja `suggested_create_index_sql = None` y delega al recomendador, que
tiene el contexto para evaluar un índice funcional.

## Validación

- **Sandbox (`sandbox.validate_index_recommendation`)**: si el camino
  elegido es CREATE INDEX, el sandbox monta el schema, crea el índice
  y verifica con EXPLAIN que el nuevo plan ya no contiene un Sort en
  disco (idealmente, ya no contiene el nodo Sort en absoluto). Si el
  camino es `SET work_mem`, la validación natural es ejecutar el
  EXPLAIN ANALYZE original con el `work_mem` propuesto y confirmar que
  `Sort Space Type` ahora es `"Memory"`.
- **LLM (`/ia/cross_validator.py`)**: la prosa generada se valida
  contra el snapshot — si menciona una columna inexistente o sugiere
  un índice sobre una tabla que no existe, se cae a la plantilla.

## Falsos positivos conocidos

- **`top-N heapsort`**: cuando hay `ORDER BY ... LIMIT N` pequeño,
  Postgres usa un heapsort acotado que cabe en memoria aunque la
  tabla sea enorme. D3 no lo confunde con disk spill porque
  `Sort Method = "top-N heapsort"` y `Sort Space Type = "Memory"`.
- **`quicksort` en memoria**: idem, sin alarma.
- **Sort en disco "intencional"**: en queries OLAP de un sólo uso
  (informes mensuales que corren a la 1 AM), un sort en disco puede
  ser aceptable. D3 igualmente reporta el hecho; la decisión de
  actuar queda en el usuario. Recomendar bajar `work_mem` global
  para queries OLAP raras y subirlo solo en la sesión del informe
  es una práctica común.
- **Sort dentro de un Aggregate de tipo `Sorted`**: aparece como
  hijo de un nodo Aggregate y se reporta normalmente. La
  recomendación de índice puede ser igual de válida.

## Ejemplo de query

```sql
SELECT id, title, body
FROM posts
WHERE author_id = 42
ORDER BY created_at DESC;
```

`posts` con 5 millones de filas y `idx_posts_author_id` pero sin
índice sobre `created_at`. Postgres filtra por `author_id`, encuentra
~200k filas, e intenta ordenarlas en memoria. Si `work_mem = 4MB`
(default), desborda.

## Ejemplo de plan

```json
{
  "Plan": {
    "Node Type": "Sort",
    "Startup Cost": 1000.0,
    "Total Cost": 1100.0,
    "Plan Rows": 200000,
    "Plan Width": 50,
    "Actual Rows": 200000,
    "Actual Loops": 1,
    "Sort Key": ["public.posts.created_at DESC"],
    "Sort Method": "external merge",
    "Sort Space Type": "Disk",
    "Sort Space Used": 24576,
    "Plans": [
      {
        "Node Type": "Bitmap Heap Scan",
        "Relation Name": "posts",
        "Recheck Cond": "(author_id = 42)"
      }
    ]
  }
}
```

Lo que D3 evalúa:

- Node Type == "Sort" ✓
- `sort_space_type == "Disk"` ✓
- ⇒ `Detection(found=True, confidence=0.95, evidence={"matches": [{...}]})`
- `suggested_set_work_mem_sql = "SET work_mem = '48MB';"` (2 × 24576 KB
  redondeado al MB)
- `suggested_create_index_sql = "CREATE INDEX idx_posts_created_at ON public.posts (created_at);"`

## Tests

`tests/motor/detectors/test_sort_spill_to_disk.py`. Cubre:

- Happy path: `Sort Space Type=Disk` con `external merge` → dispara.
- Variante (fallback): solo `Sort Method` menciona `external merge` → dispara.
- Sort key `tabla.col` → emite CREATE INDEX bien formado.
- Negativo (frontera): `Sort Space Type=Memory` → no dispara.
- Negativo: plan sin nodos Sort → no dispara.
- Negativo: `Sort Method = "top-N heapsort"` → no dispara.
- Robustez: sort key con expresión funcional → no inventa CREATE INDEX.
- Robustez: sort sin sort_key → no crashea.
- Robustez: sin `Sort Space Used` → sugiere `64MB` default.
- Plurales: dos Sort en disco en un Merge Join → dos matches.

## Referencias

- `/motor/detectors/sort_spill_to_disk.py` (implementación)
- `/motor/CLAUDE.md` (sección "detect_sort_spill_to_disk")
- Backlog `D3` en `/PgPilot_Backlog.md`
- Postgres docs: [`work_mem`](https://www.postgresql.org/docs/current/runtime-config-resource.html#GUC-WORK-MEM),
  [`EXPLAIN`](https://www.postgresql.org/docs/current/sql-explain.html)
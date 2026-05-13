# Catálogo de anti-patterns

Este directorio documenta cada anti-pattern que PgPilot detecta. Es la
referencia humana de la batería de detectores que vive en
`/motor/detectors/`. La rúbrica del proyecto pide explícitamente este
catálogo (Criterio 2.1 / 2.2): cada detector implementado debe tener
su entrada aquí, y cada entrada debe alinear con un detector real.

**Convención (definida en `/CLAUDE.md` raíz):** un anti-pattern por
archivo `.md`. Este `README.md` es el índice + la plantilla.

## Índice

| # | Anti-pattern | Archivo | Detector | Estado |
|---|--------------|---------|----------|--------|
| 1 | Seq Scan sobre tabla grande con índice disponible | [`seq-scan-on-large-table.md`](seq-scan-on-large-table.md) | `motor.detect_seq_scan_on_large_table` (C1) | ✅ Implementado |
| 2 | Seq Scan sobre tabla grande sin índice en la columna del filtro | [`missing-index.md`](missing-index.md) | `motor.detect_missing_index` (D16) | ✅ Implementado |
| 3 | Mismatch entre `rows estimated` y `rows actual` (stats obsoletas) | [`stale-statistics.md`](stale-statistics.md) | `motor.detect_stale_statistics` (D2) | ✅ Implementado |
| 4 | Sort en disco (`external merge Disk`) | [`sort-spill-to-disk.md`](sort-spill-to-disk.md) | `motor.detect_sort_spill_to_disk` (D3) | ✅ Implementado |
| 5 | LIKE con wildcard al inicio | [`like-leading-wildcard.md`](like-leading-wildcard.md) | `motor.detect_like_leading_wildcard` (D4) | ✅ Implementado |
| 6 | Función no-immutable en WHERE | [`function-in-where.md`](function-in-where.md) | `motor.detect_function_in_where` (D5) | ✅ Implementado |
| 7 | OR sobre columnas de tablas distintas | [`or-across-tables.md`](or-across-tables.md) | `motor.detect_or_across_tables` (D6) | ✅ Implementado |
| 8 | Subquery correlacionada | [`correlated-subquery.md`](correlated-subquery.md) | `motor.detect_correlated_subquery` (D7) | ✅ Implementado |
| 9 | Nested Loop con tabla externa grande | [`nested-loop-large-outer.md`](nested-loop-large-outer.md) | `motor.detect_nested_loop_large_outer` (D8) | ✅ Implementado |
| 10 | `SELECT *` con pocas columnas usadas | [`select-star.md`](select-star.md) | `motor.detect_select_star` (D9) | ✅ Implementado |
| 11 | Falta de índice cubriente | [`missing-covering-index.md`](missing-covering-index.md) | `motor.detect_missing_covering_index` (D10) | ✅ Implementado |
| 12 | Índice no usado por mismatch de tipo | [`type-mismatch.md`](type-mismatch.md) | `motor.detect_type_mismatch` (D11) | ✅ Implementado |
| 13 | CTE materializada innecesariamente | [`unnecessary-cte-materialize.md`](unnecessary-cte-materialize.md) | `motor.detect_unnecessary_cte_materialize` (D12) | ✅ Implementado |
| 14 | Oportunidad de índice parcial | [`partial-index-opportunity.md`](partial-index-opportunity.md) | `motor.detect_partial_index_opportunity` (D17) | ✅ Implementado |
| 15 | Error de cardinalidad en JOIN multi-condición | [`cardinality-misestimate.md`](cardinality-misestimate.md) | `motor.detect_cardinality_misestimate` (D18) | ✅ Implementado |
| 16 | HAVING que debería ser WHERE | _(pendiente)_ | D19 | ⬜ Backlog |
| 17 | IN con subquery debería ser EXISTS | _(pendiente)_ | D20 | ⬜ Backlog |
| 18 | NOT IN con subquery potencialmente NULL | _(pendiente)_ | D21 | ✅ Implementado 
| 19 | `count(*)` sobre tabla grande sin WHERE | _(pendiente)_ | D22 | ⬜ Backlog |

Cuando un detector aterriza, su autor:

1. Crea un archivo nuevo en este directorio siguiendo la plantilla de
   abajo.
2. Marca la fila correspondiente en el índice como ✅ Implementado y
   apunta el archivo.

## Cómo nombrar el archivo

`<verbo-o-síntoma>-<sujeto>.md` en kebab-case, en inglés, alineado con
el nombre del detector en `/motor/detectors/`. Ejemplos:

- `seq-scan-on-large-table.md` ↔ `motor/detectors/seq_scan_on_large_table.py`
- `like-leading-wildcard.md` ↔ `motor/detectors/like_leading_wildcard.py`

Si el detector aún no existe pero el pattern sí está documentado por
diseño, dejarlo claro en el archivo con una nota "Detector pendiente
(ver backlog Dx)".

## Plantilla

Cada anti-pattern documentado debe tener al menos las secciones
siguientes. Copiar este bloque y rellenar:

```markdown
# <Nombre del anti-pattern>

> **Detector:** `motor.<nombre_de_la_funcion>` (`<código del backlog>`)
> **Estado:** ✅ Implementado | ⬜ Pendiente
> **Confianza emitida:** 1.0 (determinístico) | 0.x (heurístico)

## Problema

Qué está mal y por qué duele en producción. 2-4 líneas. Escribir para
un developer backend que conoce SQL pero no es DBA. Mencionar el
costo concreto: I/O, latencia P99, bloqueos, etc.

## Cómo aparece en el plan

Qué nodos y campos del `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`
delatan el problema. Importante: la regla de detección opera sobre la
**estructura** del plan, no sobre el SQL crudo (R2 de `RULES.md`).
Ejemplo de fragmento del plan donde el patrón es visible.

## Regla de detección

Pseudocódigo o lista de condiciones que el detector evalúa. Debe
poder mapearse 1:1 contra el código en `motor/detectors/<archivo>.py`.

## Recomendación

Qué hace el recomendador (`motor/recommender.py`) cuando el detector
dispara. Si emite SQL, mostrar el shape: `CREATE INDEX ...`,
`ANALYZE ...`, etc. Si tiene varios outputs según contexto (ej.
`create_index` vs `analyze`), enumerarlos.

## Validación

Cómo se prueba antes de mostrar al usuario:

- Con sandbox: qué verifica `sandbox.validate_index_recommendation`
  (planner usa el índice, costo baja, etc.).
- Con LLM (`/ia`): qué validaciones aplica `cross_validate` sobre la
  prosa generada para descartar alucinaciones.

## Falsos positivos conocidos

Cuándo el detector dispararía mal o cuándo el patrón se ve pero NO es
problema. Documentar mitigaciones y limitaciones explícitas (ver las
"limitaciones" en el `CLAUDE.md` del módulo motor para el formato).

## Ejemplo de query

Una query (sintética o real de AppDB) que reproduce el patrón.
Idealmente referenciar un fixture en `tests/motor/fixtures/` para que
sea ejecutable.

## Ejemplo de plan

Fragmento del JSON de EXPLAIN donde el patrón aparece, con los campos
relevantes resaltados. Mantener corto: 10-30 líneas.

## Tests

Apuntador a los tests del detector:
`tests/motor/detectors/test_<archivo>.py`. Listar al menos: happy
path, caso negativo, frontera con detectores hermanos.

## Referencias

- `/motor/detectors/<archivo>.py` (implementación)
- `/motor/CLAUDE.md` (decisiones del módulo)
- Backlog `<código>` en `/PgPilot_Backlog.md`
- (Opcional) Postgres docs, papers, blog posts.
```

## Notas para agentes que documenten un pattern nuevo

- **Una sola fuente de verdad.** Si la regla de detección cambia en
  el código, actualizar el `.md` del pattern en el mismo PR (es la
  contraparte de R15 para documentación de producto, no de módulo).
- **No duplicar el código en el `.md`.** El pseudocódigo es para el
  lector humano, no copia literal. Apuntar al archivo real.
- **Usar nombres genéricos en los ejemplos** (`tabla`, `col`, `idx`)
  o nombres reales de AppDB cuando referencien fixtures concretos.
  Nunca inventar nombres que sugieran un cliente real (R4 espiritual:
  el catálogo es público).
- **Si el pattern aún no tiene detector**, igual se puede documentar
  con `Estado: ⬜ Pendiente` y nota de backlog. Esto sirve para que
  futuros autores entiendan qué se espera antes de empezar a escribir
  código.

# Módulo `workload` — Procesamiento de pg_stat_statements

Parser y scoring de exports de `pg_stat_statements`. Recibe un CSV o JSON con las queries más ejecutadas en producción y devuelve un ranking por impacto (tiempo total acumulado).

**Lo que NO hace:** conexión a Postgres (eso vive en `/conector`), detección de anti-patterns (eso vive en `/motor`), ni exposición HTTP (eso vive en `/backend`).

---

## Estado actual

- ✅ E1 — Parser de pg_stat_statements (CSV y JSON)
- ✅ E2 — Score de impacto por total_exec_time

---

## API pública

Exportado en `workload/__init__.py`:

### `parse_pg_stat_statements(raw: str) -> list[StatementEntry]`
Parsea un string con el contenido de un export de pg_stat_statements.

**Detección de formato:** si el contenido (después de strip) empieza con `[`, se trata como JSON array. Si no, se trata como CSV con headers.

**Columnas esperadas (case-insensitive):**
- `query` — la query normalizada
- `calls` — número de ejecuciones
- `total_exec_time` (o `total_time` para PG < 13)
- `mean_exec_time` (o `mean_time` para PG < 13)
- `rows` — filas totales devueltas

### `StatementEntry` (frozen dataclass)
- `query: str`
- `calls: int`
- `total_exec_time: float`
- `mean_exec_time: float`
- `rows: int`

### `score_workload(entries, *, top_n=10) -> list[ScoredEntry]`
Ordena por `total_exec_time` descendente y devuelve los top N. El score es el tiempo normalizado al máximo (0..1).

### `ScoredEntry` (frozen dataclass)
Extiende `StatementEntry` con:
- `score: float` — 0 a 1, normalizado al máximo
- `rank: int` — posición (1 = más impacto)

---

## Estructura interna

```
workload/
├── __init__.py     # exporta API pública
├── parser.py       # parse_pg_stat_statements, StatementEntry (E1)
├── scoring.py      # score_workload, ScoredEntry (E2)
├── CLAUDE.md       # este archivo
└── README.md       # placeholder original
```

---

## Cómo extender

### Agregar un nuevo formato de input
Añadir una función `_parse_<formato>(raw: str) -> list[StatementEntry]` en `parser.py` y extender la heurística de detección en `parse_pg_stat_statements`.

### Cambiar la métrica de scoring
Hoy el score usa `total_exec_time`. Para usar otra métrica (ej: rows, un compuesto), modificar la función `score_workload` en `scoring.py`.

---

## Decisiones específicas del módulo

- **Score por tiempo total, no frecuencia.** La rúbrica lo menciona explícito: una query que acumula mucho tiempo total duele más que una que se ejecuta muchas veces pero es rápida.
- **Compatibilidad PG < 13.** Las columnas `total_time` y `mean_time` (nombres pre-PG13) se aceptan como fallback de `total_exec_time` y `mean_exec_time`.
- **Heurística de formato simple.** Empieza con `[` → JSON, si no → CSV. No hay ambigüedad práctica en exports de pg_stat_statements.

---

## Tests

Viven en `tests/workload/`:
- `test_workload_parser.py` — 7 tests: CSV, JSON, campos correctos, vacío, compat PG12, 50 queries.
- `test_workload_scoring.py` — 5 tests: orden correcto, normalización, rank, vacío, frecuencia no domina.

```bash
.venv/bin/python -m pytest tests/workload/ -v
```

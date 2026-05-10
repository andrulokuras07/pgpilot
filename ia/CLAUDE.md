# Módulo `ia` — Capa de integración con LLM

Este módulo es la frontera entre el código determinístico del proyecto y el LLM. Cubre sanitización del SQL antes de enviarlo, construcción del prompt, y validación de la respuesta.

**Regla #1 del proyecto:** el LLM nunca ve la query cruda del usuario. Siempre pasa primero por `sanitize()`.

---

## Estado actual

- ✅ B10 — sanitizador de literales (`sanitizer.py`)
- ⬜ B11 — test de privacidad reforzado
- ⬜ C4 — prompt estructurado al LLM
- ⬜ C5 — validación de respuesta con Pydantic
- ⬜ C6 — validación cruzada de sugerencias
- ⬜ C7 — modo "LLM apagado" con plantillas
- ⬜ C8 — logs estructurados

---

## API pública

```python
from ia import sanitize, restore, SanitizedQuery
```

### `sanitize(sql: str) -> SanitizedQuery`

Recibe SQL crudo y devuelve `SanitizedQuery(sql, literals)`:
- `sql` — query con literales reemplazados por `$LITERAL_<tipo>_<i>`.
- `literals` — `{"LITERAL_<tipo>_<i>": {"type": ..., "original": ...}}`.

**Tipos detectados** (sufijo según backlog B10):
- `string` (sufijo 1) — texto entre comillas simples o dobles, soporta `''` escapado.
- `number` (sufijo 2) — enteros y decimales.
- `date` (sufijo 3) — ISO 8601 (`YYYY-MM-DD` con hora opcional).
- `uuid` (sufijo 4) — formato canónico 8-4-4-4-12.
- `email` (sufijo 5) — `usuario@dominio.tld`.

Ejemplo de placeholder: `$LITERAL_1_1` (primer string), `$LITERAL_2_3` (tercer número).

**Garantías:**
- Ningún valor original aparece en `sanitized.sql`.
- Funciona aunque el SQL no parsee con sqlglot (es regex puro).
- Patrones aplicados de más específico a más general; matches solapados se descartan.

### `restore(sanitized: SanitizedQuery) -> str`

Reconstruye el SQL original. Solo para debug local. Nunca usar el output de `restore()` para enviar al LLM.

---

## Cómo agregar un patrón nuevo

1. Agregar la tupla `(tipo, regex)` a `_PATTERNS` en la posición correcta (más específico antes que más general).
2. Actualizar `LiteralType` y `_TYPE_SUFFIX` con el sufijo nuevo.
3. Agregar tests en `tests/ia/test_sanitizer.py`.
4. Documentar el patrón en este archivo.

---

## Tests

`tests/ia/test_sanitizer.py`. Unitarios sin marker `integration` (no requieren AppDB ni Docker).

```bash
pytest tests/ia/ -v
```
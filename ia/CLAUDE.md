# Módulo `ia` — Capa de integración con LLM

Este módulo es la frontera entre el código determinístico del proyecto y el LLM. Cubre sanitización del SQL antes de enviarlo, construcción del prompt, y validación de la respuesta.

**Regla #1 del proyecto:** el LLM nunca ve la query cruda del usuario. Siempre pasa primero por `sanitize()`.

---

## Estado actual

- ✅ B10 — sanitizador de literales (`sanitizer.py`)
- ✅ B11 — test de privacidad del sanitizador (`tests/ia/test_privacidad.py`)
- ✅ C4 — prompt estructurado al LLM (`prompt.py` + `llm.py`)
- ⬜ C5 — validación de respuesta con Pydantic
- ⬜ C6 — validación cruzada de sugerencias
- ⬜ C7 — modo "LLM apagado" con plantillas
- ⬜ C8 — logs estructurados

---

## API pública

```python
from ia import (
    sanitize, restore, SanitizedQuery,
    build_explanation_prompt, LLMPrompt,
    call_llm, LLMError, LLMDisabledError,
)
```

### `build_explanation_prompt(detection, plan, recommendation, sanitized_query) -> LLMPrompt` (C4)

Función pura. Recibe los outputs de C1 + parser + C2 + sanitizador y
arma un `LLMPrompt(system, messages, expected_output_schema)` listo
para `call_llm`. **Rechaza con `TypeError` si `sanitized_query` no es
un `SanitizedQuery`** — defensa en profundidad para R4. El prompt
sistémico le indica al LLM: explicar (no re-detectar), proponer rewrite
opcional, devolver JSON estricto con
`{explanation, suggested_rewrite, confidence}`.

El user-turn lleva, en JSON compacto y determinístico:
- `detection`: `{found, confidence, matches}`
- `recommendation`: todos los campos de `motor.Recommendation`
- `plan_summary`: lista de nodos con campos macro (no el árbol crudo)
- `sanitized_query`: el SQL con placeholders
- `literal_placeholders`: `{placeholder → tipo}`, NUNCA el valor original

### `call_llm(prompt, *, model=..., max_tokens=..., timeout=..., api_key=None) -> str` (C4)

Llama al endpoint `messages` de Anthropic vía `httpx`. Devuelve el
texto crudo de la respuesta (sin parsear — C5 valida con Pydantic).

- Lee `ANTHROPIC_API_KEY` del entorno si no se pasa explícito.
- Respeta `LLM_ENABLED=false` (R5): levanta `LLMDisabledError`.
- Sin API key: también levanta `LLMDisabledError`.
- Errores HTTP / de red: levanta `LLMError`.

Modelo default: `claude-sonnet-4-6`. Configurable por-call.

**Defensa en profundidad: strip de fences markdown.** Verificado
empíricamente (2026-05-11, sonnet-4-6) que Claude tiende a envolver
el JSON en ` ```json ... ``` ` aun cuando el system-prompt lo
prohíbe explícito. `_extract_text` quita la fence cuando envuelve
todo el output. Fences embebidas dentro de texto (ej. ejemplo de
SQL dentro de prosa) se preservan tal cual.

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

```bash
# Unit tests (no AppDB, no API key):
pytest tests/ia -m "not integration and not llm"

# LLM real (requiere ANTHROPIC_API_KEY exportada):
ANTHROPIC_API_KEY=sk-... pytest tests/ia -m llm
```

- `tests/ia/test_sanitizer.py` — sanitizador (B10).
- `tests/ia/test_privacidad.py` — grep externo sobre el output (B11).
- `tests/ia/test_prompt.py` — builder C4 (forma del prompt, R4 defensa
  en profundidad, determinismo).
- `tests/ia/test_llm.py` — cliente C4. Unit tests con `monkeypatch`
  sobre `httpx.post` cubren happy path / errores / R5. Un test
  `@pytest.mark.llm` manda un prompt REAL al servicio y verifica que
  responde con el JSON acordado (criterio "hecho cuando" del C4).
  Skip automático si no hay `ANTHROPIC_API_KEY`.
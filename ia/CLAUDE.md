# Módulo `ia` — Capa de integración con LLM

Este módulo es la frontera entre el código determinístico del proyecto y el LLM. Cubre sanitización del SQL antes de enviarlo, construcción del prompt, y validación de la respuesta.

**Regla #1 del proyecto:** el LLM nunca ve la query cruda del usuario. Siempre pasa primero por `sanitize()`.

---

## Estado actual

- ✅ B10 — sanitizador de literales (`sanitizer.py`)
- ✅ B11 — test de privacidad del sanitizador (`tests/ia/test_privacidad.py`)
- ✅ C4 — prompt estructurado al LLM (`prompt.py` + `llm.py`)
- ✅ C5 — validación de respuesta con Pydantic (`validator.py`)
- ✅ C6 — validación cruzada de sugerencias (`cross_validator.py`)
- ✅ C7 — modo "LLM apagado" con plantillas (`templates.py`)
- ✅ Orquestador C5+C6+C7 (`explain.py` → `explain_recommendation`)
- ⬜ C8 — logs estructurados

---

## API pública

```python
from ia import (
    # B10/B11
    sanitize, restore, SanitizedQuery,
    # C4
    build_explanation_prompt, LLMPrompt,
    call_llm, LLMError, LLMDisabledError,
    # C5
    LLMResponseSchema, LLMResponseInvalid,
    parse_llm_response, request_validated_explanation,
    # C6
    CrossValidationResult, cross_validate,
    # C7
    Explanation, explain_from_template,
    # Orquestador C5+C6+C7
    explain_recommendation,
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

### `LLMResponseSchema` (Pydantic BaseModel) — C5

Schema esperado del JSON que devuelve el LLM (definido en el system-prompt
de C4). Campos:
- `explanation: str` — `min_length=1`.
- `suggested_rewrite: str | None` — opcional. Si presente, debe parsear
  con sqlglot y referenciar identificadores existentes (lo valida C6).
- `confidence: float` — `ge=0.0, le=1.0`.

Campos extra del LLM se ignoran silenciosamente (Pydantic v2 default).

### `parse_llm_response(raw: str) -> LLMResponseSchema` — C5

Función pura. Parsea + valida en un solo paso. Levanta
`LLMResponseInvalid(reason, raw)` ante JSON malformado o schema
incorrecto. El campo `raw` se preserva para logs (C8).

### `request_validated_explanation(prompt, *, max_retries=1, ...) -> LLMResponseSchema` — C5

Llama al LLM (`call_llm`), valida, y si el output es inválido reintenta
hasta `max_retries` veces (default 1, según el backlog). Si tras todos
los intentos sigue siendo inválido, levanta `LLMResponseInvalid`. El
orquestador (`explain_recommendation`) atrapa esa excepción y cae a
plantilla.

No atrapa `LLMDisabledError` ni `LLMError`: el orquestador les da el
mismo tratamiento (todos → plantilla).

### `cross_validate(response, recommendation, snapshot, *, sandbox_pool=None, sanitized_sql=None) -> CrossValidationResult` — C6

Validación cruzada. Verifica que lo que dijo el LLM sea coherente con
la realidad antes de mostrárselo al usuario. Reglas aplicadas:

1. La columna del `Recommendation` existe en la tabla del snapshot.
2. Si `recommendation.kind == "create_index"`, el nombre del índice no
   está ya en uso en la tabla.
3. Si `response.suggested_rewrite` está presente:
   a. Parsea con sqlglot (dialect=`postgres`).
   b. Cualquier `CREATE INDEX` en el rewrite NO usa un nombre ya
      existente en el schema (los nombres de índice son scope-schema
      en Postgres).
   c. Las columnas referenciadas existen en algún table del snapshot.
4. (Opcional) Si `sandbox_pool` y `sanitized_sql` se pasan, corre
   `sandbox.validate_index_recommendation` y descarta si verdict ==
   `"discarded"`. Sin sandbox_pool, esta verificación se omite (modo
   rápido del backend / tests unit).

Devuelve `CrossValidationResult(passed, reasons, sandbox_verdict)`.
`reasons` es lista de strings — vacía cuando pasa, con prosa
diagnóstica cuando falla (consumida por C8 a futuro).

Es deliberadamente conservadora: ante cualquier inconsistencia,
falla. La regla #1 del proyecto (motor decide, LLM explica) implica
que descartar al LLM nunca es un costo alto — siempre hay plantilla.

### `Explanation` (frozen dataclass) — C7

Tipo común de salida tanto del camino LLM como del de plantilla:
- `explanation: str`
- `suggested_rewrite: str | None` — siempre `None` en plantilla;
  posiblemente string en LLM.
- `confidence: float` — entre 0 y 1.
- `source: Literal["llm", "template"]` — distingue cuál generó.

El frontend usa `source` para mostrar una etiqueta sutil
("explicación generada sin IA") cuando aplica.

### `explain_from_template(detection, recommendation) -> Explanation` — C7

Genera prosa determinística a partir de `Detection` + `Recommendation`.
Sin red, sin LLM. Dos plantillas: una para `kind="create_index"` (cómo
funciona un Seq Scan vs. Index Scan + el SQL del motor), otra para
`kind="analyze"` (stats desactualizadas + ANALYZE).

La confianza baja a 0.6 si la recomendación no tiene selectividad
(tabla sin ANALYZE); 0.8 cuando sí. La prosa de la plantilla incluye
los campos `justification` y `expected_impact` ya armados por C2.

### `explain_recommendation(detection, plan, recommendation, sanitized_query, *, snapshot, sandbox_pool=None, max_retries=1) -> Explanation` — orquestador

Función principal que el backend (C9) consume. Atajos:

- LLM apagado / sin API key → plantilla directa.
- LLM responde basura tras reintentos → plantilla (C5 hecho-cuando).
- LLM responde válido pero C6 falla → plantilla (C6 hecho-cuando).
- LLM responde válido + C6 pasa → `Explanation(source="llm")`.

Garantía: **nunca propaga** `LLMDisabledError`, `LLMError` ni
`LLMResponseInvalid` al backend. La pipeline degrada elegante a
plantilla en todos esos casos (R5).

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
- `tests/ia/test_response_validator.py` — Pydantic schema, parseo y
  reintentos del validador C5. Cubre el "hecho cuando" del backlog
  (JSON malformado → `LLMResponseInvalid` levantado, sin crash).
- `tests/ia/test_cross_validator.py` — validación cruzada C6.
  Cubre el "hecho cuando" del backlog: una respuesta con un nombre
  de índice ya existente se descarta. Más: columna inventada, SQL
  no parseable, recomendación con columna inexistente, modo sandbox
  opcional con `monkeypatch` sobre `validate_index_recommendation`.
- `tests/ia/test_templates.py` — plantillas C7. Verifica que la prosa
  determinística menciona tabla/columna del snapshot (R14), incluye
  el SQL, y baja la confianza cuando falta selectividad.
- `tests/ia/test_explain_orchestrator.py` — integración C5+C6+C7.
  El "hecho cuando" más fuerte del backlog: con `LLM_ENABLED=false`
  o con respuesta malformada del LLM, el sistema devuelve
  `Explanation(source="template")` sin propagar excepciones.
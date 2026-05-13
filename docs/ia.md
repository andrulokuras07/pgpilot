# Módulo `ia` — guía de la capa de integración con el LLM

> **Audiencia:** developers fuera del equipo de PgPilot que necesiten
> entender qué hace la capa de IA, qué garantías de privacidad y
> resiliencia ofrece, y cómo se protege al usuario de las
> alucinaciones del LLM.
>
> **Resumen en una línea:** la capa de IA **sanitiza** el SQL antes
> de mandarlo al LLM, **valida** la respuesta contra un schema
> Pydantic y la **cruza** contra el snapshot del schema y opcionalmente
> contra un sandbox antes de mostrársela al usuario. Si algo falla en
> el camino, **cae a plantilla determinística** sin romper la pipeline.

---

## 1. ¿Qué hace este módulo?

`ia/` cumple **cinco responsabilidades** y nada más:

1. **Sanitizar** todo SQL crudo antes de que el LLM lo vea (strings,
   números, fechas, UUIDs, emails → placeholders).
2. **Construir el prompt** al LLM con guardrails sistémicos (rol
   pedagógico, reglas inviolables, schema JSON acordado).
3. **Llamar al LLM** (Anthropic Messages API) con manejo elegante de
   "LLM apagado", red caída o API key ausente.
4. **Validar la respuesta** en dos capas: forma (Pydantic) y
   contenido (cruce contra schema + opcional sandbox).
5. **Degradar a plantilla** determinística siempre que cualquier capa
   anterior falle — la pipeline nunca crashea por culpa del LLM.

**Lo que NO hace este módulo:**

- No decide si una query tiene un anti-pattern — eso es `/motor`.
- No recomienda índices — eso es `/motor` también.
- No abre conexiones a la BD del cliente — eso es `/conector`.
- No valida sintaxis SQL contra una BD viva — eso es `/sandbox`.

**Regla #1 del proyecto, aplicada aquí:** *el motor decide, el LLM
explica*. Si en algún momento un componente de este módulo pidiera
al LLM que decida "¿esto es un anti-pattern?", la arquitectura del
producto se rompe. El LLM solo recibe **hechos ya determinados** por
el motor y produce prosa pedagógica + opcionalmente un rewrite
alternativo.

---

## 2. Pipeline de la capa de IA

```
                    SQL crudo del usuario (con literales)
                              │
                              ▼
                       sanitize()              ← B10
                              │
                              ▼
                  SanitizedQuery(sql, literals)
                  (los literales NUNCA viajan al LLM)
                              │
                              ▼
                 build_explanation_prompt()    ← C4
                              │
                              ▼
                  LLMPrompt(system, messages)
                              │
                              ▼
                         call_llm()             ← C4
                              │           (Anthropic Messages API)
                              ▼
                  texto crudo del LLM
                              │
                              ▼
                  parse_llm_response()         ← C5 (Pydantic)
                              │
              ┌───────────────┴───────────────┐
              ▼ válido                        ▼ inválido tras reintentos
        cross_validate()                explain_from_template()  ← C7
              │
   ┌──────────┴──────────┐
   ▼ passed              ▼ failed
Explanation         explain_from_template()
(source="llm")      (source="template")
              │
              ▼
        log_llm_interaction()            ← C8 (JSONL)
              │
              ▼
        Explanation                      → consumido por /backend
        (la única excepción que SÍ
         escapa es algo no previsto;
         el orquestador la atrapa
         con su propia red de E8)
```

Cada flecha es deterministica y testeable de forma aislada. El único
nodo que **puede** depender de red es `call_llm()` — y todo lo
demás está blindado para tolerar que ese nodo falle.

---

## 3. Sanitización (B10/B11)

**Esta es la garantía de privacidad del producto.** El LLM nunca ve
literales del SQL del usuario. Cubrimos cinco tipos:

| Sufijo | Tipo | Regex (resumido) | Ejemplo de literal | Placeholder emitido |
|---|---|---|---|---|
| `1` | `string` | comillas simples (`''` escapado) o dobles | `'juan@empresa.com'` | `$LITERAL_1_1` |
| `2` | `number` | enteros y decimales | `42`, `3.14` | `$LITERAL_2_1` |
| `3` | `date` | ISO 8601 con hora opcional | `2026-01-15`, `2026-01-15T12:00:00` | `$LITERAL_3_1` |
| `4` | `uuid` | formato canónico 8-4-4-4-12 | `550e8400-e29b-41d4-a716-446655440000` | `$LITERAL_4_1` |
| `5` | `email` | `usuario@dominio.tld` (cuando no está entre comillas) | `juan@empresa.com.mx` | `$LITERAL_5_1` |

### 3.1. `sanitize(sql: str) -> SanitizedQuery`

Función pura. Devuelve `SanitizedQuery(sql, literals)`:

- `sql` — el SQL con cada literal reemplazado por un placeholder
  determinístico (`$LITERAL_<tipo>_<i>`).
- `literals` — `{"LITERAL_<tipo>_<i>": {"type": ..., "original": ...}}`.
  Este mapa **se queda local**, jamás se envía al LLM. Es solo para
  poder reconstruir la query si el caller lo necesita en debug.

**Garantías:**

- **Ningún valor original aparece en `sanitized.sql`** — verificado
  por un test específico de privacidad (B11) que hace `grep` externo
  sobre el output con un email real, un RFC mexicano y un número de
  tarjeta.
- **Funciona aunque el SQL no parsee con sqlglot.** El sanitizador es
  regex puro — si la query es sintácticamente rara, los placeholders
  igual se aplican.
- **Patrones de más específico a más general.** Los strings primero
  (se tragan todo lo entre comillas como bloque), luego emails y
  UUIDs (dentro de strings), después fechas, y finalmente números.
  Matches solapados se descartan.

### 3.2. Ejemplo

```python
from ia import sanitize

raw = """SELECT * FROM users
         WHERE email = 'juan@empresa.com.mx'
           AND created_at >= '2026-01-01'
           AND id = 42
           AND uuid_token = '550e8400-e29b-41d4-a716-446655440000'"""

q = sanitize(raw)
print(q.sql)
# SELECT * FROM users
# WHERE email = $LITERAL_1_1
#   AND created_at >= $LITERAL_1_2
#   AND id = $LITERAL_2_1
#   AND uuid_token = $LITERAL_1_3

print(q.literals["LITERAL_1_1"])
# {'type': 'string', 'original': "'juan@empresa.com.mx'"}
```

> Nota: en este ejemplo el email y el UUID quedan **dentro de strings**,
> así que el sanitizador los trata como `string` (sufijo `1`). Cuando
> aparecen sin comillas (raro en SQL pero posible en logs de error o
> queries dinámicas), los patrones de `email`/`uuid` los capturan
> directamente.

### 3.3. `restore(sanitized: SanitizedQuery) -> str`

Reconstruye el SQL original. **Sólo para debug local.** No usar el
output de `restore()` para enviar al LLM — si lo hicieras, violarías
R4 y la garantía de privacidad.

### 3.4. Test de privacidad (B11)

`tests/ia/test_privacidad.py` ejecuta dos validaciones defensivas
para Q&A del Demo Day:

1. Sanitiza una query con datos sensibles reales (`juan.perez@empresa.com.mx`,
   RFC mexicano `GODE561231GR8`, número de tarjeta `4532015112830366`),
   escribe el `sanitized.sql` a un archivo temporal y verifica con
   `subprocess.run(["grep", ...])` que ninguno de esos valores aparece.
2. Confirma que los datos sí siguen disponibles en
   `sanitized.literals` para que `restore()` pueda reconstruir
   localmente.

---

## 4. Prompt al LLM (C4)

### 4.1. `build_explanation_prompt(detection, plan, recommendation, sanitized_query) -> LLMPrompt`

Función pura. Recibe los outputs del motor (`Detection`,
`ExplainResult`, `Recommendation`) más el `SanitizedQuery`, y
devuelve un `LLMPrompt(system, messages, expected_output_schema)`
listo para `call_llm`.

**Defensa en profundidad para R4:** la función lanza `TypeError` si
`sanitized_query` no es un `SanitizedQuery`. Esto evita que un caller
mande un string crudo por accidente y filtre literales al LLM.

```python
from ia import build_explanation_prompt, sanitize

prompt = build_explanation_prompt(
    detection=det,                        # de motor.detect_*
    plan=plan,                            # de motor.parse_explain
    recommendation=rec,                   # de motor.recommend
    sanitized_query=sanitize(raw_sql),    # SanitizedQuery, no str
)
print(prompt.system)             # rol pedagógico + reglas inviolables
print(prompt.messages[0])        # user turn con el payload JSON
```

### 4.2. System prompt — rol pedagógico

El system prompt le dice al LLM **exactamente** tres cosas y le
prohíbe el resto:

1. **EXPLICAR** el anti-pattern en lenguaje claro para developers de
   nivel intermedio.
2. **PROPONER** opcionalmente una reescritura alternativa. Si no se
   le ocurre una clara, `suggested_rewrite=null`. *No inventar.*
3. **DAR** un nivel de confianza `[0, 1]` sobre la explicación.

**Reglas inviolables emitidas al modelo:**

- No contradecir al motor (R1).
- No inventar nombres de tablas, columnas o índices (R14).
- No reemplazar los placeholders `$LITERAL_<i>_<j>` por valores
  inventados — preservarlos en la respuesta.
- Output **estricto en JSON** con el schema acordado, sin markdown ni
  prosa fuera del JSON.

### 4.3. User payload

El user turn lleva en JSON compacto y determinístico:

```jsonc
{
  "detection": {"found": true, "confidence": 1.0, "matches": [{...}]},
  "recommendation": {"kind": "create_index", "table": "...", "column": "...", "create_index_sql": "...", "selectivity": 0.002, ...},
  "plan_summary": [{"node_type": "Seq Scan", "relation_name": "...", "plan_rows": 500000, ...}, ...],
  "sanitized_query": "SELECT … WHERE col = $LITERAL_2_1",
  "literal_placeholders": {"LITERAL_2_1": {"type": "number"}}
}
```

`literal_placeholders` **solo contiene el tipo** del placeholder
(`number`/`string`/`date`/…), **nunca el valor original**. El LLM
sabe "aquí va un número" pero no qué número específicamente.

### 4.4. `call_llm(prompt, *, model=..., max_tokens=..., timeout=..., api_key=None) -> str`

Llama al endpoint `messages` de Anthropic vía `httpx`. Devuelve el
texto crudo de la respuesta (sin parsear — C5 valida con Pydantic).

| Variable | Default | Comportamiento |
|---|---|---|
| `model` | `claude-sonnet-4-6` | Configurable por-call. |
| `max_tokens` | `1024` | Suficiente para una explicación + rewrite corto. |
| `timeout` | `30` segundos | Para evitar cuelgues del cliente. |
| `api_key` | `ANTHROPIC_API_KEY` del entorno | Override por-call para tests. |

**Manejo de errores:**

| Condición | Excepción | Acción del orquestador |
|---|---|---|
| `LLM_ENABLED=false` en env | `LLMDisabledError` | → plantilla |
| Sin `ANTHROPIC_API_KEY` | `LLMDisabledError` | → plantilla |
| HTTP error / red caída / timeout | `LLMError` | → plantilla |

**Defensa en profundidad — strip de fences markdown:** verificado
empíricamente (2026-05-11) que Claude tiende a envolver el JSON en
` ```json ... ``` ` incluso cuando el system-prompt lo prohíbe.
`call_llm` quita la fence cuando envuelve TODO el output. Fences
embebidas dentro de prosa (ej. ejemplo de SQL dentro de una
explicación) se preservan.

---

## 5. Validación Pydantic (C5)

### 5.1. `LLMResponseSchema`

Schema Pydantic v2 del JSON acordado en el system-prompt:

| Campo | Tipo | Reglas |
|---|---|---|
| `explanation` | `str` | `min_length=1`. |
| `suggested_rewrite` | `str \| None` | Opcional. Si presente, debe parsear con sqlglot (lo verifica C6). |
| `confidence` | `float` | `ge=0.0, le=1.0`. |

Campos extra emitidos por el LLM se ignoran silenciosamente (default
de Pydantic v2). Esto tolera que el modelo agregue contexto
adicional sin romper la pipeline.

### 5.2. `parse_llm_response(raw: str) -> LLMResponseSchema`

Función pura. Parsea + valida en un solo paso. Levanta
`LLMResponseInvalid(reason, raw)` ante JSON malformado o schema
incorrecto. El campo `raw` se preserva para logs (C8) — útil para
debug post-mortem.

### 5.3. `request_validated_explanation(prompt, *, max_retries=1, ...) -> LLMResponseSchema`

Llama al LLM (`call_llm`), valida la respuesta y, si es inválida,
**reintenta hasta `max_retries` veces** (default 1, según el
backlog C5). Si tras todos los intentos sigue siendo inválida, levanta
`LLMResponseInvalid`. El orquestador la atrapa y cae a plantilla.

No atrapa `LLMDisabledError` ni `LLMError`: el orquestador les da el
mismo tratamiento (todos → plantilla).

---

## 6. Validación cruzada (C6)

Después de que C5 valida la **forma** del JSON, C6 valida el
**contenido contra la realidad**: las columnas mencionadas existen,
los nombres de índice no están inventados, el SQL parsea.

### 6.1. `cross_validate(response, recommendation, snapshot, *, sandbox_pool=None, sanitized_sql=None) -> CrossValidationResult`

Aplica **cuatro reglas** en orden. Todas se corren; se reportan todas
las que fallen.

| # | Regla | Si falla |
|---|---|---|
| 1 | La columna del `Recommendation` existe en la tabla del snapshot. | Sugerencia descartada. |
| 2 | Si `kind="create_index"`, el nombre del índice propuesto no existe ya en la tabla. | Sugerencia descartada (R3 explícito del backlog). |
| 3a | Si `suggested_rewrite` está presente, parsea con `sqlglot` dialect `postgres`. | Sugerencia descartada. |
| 3b | Si el rewrite contiene `CREATE INDEX`, ese nombre no debe existir en el schema (los nombres de índice son scope-schema en Postgres). | Sugerencia descartada. |
| 3c | Todas las columnas referenciadas en el rewrite existen en algún table del snapshot. | Sugerencia descartada. |
| 4 *(opcional)* | Si `sandbox_pool` y `sanitized_sql` se pasan: `sandbox.validate_index_recommendation` no devuelve `"discarded"`. | Sugerencia descartada. |

### 6.2. `CrossValidationResult`

| Campo | Tipo | Descripción |
|---|---|---|
| `passed` | `bool` | `True` si TODAS pasaron. `False` si alguna falla. |
| `reasons` | `list[str]` | Prosa diagnóstica de las reglas que fallaron. Vacía cuando pasa. Consumida por C8. |
| `sandbox_verdict` | `str \| None` | `"validated"` / `"discarded"` / `"skipped_no_sandbox_signal"` cuando se corrió la regla #4. `None` si no se corrió. |

**Diseño conservador:** ante cualquier inconsistencia, falla y se
descarta la respuesta del LLM. La regla #1 del proyecto implica que
descartar al LLM nunca es un costo alto — siempre hay plantilla.

---

## 7. Modo "LLM apagado" (C7)

PgPilot debe funcionar **sin LLM** (regla R5). Esto cubre tres
escenarios reales:

- El cliente tiene compliance que prohíbe llamadas externas
  (LLM_ENABLED=false).
- No hay API key configurada.
- El LLM responde basura o se cae.

### 7.1. `Explanation` (frozen dataclass)

Tipo común de salida tanto del camino LLM como del de plantilla:

| Campo | Tipo | Descripción |
|---|---|---|
| `explanation` | `str` | Prosa al usuario. |
| `suggested_rewrite` | `str \| None` | Siempre `None` en plantilla; posiblemente string en LLM. |
| `confidence` | `float` | 0..1. |
| `source` | `Literal["llm", "template"]` | Distingue cuál generó la explicación. |

El frontend usa `source` para mostrar la etiqueta "explicación
generada sin IA" cuando aplica. **Esta etiqueta es honestidad
visible para el usuario** — sabe si la prosa la escribió un humano
con plantilla o un LLM.

### 7.2. `explain_from_template(detection, recommendation) -> Explanation`

Genera prosa determinística a partir de `Detection` + `Recommendation`.
Sin red, sin LLM. Dos plantillas:

- **`kind="create_index"`** — cómo funciona un Seq Scan vs. Index
  Scan, por qué la columna seleccionada lo arregla, y el SQL del
  motor.
- **`kind="analyze"`** — stats desactualizadas + `ANALYZE` como
  remedio.

La confianza baja a **0.6** si la recomendación no tiene
selectividad (tabla sin ANALYZE); **0.8** cuando sí. La prosa
incluye los campos `justification` y `expected_impact` ya armados
por el recomendador (`motor.recommend`).

---

## 8. Orquestador `explain_recommendation`

### 8.1. Firma

```python
def explain_recommendation(
    detection: Detection,
    plan: ExplainResult,
    recommendation: Recommendation,
    sanitized_query: SanitizedQuery,
    *,
    snapshot: dict[str, Any],
    sandbox_pool: ConnectionPool | None = None,
    max_retries: int = 1,
    request_id: str | None = None,
) -> Explanation:
    ...
```

### 8.2. Los 5 caminos posibles

| # | Camino | Condición | Resultado |
|---|---|---|---|
| 1 | `llm_ok` | LLM responde válido, Pydantic OK, C6 pasa | `Explanation(source="llm")` con la prosa del LLM |
| 2 | `llm_disabled` | `LLM_ENABLED=false` o sin API key | `Explanation(source="template")` |
| 3 | `llm_error` | Red caída, timeout, error HTTP | `Explanation(source="template")` |
| 4 | `llm_invalid_response` | LLM responde basura, falla Pydantic tras reintentos | `Explanation(source="template")` |
| 5 | `cross_validation_failed` | LLM responde válido pero C6 descarta | `Explanation(source="template")` |

**Garantía dura:** el orquestador **nunca propaga** `LLMDisabledError`,
`LLMError` ni `LLMResponseInvalid` al backend. La pipeline degrada
elegante en los cinco caminos.

`request_id` opcional se propaga al log estructurado de C8 para
correlación con la request HTTP del backend. Si no se pasa, `ia.logs`
genera un UUID por sí mismo.

---

## 9. Logs estructurados (C8)

Cada interacción con el LLM (o intento de) deja una línea en un
archivo **JSON Lines** local. Es la herramienta de auditoría para
debug post-mortem y la respuesta a "¿qué le dijiste exactamente al
LLM y qué respondió?".

### 9.1. `log_llm_interaction(record: dict[str, Any]) -> Path | None`

Append una entrada al archivo de logs. Devuelve la ruta usada, o
`None` si:

- El logger está deshabilitado (`PGPILOT_LLM_LOG_DISABLED=true`), o
- La escritura falló por `OSError` (disco lleno, permisos, etc.).

**Nunca propaga excepciones** — el log es side-effect, no debe
romper la pipeline (R5 a nivel logger). Internamente toma un lock
global para no intercalar líneas en escrituras concurrentes.

### 9.2. Configuración por entorno

| Variable | Default | Efecto |
|---|---|---|
| `PGPILOT_LLM_LOG_PATH` | `logs/llm_interactions.jsonl` | Ruta del archivo de logs. |
| `PGPILOT_LLM_LOG_DISABLED` | unset (loggea) | `=true` apaga el logger. |

`logs/` y `*.jsonl` están en `.gitignore` — cada dev acumula sus
propias interacciones. En producción el operador puede rotar el
archivo (logrotate, cron) — el logger solo hace append.

### 9.3. Schema de cada línea

```jsonc
{
  "timestamp": "2026-05-13T20:34:12.345+00:00",
  "request_id": "uuid hex",
  "outcome": "llm_ok",                                  // 1 de 5 outcomes
  "detection": {
    "found": true,
    "confidence": 1.0,
    "matches_count": 1,
    "first_match_table": "public.posts",
    "first_match_column": "author_id"
  },
  "recommendation": {
    "kind": "create_index",
    "table": "public.posts",
    "column": "author_id",
    "index_name": "idx_posts_author_id",
    "selectivity": 0.002
  },
  "sanitized_sql": "SELECT … WHERE x = $LITERAL_2_1",   // R4: nunca el valor real
  "placeholders_count": 1,
  "llm": {
    "called": true,
    "raw_response_excerpt": "primeros 4000 chars",
    "raw_response_length": 1234,
    "pydantic_passed": true,
    "cross_validation_passed": true,
    "cross_reasons": [],
    "sandbox_verdict": "validated",                      // o null
    "error": null
  },
  "final_shown": {
    "source": "llm",                                     // o "template"
    "confidence": 0.93,
    "has_suggested_rewrite": false,
    "explanation_excerpt": "primeros 200 chars"
  }
}
```

**Propiedad importante:** el log guarda **`sanitized_sql`**, no el
SQL crudo. La privacidad del usuario se preserva incluso en los
logs (R4 transversal). El `raw_response_excerpt` del LLM tampoco
contiene literales — el LLM nunca los vio.

### 9.4. Helpers expuestos

| Helper | Para qué |
|---|---|
| `is_logging_enabled() -> bool` | Refleja el estado actual del entorno. |
| `resolve_log_path() -> Path` | Ruta efectiva (default o del env). |
| `LLMOutcome` | `Literal` con los 5 outcomes válidos. |
| `DEFAULT_LOG_PATH` | `"logs/llm_interactions.jsonl"`. |

---

## 10. Garantías para el usuario

Tres garantías contractuales — las preguntas del Demo Day se
responden directamente con ellas:

### 10.1. Privacidad (R4)

- El SQL crudo se sanitiza **antes** de cualquier llamada al LLM.
- Los literales originales **nunca** salen del proceso PgPilot.
- El test de privacidad (`tests/ia/test_privacidad.py`) prueba esto
  empíricamente con `grep` externo sobre el output sanitizado.
- Los logs estructurados también guardan solo el SQL sanitizado.
- El `build_explanation_prompt` lanza `TypeError` si recibe un
  string crudo en vez de un `SanitizedQuery` — defensa en
  profundidad contra bugs futuros.

### 10.2. Anti-alucinaciones (R3 + R14)

- Pydantic valida la **forma** de la respuesta (5 reglas → C5).
- `cross_validate` valida el **contenido** contra el snapshot del
  schema (4 reglas → C6): columnas existentes, índices no
  duplicados, SQL parseable.
- Validación opcional contra sandbox (`sandbox.validate_index_recommendation`)
  cuando el caller lo activa.
- Ante cualquier fallo de validación: la respuesta del LLM se
  **descarta** y se muestra la plantilla determinística.

### 10.3. Resiliencia (R5)

- `LLM_ENABLED=false` → plantilla.
- Sin API key → plantilla.
- Red caída, timeout, 5xx → plantilla.
- Respuesta basura tras reintentos → plantilla.
- Validación cruzada falla → plantilla.

**La pipeline nunca crashea por culpa del LLM**, en ninguno de los
cinco caminos posibles.

---

## 11. Configuración y ejecución

### 11.1. Variables de entorno

| Variable | Default | Efecto |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Si está unset, todas las llamadas → plantilla. |
| `LLM_ENABLED` | unset (= enabled) | `=false` fuerza modo plantilla. |
| `PGPILOT_LLM_LOG_PATH` | `logs/llm_interactions.jsonl` | Override del archivo de logs. |
| `PGPILOT_LLM_LOG_DISABLED` | unset | `=true` apaga el logger entero. |

### 11.2. Correr los tests

```bash
# Unit tests (sin red, sin API key)
pytest tests/ia -m "not integration and not llm"

# Tests con LLM real (requiere ANTHROPIC_API_KEY)
ANTHROPIC_API_KEY=sk-... pytest tests/ia -m llm
```

Los tests con marker `llm` están **skipped automáticamente** si no
hay API key en el entorno — así el CI no falla por falta de credenciales.

### 11.3. Estructura de tests

| Archivo | Cobertura |
|---|---|
| `test_sanitizer.py` | B10 — los 5 tipos, casos límite, escapado `''`. |
| `test_privacidad.py` | B11 — grep externo sobre el output con datos reales (email, RFC, número de tarjeta). |
| `test_prompt.py` | C4 — forma del prompt, defensa R4, determinismo. |
| `test_llm.py` | C4 — happy path / errores con `monkeypatch` sobre `httpx`; 1 test real con `@pytest.mark.llm`. |
| `test_response_validator.py` | C5 — Pydantic schema, reintentos, JSON malformado. |
| `test_cross_validator.py` | C6 — las 4 reglas + el modo sandbox opcional. |
| `test_templates.py` | C7 — plantillas mencionan tabla/columna, incluyen SQL, bajan confianza sin selectividad. |
| `test_explain_orchestrator.py` | Integración C5+C6+C7 — los 5 caminos del orquestador. |
| `test_logs.py` | C8 — helpers puros, persistencia, toggle por env, resiliencia ante `OSError`. |

---

## 12. Limitaciones conocidas

- **El sanitizador es regex puro, no parser SQL.** Esto es deliberado
  (resiliencia ante SQL no estándar) pero implica que columnas con
  nombres tipo `email_2026` podrían sufrir interferencia si el regex
  de `date` matchea por accidente. Mitigación: revisar el orden de
  patrones; los strings tienen prioridad y se tragan todo lo entre
  comillas como bloque.
- **No detectamos PII no-literal.** Si el usuario pone un comentario
  SQL `-- cliente: María González` en la query, ese comentario viaja
  al LLM. Mitigación pendiente: stripear comentarios antes de
  sanitizar.
- **El cross-validator solo valida identificadores, no semántica.**
  Si el LLM propone un rewrite que cambia los resultados de la query
  (ej. `LEFT JOIN` → `INNER JOIN`), C6 no lo detecta. La validación
  semántica vive en el sandbox vía cambio de plan; activarla requiere
  pasar `sandbox_pool` y `sanitized_sql`.
- **`max_retries=1` por default.** Si el LLM responde basura dos
  veces seguidas, cae a plantilla. Subirlo encarece la latencia y no
  mejora mucho — un modelo que falla la forma 2 veces probablemente
  fallará la tercera.
- **Logs en `.jsonl` plano.** No hay rotación automática ni
  redacción adicional más allá de la sanitización. En producción
  el operador es responsable de logrotate y de respetar políticas
  de retención.
- **Costo por llamada al LLM.** Cada análisis hace una llamada al
  modelo configurado (`claude-sonnet-4-6` por default). En cargas
  pesadas puede convenir cambiar a Haiku (más barato, menos prosa
  pulida) o cachear explicaciones por `(código_detector, tabla, columna)`
  — fuera de scope del módulo actual.

---

## 13. Cómo extender

### 13.1. Añadir un patrón de sanitización nuevo

Cinco pasos en `ia/sanitizer.py`:

1. Añadir el `Literal` al `LiteralType` (ej. `"phone_number"`).
2. Agregar la entrada al `_TYPE_SUFFIX` con el sufijo nuevo (ej. `6`).
3. Insertar la tupla `(tipo, regex)` en `_PATTERNS` **en la posición
   correcta** — del más específico al más general.
4. Agregar tests en `tests/ia/test_sanitizer.py` (happy path + caso
   donde NO debe matchear).
5. Actualizar la tabla de la sección 3 de este doc.

### 13.2. Cambiar el modelo Claude usado

`call_llm(prompt, model="claude-haiku-4-5-20251001", ...)`. El cambio
no requiere tocar el resto de la pipeline — C5 (Pydantic) y C6
(cruce) son agnósticos al modelo. Sugerimos correr el test
`@pytest.mark.llm` después de cambiarlo, para confirmar que el modelo
nuevo respeta el schema acordado.

### 13.3. Añadir una regla a la validación cruzada

En `ia/cross_validator.py::cross_validate`, agregar el bloque de
verificación dentro del cuerpo. Convención: si la verificación falla,
añadir un string descriptivo a `reasons` y marcar `passed=False` al
final. Tests en `tests/ia/test_cross_validator.py`.

### 13.4. Soportar un nuevo outcome de C8

Si introduces un camino nuevo en el orquestador (más allá de los 5
actuales), añadirlo al `LLMOutcome` Literal en `ia/logs.py` y emitir
el record correspondiente desde `explain_recommendation`.

---

## 14. Referencias

- **Código fuente:** [`ia/`](../ia/) en la raíz del repo.
- **Notas internas para mantenedores:**
  [`ia/CLAUDE.md`](../ia/CLAUDE.md).
- **Reglas del proyecto** (R1, R3, R4, R5, R14):
  [`RULES.md`](../RULES.md) en la raíz del repo.
- **Documentación de módulos relacionados:**
  - [`docs/conector.md`](conector.md) — de dónde viene el snapshot
    que C6 usa para cruzar identificadores.
  - [`docs/motor.md`](motor.md) — de dónde vienen `Detection` y
    `Recommendation` que el prompt y los validadores consumen.
- **Decisiones técnicas:** `PROGRESS.md` — entradas relevantes
  2026-05-09 (sanitizador, test de privacidad), 2026-05-10
  (prompt C4, validador C5+C6, plantillas C7), 2026-05-11
  (orquestador C8 + strip de fences), 2026-05-13 (E8 aislamiento de
  errores en el endpoint del backend que llama a esta capa).

Si encuentras algo confuso o falta documentar un escenario, abrí un
issue en el repo de PgPilot.

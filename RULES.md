# Reglas técnicas inviolables

Estas reglas aplican a todo el proyecto sin excepción. Si una regla bloquea un avance, escala al equipo antes de saltártela; no decidas en solitario que "esta vez no aplica".

## Reglas de arquitectura del producto

### R1. El motor decide, el LLM explica

Los detectores de anti-patterns son funciones puras Python. Reciben el árbol del plan parseado y la metadata del schema, devuelven `Detection(found, confidence, evidence)`. **Nunca consultan al LLM para decidir si algo es un anti-pattern.**

El LLM solo se usa para:

- Generar prosa pedagógica que explique una detección que ya existe
- Proponer reescrituras alternativas de queries

Si te encuentras pasándole al LLM una query y preguntando "¿esto está mal?", estás violando R1. Detente.

### R2. Detección sobre estructura, no sobre strings

Los detectores operan sobre el árbol del plan parseado y sobre la metadata del schema. **Está prohibido detectar anti-patterns con regex sobre el SQL crudo o sobre el texto del EXPLAIN.**

Ejemplo correcto: el detector de seq scan busca nodos del tipo `Seq Scan` en el árbol y verifica `pg_class.reltuples` de la tabla y existencia de índice en la columna del filtro.

Ejemplo prohibido: `if "Seq Scan" in explain_output: ...`

Esta regla protege el bonus de AppDB v2: detección estructural sobrevive el cambio de nombres de tabla.

### R3. Toda salida del LLM se valida antes de mostrarla

Cuando el LLM propone un índice o un rewrite, antes de mostrarlo al usuario el sistema verifica:

1. Las columnas mencionadas existen en el schema
2. El índice propuesto no existe ya
3. La sintaxis SQL es válida (parseable con sqlglot)
4. El sandbox confirma con `EXPLAIN` que el planner usaría el índice y el costo baja

Si cualquier validación falla, la sugerencia del LLM se descarta y se muestra el output del motor determinístico. Esto se loggea (no se silencia).

### R4. Nunca enviar literales al LLM

Toda query que va al LLM pasa primero por `ia/sanitizer.py`. Strings, números, fechas, UUIDs y emails se reemplazan por placeholders. Esta regla es absoluta y aplica también a logs, traces y mensajes de debug.

Cualquier llamada nueva al LLM debe tener un test que verifique que el sanitizador se aplicó.

### R5. El producto debe funcionar sin LLM

Existe un toggle global `LLM_ENABLED`. Cuando está apagado, el sistema responde con explicaciones generadas por plantillas a partir de los datos de la detección. Cualquier código que dependa del LLM debe tener su rama "LLM apagado" cubierta. Tests obligatorios para ambas ramas.

### R6. Sandbox no copia datos, solo schema y stats

El sandbox monta schemas temporales con tablas vacías y stats falseadas via `pg_set_relation_stats` y `pg_set_attribute_stats`. **Está prohibido copiar filas de AppDB o de cualquier BD cliente al sandbox.** `EXPLAIN` sin `ANALYZE` no necesita filas reales.

### R7. Conexiones a la BD del cliente son siempre read-only

El módulo `/conector` fuerza `SET TRANSACTION READ ONLY` en cada conexión. **Está prohibido emitir DDL, INSERT, UPDATE, DELETE, TRUNCATE o cualquier statement de escritura contra la BD del cliente.** Si necesitas probar una mutación, va al sandbox.

## Reglas de código

### R8. Type hints obligatorios en Python

Todo módulo Python usa type hints. Funciones públicas tienen tipos en parámetros y return. Modelos de datos son `dataclass` o `pydantic.BaseModel`. CI rechaza código sin tipos en funciones públicas.

### R9. Funciones puras donde sea posible

Especialmente en `/motor`: los detectores y el recomendador son funciones puras. No leen archivos, no hacen llamadas de red, no dependen de estado global. Reciben todo lo que necesitan como argumentos.

Esto hace los tests triviales y el comportamiento determinista.

### R10. Tests con cada feature nueva

Cada función pública nueva incluye al menos un test (happy path) en `/tests/{módulo}/`. Los detectores incluyen además un test "negativo" (caso donde NO se debe detectar) para evitar falsos positivos.

PR sin tests no se mergea.

### R11. Black + isort antes de commit

Todo Python pasa por `black` e `isort` antes de commit. Recomendado: pre-commit hook. CI rechaza código mal formateado.

### R12. Frontend usa hooks, no clases

Solo componentes funcionales con hooks. No `class Component`. Estilos con Tailwind o CSS modules; nada de styled-components ni emotion.

### R13. Nombres significativos

- Detectores: `detect_seq_scan_on_large_table`, no `detector1`
- Tests: `test_seq_scan_detected_when_table_large_and_index_exists`, no `test_1`
- Commits: `feat(motor): agrega detector de subquery correlacionada`, no `cambios`
- Branches: `feat/motor-detector-subquery`, no `dev` o `andres-rama`

### R14. No hardcodear nombres de tablas o columnas

Los detectores y recomendadores nunca contienen literales tipo `"users"` o `"email"`. Operan sobre los nombres que llegan en el schema/plan. Si lo violas, el bonus de AppDB v2 se pierde.

## Reglas de proceso

### R15. Documentación obligatoria al cerrar una actividad

Cuando un agente cierra una actividad del backlog **debe hacer las dos cosas siguientes antes de hacer `git push`**:

1. **Agregar entrada en `PROGRESS.md`** bajo el día actual con: código de actividad cerrada, resumen de 1-2 líneas, archivos modificados, decisiones que se tomaron (si las hubo)
2. **Actualizar el `CLAUDE.md` del módulo afectado** si el cambio modifica:
   - La API pública del módulo (funciones expuestas, su firma o su comportamiento)
   - El formato de los datos que produce o consume
   - La lista de detectores, validaciones o reglas implementadas
   - Cualquier convención que un agente futuro deba conocer para seguir el patrón

Si el cambio no afecta nada de lo anterior (ej: refactor interno, fix de bug menor), basta con `PROGRESS.md`. Pero pregúntate honestamente: ¿el siguiente agente que toque este módulo necesita saber esto? Si sí, va en el `CLAUDE.md` del módulo actual.

**Esta regla es obligatoria.** Antes de hacer `git push` de la rama que cierra una actividad, verifica que las actualizaciones de documentación están en los commits. Si se te olvidó, agrega la documentación en un commit adicional antes del push.

**Recordatorio práctico para usar con Claude Code:** antes de pedirle que haga commit final o push, dile:

> Antes de hacer push, recordatorio R15: ¿qué hay que actualizar en `PROGRESS.md` y en algún `CLAUDE.md` de módulo según los cambios de esta rama?

### R16. Standup diario

15 minutos, mismo horario, los 9 días. Cada uno responde tres preguntas: qué hice, qué voy a hacer, qué me bloquea. Si alguien no puede asistir, deja sus tres respuestas escritas en el canal antes del horario.

### R17. Pull Requests con review entre miembros

Aunque la rama `main` no esté técnicamente protegida en GitHub, **nadie hace push directo a `main` ni mergea su propio PR sin revisión.** Esto aplica por convención del equipo, no por bloqueo de la herramienta.

Flujo correcto para cualquier cambio:

1. Crear una rama desde `main`: `git checkout -b tipo/descripcion-corta`
2. Trabajar y hacer commits en esa rama
3. Antes de `git push`, verificar regla R15 (documentación)
4. Pushear la rama y abrir Pull Request en GitHub
5. Confirmar que el código está bien antes del merge

### R18. Commits distribuidos entre los 5 miembros

`git shortlog -sn` se revisa al final del proyecto. Si una persona tiene >70% de los commits, hay desbalance que afecta la nota individual. Si vas demasiado adelantado y alguien va atrás, ayuda mediante pair programming, no programando por el otro.

### R19. Ningún miembro programa todo en una sola rama

Cada feature o actividad va en su rama, se mergea, se borra. Ramas que viven más de 3 días se vuelven imposibles de mergear.

### R20. Decisiones técnicas se documentan en PROGRESS.md el mismo día

Si el equipo decide cambiar una librería, modificar un contrato entre módulos, o aceptar un trade-off importante, queda anotado en `PROGRESS.md` bajo "Decisiones" el mismo día. No "ya lo recordamos al final".

## Anti-patterns prohibidos

Lista negra de cosas que rompen el producto o la nota:

- ❌ Detectar anti-patterns con regex sobre SQL crudo
- ❌ Hardcodear nombres de tablas, columnas o queries específicas de AppDB
- ❌ Llamar al LLM sin sanitizar literales
- ❌ Mergear sin tests
- ❌ Push directo a `main` (incluso sin protección activa)
- ❌ Commits genéricos ("fix", "cambios", "wip")
- ❌ Copiar datos de la BD cliente al sandbox
- ❌ Que el LLM tenga la palabra final en una recomendación
- ❌ Hacer `git push` sin actualizar `PROGRESS.md` cuando se cierra una actividad
- ❌ "Resolverlo después" para algo que la rúbrica evalúa explícitamente

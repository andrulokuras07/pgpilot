# Decisiones del equipo — PgPilot

Bitácora viva de decisiones técnicas y de producto. Se actualiza durante todo el proyecto. Alimenta después el documento de arquitectura (F2) y el documento de negocio (F15).

**Cómo se usa:**
- Cada sección crece con el tiempo. No se borra contenido, solo se añade.
- Al cerrar una decisión, agregar entrada con fecha y autor.
- Si una decisión se revierte después, no borrar la original: agregar nueva entrada explicando el cambio.

---

## 1. Stack elegido

### Backend: Python 3.11+ con FastAPI
- **Decisión:** Python como lenguaje del backend, FastAPI como framework web.
- **Razón:** Python tiene el ecosistema más maduro para parsing de SQL (sqlglot, pglast) y validación estructurada (Pydantic), que son el corazón del producto. FastAPI da tipado fuerte con Pydantic, validación automática de request/response, y OpenAPI generado, sin overhead. El brief lo sugiere explícitamente.
- **Alternativa descartada:** Node/Express. Tiene buen soporte web pero ecosistema débil para parsing SQL profundo.

### Driver Postgres: psycopg (v3)
- **Decisión:** `psycopg` (v3, no `psycopg2`).
- **Razón:** API moderna, soporta async opcional, y permite forzar `SET TRANSACTION READ ONLY` por conexión sin trucos. Para nuestro caso de uso (queries cortas de análisis, no streaming masivo), no necesitamos asyncpg.
- **Alternativa descartada:** `asyncpg`. Más rápido pero su API no expone tan limpiamente el control de transacciones que necesitamos para el modo read-only forzado.

### Parser SQL: sqlglot
- **Decisión:** `sqlglot` para parseo y normalización de SQL.
- **Razón:** parser puro Python (sin dependencias C), multi-dialect, AST estable y documentado, y permite normalización (`sqlglot.optimizer.normalize`) que se usará para deduplicar queries en el workload analyzer.
- **Alternativa descartada:** `pglast`. Es el parser oficial de Postgres como librería, más fiel pero requiere compilación nativa y su AST es más verboso para nuestro caso.

### Validación de respuestas LLM: Pydantic v2
- **Decisión:** todas las respuestas del LLM se validan contra schemas Pydantic antes de usarse.
- **Razón:** clave para la regla #1 del producto. El LLM nunca devuelve "texto libre" que se confíe; devuelve JSON que pasa por Pydantic, y si falla la validación se descarta. Esto es defensa contra alucinaciones a nivel de tipos.

### Frontend: React + Vite + Monaco Editor + Tailwind
- **Decisión:** React 18 con Vite como bundler, `@monaco-editor/react` para editar SQL, Tailwind para estilos, tema oscuro.
- **Razón:** Vite da build instantáneo (vs Create React App). Monaco es el editor de VS Code, ya soporta SQL syntax highlight nativo y se ve profesional para el demo. Tailwind acelera el styling sin escribir CSS custom.
- **Alternativa descartada:** Next.js. Sobra; no necesitamos SSR ni routing complejo. Solo es un SPA con un editor y un panel de resultados.

### LLM: Anthropic Claude API
- **Decisión:** Claude API como proveedor del LLM.
- **Razón:** mejor seguimiento de instrucciones estructuradas (importante para JSON output validado), tool use estable, y los miembros del equipo ya tienen acceso. El prompt system se documenta en `/docs` como pide la rúbrica.
- **Alternativa descartada:** OpenAI. Funcionaría igual; la decisión es por familiaridad del equipo.

### BD analizada y sandbox: Postgres 16
- **Decisión:** Postgres 16 tanto para AppDB (target del análisis) como para el sandbox (validación de recomendaciones).
- **Razón:** AppDB la entrega el profesor en Postgres 16; el sandbox usa la misma versión para que `EXPLAIN` se comporte idéntico. Sandbox es contenedor efímero separado, schema-aislado por análisis.

### Despliegue: Docker Compose
- **Decisión:** todo el producto corre con `docker compose up`.
- **Razón:** requisito explícito del brief. Garantiza que el evaluador puede levantar el producto en máquina limpia sin instalar nada local.

### Testing: pytest + httpx
- **Decisión:** `pytest` para tests unitarios y de integración del backend; `httpx` para probar endpoints FastAPI.
- **Razón:** estándar de facto en Python, integración nativa con FastAPI, y permite tests de privacidad (B11) y aislamiento (E8) que la rúbrica revisa.

### Linter y formato: black + isort
- **Decisión:** `black` para formato, `isort` para imports.
- **Razón:** cero discusión sobre estilo, formato consistente entre los 5 miembros, corre en pre-commit.

---

## 2. Decisiones de arquitectura

*Decisiones de diseño del sistema: separación de responsabilidades entre módulos, contratos entre componentes, flujos de datos, patrones aplicados.*

### Puertos de Postgres: AppDB en 5434, sandbox en 5435
- **Fecha:** 2026-05-08
- **Autor:** Andrés Angulo
- **Contexto:** el backlog original asumía AppDB en 5432 y sandbox en 5433, pero el compose entregado por el profesor publica AppDB en 5434 (5432 y 5433 los ocupan TiendaDB y FintechDB de otros proyectos del curso).
- **Decisión:** respetar los puertos del profesor. AppDB en 5434, sandbox en 5435.
- **Razón:** el evaluador probablemente correrá los 3 productos del curso simultáneamente. Si tomamos 5432 chocamos con TiendaDB y `docker compose up` falla.
- **Trade-off:** desviación menor del backlog original, sin impacto en arquitectura.

### Init files de AppDB versionados en nuestro repo
- **Fecha:** 2026-05-08
- **Autor:** Andrés Angulo
- **Contexto:** el compose de AppDB depende de `./init/` y `postgresql.conf` que viven en el repo del profesor. Para cumplir el requisito del brief ("`docker compose up` sin más configuración"), necesitábamos esos archivos disponibles localmente.
- **Alternativas:** (a) instruir al evaluador a clonar dos repos, (b) copiar los archivos del profe a `/infra/appdb/` en nuestro repo.
- **Decisión:** opción (b).
- **Razón:** el brief es literal con "sin más configuración". Un solo comando, un solo repo.
- **Trade-off:** duplicación de archivos del profe. Si actualiza AppDB hay que sincronizar a mano y registrarlo en PROGRESS.

---

## 3. Trade-offs

*Decisiones donde se sacrificó algo conscientemente. Formato: qué se eligió, qué se sacrificó, por qué.*

*(Vacío al inicio.)*

---

## 4. Log de bloqueos

*Bloqueos técnicos o de equipo que afectaron el avance. Formato: fecha, descripción, cómo se destrabó.*

*(Vacío al inicio.)*

---

## Plantilla para nuevas entradas

```markdown
### [Título corto de la decisión]
- **Fecha:** YYYY-MM-DD
- **Autor:** Nombre (o "Equipo")
- **Contexto:** qué problema se resolvía
- **Alternativas:** A, B, C
- **Decisión:** se eligió X
- **Razón:** por qué X le ganó a las otras
- **Trade-off:** qué se sacrifica
```
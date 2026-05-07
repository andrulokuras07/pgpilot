# PgPilot

Analizador inteligente de queries Postgres que detecta anti-patterns, recomienda índices y sugiere reescrituras combinando un motor determinístico con una capa de IA con guardrails. Producto B2B para developers backend con Postgres en producción.

Proyecto final de SIS2404 (Bases de Datos Avanzadas), Universidad Anáhuac Querétaro. Equipo de 5 personas, Demo Day el 14 de mayo de 2026.

## La regla #1 del proyectos

**El motor determinístico detecta y decide. El LLM explica y propone. El motor valida lo que el LLM propone. Si el LLM contradice al motor, gana el motor.**

Si en algún momento un agente está a punto de escribir código donde "el LLM decide si hay un anti-pattern" o "el LLM elige el índice", está rompiendo la arquitectura del producto. Detente y revisa.

## Stack técnico

- **Backend:** Python 3.11+, FastAPI, psycopg (read-only forzado)
- **Parser SQL:** sqlglot
- **LLM:** Anthropic Claude API
- **Validación de respuestas:** Pydantic
- **Frontend:** React + Vite, Monaco editor, Tailwind, tema oscuro
- **BD analizada:** Postgres 16 (AppDB demo)
- **Sandbox:** segundo contenedor Postgres efímero
- **Despliegue:** docker-compose

Cualquier desviación del stack debe documentarse en `PROGRESS.md` con justificación.

## Estructura del repositorio

```
/conector       Conexión a Postgres, extracción de schema y pg_stats, modo offline
/motor          Parser de EXPLAIN, detectores de anti-patterns, recomendador de índices
/ia             Sanitizador de literales, prompts al LLM, validación cruzada
/workload       Procesamiento de pg_stat_statements, score de impacto
/sandbox        Postgres efímero para validar recomendaciones con EXPLAIN antes/después
/backend        FastAPI que orquesta: endpoint /analyze, /workload
/frontend       React + Monaco editor, panel de detecciones, comparativo before/after
/docs           Arquitectura, documentación de módulos
/docs/patterns  Catálogo de anti-patterns (uno por archivo .md)
/business       Documento de negocio, entrevistas, análisis competitivo
/tests          Tests automatizados (cada módulo tiene los suyos en /tests/{módulo})
/scripts        Scripts auxiliares (seed de sandbox, etc.)
```

Cada módulo (`/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`, `/frontend`) tiene su propio `CLAUDE.md` con detalles internos. Cárgalos con `@conector/CLAUDE.md` cuando trabajes en ese módulo.

## Comandos críticos

```bash
# Levantar todo el producto (AppDB + sandbox + backend + frontend)
docker compose up

# Solo las dos BDs (para desarrollo local del backend)
docker compose up appdb sandbox

# Frontend en desarrollo
cd frontend && npm run dev

# Backend en desarrollo
cd backend && uvicorn main:app --reload

# Tests del backend
pytest

# Tests con coverage
pytest --cov=. --cov-report=term-missing

# Linter
black . && isort .
```

## Cómo trabajar con este repo (instrucciones para agentes)

1. **Antes de tocar código en un módulo, carga su `CLAUDE.md`.** Por ejemplo, si vas a trabajar en detectores, carga `@motor/CLAUDE.md`.
2. **Lee `RULES.md` en cada sesión.** Las reglas de código son inviolables.
3. **Revisa `PROGRESS.md` antes de empezar.** Para saber qué actividad del backlog tomar y qué decisiones recientes pueden afectarte.
4. **Documenta antes de hacer push.** Al cerrar una actividad, antes de `git push` agrega entrada en `PROGRESS.md` Y actualiza el `CLAUDE.md` del módulo si cambiaste su comportamiento. Si el módulo no tiene `CLAUDE.md` todavía (porque eres la primera persona que trabaja ahí), créalo siguiendo la convención descrita abajo. Esta regla es obligatoria — ver R15 en `RULES.md`.
5. **Tests verdes antes de mergear.** Si rompes `main`, paga café.

## Convención para los `CLAUDE.md` de cada módulo

Cada carpeta de módulo (`/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`, `/backend`, `/frontend`) tiene su propio `CLAUDE.md` que documenta cómo funciona ese módulo internamente. La primera persona que trabaja en un módulo es responsable de crear su `CLAUDE.md`.

**Cuándo crearlo:** la primera vez que un agente abre un módulo y agrega código real (no placeholder). Antes del primer push de ese módulo.

**Qué debe contener (mínimo viable):**

- **Propósito del módulo:** 2-3 líneas sobre qué hace y qué NO hace
- **API pública:** qué funciones, clases o endpoints expone el módulo y qué reciben/devuelven
- **Estructura interna:** cómo están organizados los archivos dentro del módulo
- **Cómo extender:** si alguien necesita agregar algo (ej: un detector nuevo, un validador nuevo), cómo lo hace
- **Decisiones específicas del módulo:** convenciones que aplican solo aquí (ej: "todos los detectores devuelven `Detection(found, confidence, evidence)`")
- **Tests:** dónde están y cómo correrlos

**Cómo evolucionarlo:** cada vez que un agente cambia algo que afecta cómo otro agente debería usar o extender el módulo, actualiza el `CLAUDE.md` del módulo en el mismo push (regla R15).

Si trabajas en un módulo que ya tiene `CLAUDE.md`, cárgalo en tu sesión de Claude Code antes de empezar a programar (`@motor/CLAUDE.md` por ejemplo).

## Archivos de referencia

- `@RULES.md` — reglas técnicas y de proceso (inviolables)
- `@PROGRESS.md` — log de avance y decisiones del proyecto
- `@docs/patterns/` — catálogo de anti-patterns implementados
- Briefs originales del proyecto en `/docs/briefs/` (para consultar la rúbrica si hay duda)

## Criterios de éxito del proyecto

El producto debe alcanzar al menos:

- 16 de 20 queries plantadas detectadas correctamente en AppDB v1 (80% cobertura)
- Menos de 3 falsos positivos sobre queries sanas
- 4 de 5 queries nuevas detectadas en AppDB v2 (bonus de detección genérica)
- Modo "LLM apagado" funcional (resiliencia)
- Sanitización de literales antes de cualquier llamada al LLM (privacidad)
- Validación con sandbox de cada recomendación de índice (no alucinaciones)

Si una decisión de implementación pone en riesgo cualquiera de estos criterios, escálala al equipo antes de mergear.

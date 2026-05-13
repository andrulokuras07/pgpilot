# PgPilot

Analizador inteligente de queries Postgres que detecta anti-patterns,
recomienda índices y sugiere reescrituras combinando un motor
determinístico con una capa de IA con guardrails. Backend en Python
(FastAPI) + frontend en React + Vite.

**Regla #1 del proyecto:** el motor determinístico decide; el LLM
explica y propone; el motor valida lo que el LLM propone. Si el LLM
contradice al motor, gana el motor.

## Documentación

Guías por módulo orientadas a uso externo:

- [`docs/conector.md`](docs/conector.md) — módulo de conexión a la
  BD del cliente: pool read-only, extracción de schema/tamaños/
  stats, cache local y modo offline (bundle JSON portable).
- [`docs/motor.md`](docs/motor.md) — motor determinístico: parser
  de EXPLAIN, los 19 detectores con sus reglas, recomendador de
  índices con filtro de selectividad, y cómo agregar un detector
  nuevo.
- [`docs/patterns/`](docs/patterns/) — catálogo de anti-patterns,
  un archivo `.md` por detector implementado.
- [`docs/decisiones.md`](docs/decisiones.md) — registro vivo de
  decisiones técnicas del equipo (stack, arquitectura, trade-offs).
- [`docs/briefs/`](docs/briefs/) — PDFs originales del proyecto
  (rúbrica, brief de negocio, briefs técnicos).

Notas internas dirigidas a agentes de Claude Code y al equipo viven
en cada `CLAUDE.md` por módulo (no en `/docs/`).

## Reglas técnicas

Las reglas inviolables que protegen la arquitectura del producto y
la nota del proyecto están en [`RULES.md`](RULES.md).

## Bitácora

El log cronológico del proyecto vive en
[`PROGRESS.md`](PROGRESS.md): qué se cerró cada día, qué decisiones
tomó el equipo, qué bloqueos hay activos.

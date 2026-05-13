# docs

Documentación de PgPilot orientada a personas **fuera del equipo de
desarrollo** (clientes evaluando el producto, integradores, futuros
mantenedores). Las notas internas dirigidas a agentes de Claude Code y
al equipo del proyecto viven en cada `CLAUDE.md` de su módulo.

## Índice

- [`conector.md`](conector.md) — guía de uso del módulo `/conector`
  (conexiones read-only, extracción de metadata, cache y modo offline).
- [`motor.md`](motor.md) — guía del motor determinístico (parser de
  EXPLAIN, los 19 detectores, recomendador de índices, cómo agregar
  un detector nuevo). Cruzado con `patterns/`.
- [`ia.md`](ia.md) — guía de la capa de integración con el LLM
  (sanitización, prompt con guardrails, validación Pydantic +
  cruzada, modo "LLM apagado" con plantillas, logs estructurados).
- [`patterns/`](patterns/) — catálogo de anti-patterns que PgPilot
  detecta, un archivo por detector implementado.
- [`decisiones.md`](decisiones.md) — registro vivo de decisiones
  técnicas del equipo (stack, arquitectura, trade-offs).
- [`briefs/`](briefs/) — PDFs originales del proyecto (rúbrica, brief
  de negocio, briefs técnicos).

Documentación de los módulos pendientes de publicar:
`/workload`, `/sandbox`, `/backend`, `/frontend`.
Mientras tanto, su API interna está descrita en el `CLAUDE.md`
correspondiente.

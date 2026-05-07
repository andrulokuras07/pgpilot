# PROGRESS — Bitácora del proyecto

Este archivo es el log cronológico del proyecto. Cada vez que un agente cierra una actividad del backlog, debe agregar una entrada aquí. Cada vez que el equipo toma una decisión técnica importante, debe registrarse aquí.

**Cómo se usa este archivo:**

- Las entradas más recientes van **arriba** (orden cronológico inverso)
- Cada día tiene su sección con fecha en formato `YYYY-MM-DD`
- Dentro de cada día hay dos subsecciones: "Avances" y "Decisiones" (si aplica)
- Cada avance lista: actividad cerrada, autor, archivos modificados, notas
- Las decisiones tienen autor, contexto, alternativas consideradas, qué se eligió y por qué

**Cómo lo usan los agentes de Claude Code:**

Antes de empezar a trabajar, leen las últimas 2-3 entradas de `PROGRESS.md` para conocer el estado actual del proyecto y detectar decisiones recientes que pueden afectar su trabajo.

**Recordatorio de regla R15 (en `RULES.md`):** ningún PR que cierra una actividad del backlog se mergea sin actualizar este archivo Y, si aplica, el `CLAUDE.md` del módulo afectado.

---

## Estado actual del proyecto

### Cobertura de detección
- **AppDB v1:** 0 / 20 queries detectadas (objetivo: ≥16)
- **Falsos positivos:** sin medir todavía (objetivo: <3)
- **AppDB v2:** sin probar (objetivo: ≥4 de 5 queries nuevas)

### Hitos
- ⬜ Hito 1 (kickoff y arquitectura) — fecha por confirmar
- ⬜ Hito 2 (demo parcial) — fecha por confirmar
- ⬜ Hito 3 (Demo Day) — 14 de mayo de 2026

### Asignación de roles
- **Conector e Ingesta:** [pendiente]
- **Motor Determinístico:** [pendiente]
- **Capa de IA + Validación:** [pendiente]
- **Workload + Sandbox:** [pendiente]
- **Producto y Negocio:** [pendiente]

### Actividades en curso
*(Esta sección la actualiza cada miembro al tomar/cerrar tareas. Una actividad nunca debe estar "in progress" más de 3 días sin moverse.)*

| Código | Actividad | Responsable | Estado | Notas |
|--------|-----------|-------------|--------|-------|
| — | — | — | — | — |

### Bloqueos activos
*(Cualquier impedimento que requiera ayuda del equipo o de fuera. Si no hay bloqueos, déjalo vacío.)*

- Ninguno reportado.

---

## Plantilla para nuevas entradas

Copia esta plantilla cuando agregues un día nuevo. Borra los placeholders.

```markdown
## YYYY-MM-DD

### Avances

#### [CODIGO_ACTIVIDAD] — Título corto
- **Autor:** Nombre
- **Archivos:** `archivo1.py`, `archivo2.py`
- **Notas:** Resumen de 1-2 líneas. Qué cambió, qué quedó pendiente, qué hay que vigilar.
- **Tests:** ✅ Verde | ⚠️ Pendiente | ❌ Falló (con razón)

### Decisiones

#### Título de la decisión
- **Autor:** Nombre (o "Equipo" si fue en standup)
- **Contexto:** Qué problema se estaba resolviendo
- **Alternativas consideradas:** A, B, C
- **Decisión:** Se eligió A
- **Razón:** Por qué A le ganó a B y C
- **Trade-offs:** Qué se sacrifica con esta decisión

### Bloqueos detectados

- Bloqueo X afectando a Persona Y. Acción para destrabar: ...
```

---

## Bitácora

*(Las entradas reales del proyecto van debajo de esta línea. Las más recientes arriba.)*

---

## YYYY-MM-DD — Día 1 del proyecto

### Avances

*(Aún no hay avances registrados. La primera entrada real reemplaza esta línea.)*

### Decisiones

#### Stack técnico inicial
- **Autor:** Equipo (kickoff)
- **Contexto:** Definir tecnologías base antes de empezar a programar
- **Decisión:** Python + FastAPI + psycopg backend, React + Vite + Monaco frontend, Anthropic Claude LLM, sqlglot parser, Postgres 16 base
- **Razón:** Python tiene mejor soporte para parsing SQL y validación con Pydantic. FastAPI es rápido de levantar. Monaco es estándar para editores SQL en producción.
- **Trade-offs:** Stack mixto (Python + JS) implica dos toolchains, pero ningún stack único cubre bien backend de análisis + frontend tipo IDE.

#### Roles del equipo
- **Autor:** Equipo
- **Contexto:** Reparto de los 5 roles del brief
- **Decisión:** Por confirmar tras revisión del backlog
- **Razón:** —

---

## Histórico de hitos

### Hito 1 — [Por completar]
- **Fecha real:** —
- **Qué se entregó:** —
- **Feedback del profesor:** —
- **Acciones derivadas:** —

### Hito 2 — [Por completar]
- **Fecha real:** —
- **Qué se entregó:** —
- **Feedback del profesor:** —
- **Acciones derivadas:** —

### Hito 3 (Demo Day) — [Por completar]
- **Fecha real:** —
- **Cobertura final v1:** —
- **Cobertura final v2:** —
- **Falsos positivos:** —
- **Resultado del Q&A Battle:** —
- **Nota recibida:** —

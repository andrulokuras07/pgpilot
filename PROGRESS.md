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

**Recordatorio de regla R15 (en `RULES.md`):** antes de hacer `git push` de una rama que cierra una actividad del backlog, hay que agregar entrada en este archivo Y, si aplica, actualizar el `CLAUDE.md` del módulo afectado. Si el módulo no tiene `CLAUDE.md` todavía, hay que crearlo (ver convención en `CLAUDE.md` raíz).

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
*El equipo decidió no asignar roles fijos. Cualquier miembro puede tomar cualquier actividad del backlog. Ver decisión del 2026-05-08 en este archivo.*

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

## 2026-05-08

### Decisiones

#### Modificación del backlog: eliminación de A4 y A7, reformulación de A6
- **Autor:** Andrés Angulo
- **Contexto:** revisión inicial del backlog antes de arrancar Fase 0. Se identificaron tres actividades que no encajan con la forma de trabajo decidida por el equipo.
- **Cambios:**
  - **A4 (tablero de tareas):** eliminada. El equipo se coordina con el backlog en Markdown, `PROGRESS.md` y GitHub Issues. No se usará tablero externo.
  - **A6 (decisiones del equipo):** reformulada. Pasa de Google Doc/Notion a `docs/decisiones.md` dentro del repo. Razón: tener todo versionado en Git y evitar herramientas paralelas.
  - **A7 (asignar roles):** eliminada. El equipo trabajará sin roles fijos; cualquiera puede tomar cualquier actividad disponible.

## 2026-05-06 — Día 1 del proyecto

### Avances

#### A1 — Crear repositorio Git
- **Autor:** Andrés Angulo
- **Archivos:** `.gitignore`, `README.md`
- **Notas:** Repo `pgpilot` creado en GitHub. Los 4 compañeros agregados como colaboradores. Protección de rama `main` por ahora NO activada (ver decisión abajo).
- **Tests:** N/A

#### A2 — Definir estructura de carpetas
- **Autor:** Andrés Angulo
- **Archivos:** carpetas `/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`, `/backend`, `/frontend`, `/docs`, `/docs/patterns`, `/docs/briefs`, `/business`, `/tests`, `/scripts` con README placeholder en cada una.
- **Notas:** Estructura alineada con la documentada en `CLAUDE.md`. Agregada carpeta `/backend` para FastAPI y `/docs/briefs` para los PDFs originales del proyecto.
- **Tests:** N/A

#### Setup inicial — Archivos de contexto base
- **Autor:** Andrés Angulo
- **Archivos:** `CLAUDE.md`, `RULES.md`, `PROGRESS.md` en raíz
- **Notas:** Tres archivos de contexto agregados antes de que el equipo arranque cualquier código, para que Claude Code de cada miembro tenga las reglas y arquitectura desde la primera sesión.

### Decisiones

#### Documentación obligatoria al hacer push, no al hacer PR
- **Autor:** Andrés Angulo
- **Contexto:** La regla R15 original exigía actualizar `PROGRESS.md` y los `CLAUDE.md` de módulos antes de mergear el PR. Esto solo funciona si la rama `main` está protegida y bloquea push directos. Como el equipo no domina Git todavía, activar la protección agregaría fricción de aprendizaje.
- **Alternativas consideradas:** (a) activar protección de rama y mantener regla atada al PR, (b) posponer protección y atar la regla al `git push` en lugar del PR
- **Decisión:** Opción b — la regla se cumple antes de cada push. 
- **Razón:** Permite que el equipo aprenda el flujo de Git con menos fricción mientras mantiene viva la regla de documentación obligatoria. La regla deja de depender de la herramienta y pasa a depender de disciplina del equipo, lo cual es viable porque cada agente Claude Code va a leer `RULES.md` antes de hacer push.
- **Trade-offs:** Si alguien hace push directo a `main` por accidente, no hay red de seguridad técnica. Mitigación: comunicación clara en el grupo de WhatsApp y recordatorio en standups.

### Bloqueos detectados

- Ninguno.

## 2026-05-08

### Avances

#### A6 — Documento de decisiones del equipo
- **Autor:** Andrés Angulo
- **Archivos:** `docs/decisiones.md`
- **Notas:** Archivo creado con las 4 secciones inicializadas (Stack, Arquitectura, Trade-offs, Bloqueos). Contenido se llena progresivamente; sección Stack se completa en A8.
- **Tests:** N/A

#### A8 — Stack técnico documentado
- **Autor:** Andrés Angulo
- **Archivos:** `docs/decisiones.md`
- **Notas:** Sección "Stack elegido" llenada con justificación de cada decisión (Python+FastAPI, psycopg v3, sqlglot, Pydantic, React+Vite+Monaco+Tailwind, Claude API, Postgres 16, Docker Compose, pytest, black+isort). Cubre Criterio 1.2 de la rúbrica.
- **Tests:** N/A

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

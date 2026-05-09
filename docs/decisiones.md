# Decisiones del equipo — PgPilot

Bitácora viva de decisiones técnicas y de producto. Se actualiza durante todo el proyecto. Alimenta después el documento de arquitectura (F2) y el documento de negocio (F15).

**Cómo se usa:**
- Cada sección crece con el tiempo. No se borra contenido, solo se añade.
- Al cerrar una decisión, agregar entrada con fecha y autor.
- Si una decisión se revierte después, no borrar la original: agregar nueva entrada explicando el cambio.

---

## 1. Stack elegido

*Decisiones sobre lenguajes, frameworks, librerías y herramientas. Cada elección con justificación de 1-2 líneas (la rúbrica lo evalúa en Criterio 1.2).*

*(Pendiente — se llena en A8.)*

---

## 2. Decisiones de arquitectura

*Decisiones de diseño del sistema: separación de responsabilidades entre módulos, contratos entre componentes, flujos de datos, patrones aplicados.*

*(Vacío al inicio. Se llena durante Fases 1-4.)*

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
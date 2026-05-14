# Módulo `business` — Documentación de negocio de PgPilot

Documentos de discovery, validación de mercado y preparación para el Demo Day. No contiene código — solo documentación de negocio.

**Lo que NO hace:** nada técnico. El código vive en los otros módulos.

---

## Estado actual

- ✅ F3 — Investigación competitiva (`competencia.md` + `.docx`)
- ✅ F4 — Lista de 5 candidatos a entrevistar (`lista-entrevistados.md`)
- ✅ F5 — Guion de entrevista (`guion-entrevistas.md`)
- ✅ F6 — Entrevista 1: Carlos Orellán, DBA (`entrevista-1.md`)
- ✅ F7 — Entrevista 2: Jos Lugo, Ingeniero de software (`entrevista-2.md`)
- ✅ F8 — Entrevista 3: Raúl de la Breña, Tech Lead Backend (`entrevista-3.md`)
- ✅ F9 — Definición de problema con datos (`problema.md`)
- ✅ F10 — User persona detallado (`persona.md`)
- ✅ F11 — Modelo de pricing (`pricing.md` + `.docx`)
- ✅ F12 — TAM/SAM/SOM (`mercado.md` + `.docx`)
- ✅ F13 — Plan Go-to-Market (`gtm.md` + `.docx`)
- ✅ F14 — Diferenciador defendible (`diferenciador.md` + `.docx`)
- 🟡 F15 — Documento de negocio consolidado (`negocio.md` integrado al 95% con F3/F6/F7/F8/F9/F10/F11/F12/F13/F14. §2.3 con frecuencia/severidad cuantificadas de los 3 entrevistados + Andrés (gradiente 1 h/mes → 20 h/mes); §3.1 con la tabla de las 3 entrevistas; §3.3 con 9 insights consolidados (decisor matizado, dolor disociado del tamaño puro, monitor proactivo como oportunidad nueva) + hipótesis resueltas + cambios al producto/pricing/GTM derivados de F6+F7+F8; §6.3 actualizada con la validación explícita de Raúl al rango $200/mes. **`negocio.docx` queda desincronizado tras esta actualización** — regenerar antes de la entrega final (ver convención .md/.docx). §10 sigue con `[PENDIENTE: COMPLETAR DATOS DEL EQUIPO]` para nombres y reparto técnico — único hueco para llegar al 100%.)

---

## Estructura interna

```
business/
├── CLAUDE.md                # este archivo
├── README.md                # placeholder original
├── competencia.md / .docx   # F3 — investigación competitiva
├── lista-entrevistados.md   # F4 — 5 candidatos con criterios de selección
├── guion-entrevistas.md     # F5 — 9 preguntas para entrevistas de discovery
├── entrevista-1.md          # F6 — Entrevista Carlos Orellán (DBA)
├── entrevista-2.md          # F7 — Entrevista Jos Lugo (Ing. software)
├── entrevista-3.md          # F8 — Entrevista Raúl de la Breña (Tech Lead)
├── problema.md              # F9 — Definición del problema con datos
├── persona.md               # F10 — User persona detallado
├── pricing.md / .docx       # F11 — modelo de pricing (4 tiers)
├── mercado.md / .docx       # F12 — TAM/SAM/SOM con metodología y fuentes
├── gtm.md / .docx           # F13 — plan go-to-market (primeros 10 clientes)
├── diferenciador.md / .docx # F14 — diferenciador defendible
└── negocio.md / .docx       # F15 — documento de negocio consolidado (Plantilla 3 de la entrega oficial; .docx llena la plantilla del profesor preservando headings y estilos)
```

---

## Convenciones

### Documentos con entregable formal
Los documentos que se entregan al evaluador o se citan en pitches (F3, F11, F12, F13, F14, F15) viven como pareja `.md` + `.docx`:

- **`.md`** es la fuente versionada en el repo, fácil de revisar en GitHub y editar.
- **`.docx`** es el entregable de presentación formal (Word con tablas formateadas, encabezados, colores).
- Ambos contienen la misma información. Si se actualiza el `.md`, hay que reflejar manualmente los cambios en el `.docx` para que no diverjan. Cada archivo `.md` lleva una "Nota de mantenimiento" al final recordándolo.
- Los `.docx` se generan localmente con un script temporal (python-docx) que se borra antes del commit; el equipo decidió no versionar generadores de docx para mantener el repo limpio (ver decisión del 2026-05-13 en `PROGRESS.md`).

### Documentos de proceso interno
Documentos de proceso (F4 lista de candidatos, F5 guion de entrevistas, F6-F8 entrevistas, F9 problema, F10 persona) viven solo como `.md` — no necesitan entregable Word formal.

---

## Cómo extender

### Documentar una entrevista (F6-F8)
Crear `business/entrevista-N.md` con: nombre y rol del entrevistado, fecha, respuestas resumidas por pregunta, insights principales. Solo `.md`, no requiere `.docx`.

### Agregar documentación de negocio nueva
1. Crear el archivo `.md` correspondiente en esta carpeta.
2. Si es entregable formal, generar también el `.docx` con un script temporal local (basado en python-docx, mismo patrón que F3/F11/F12/F13/F14/F15). Borrar el script antes del commit.
3. Actualizar la sección "Estado actual" de este archivo (`business/CLAUDE.md`) marcando el ticket como ✅.
4. Actualizar la sección "Estructura interna" si el nombre del archivo es nuevo.
5. Agregar entrada en `PROGRESS.md` (regla R15).

### Actualizar contenido existente
Si se modifica un `.md`:
- Reflejar el cambio en el `.docx` correspondiente (regenerar o editar manualmente).
- Si el cambio es material (precio, cifra, conclusión), agregar entrada en `PROGRESS.md` explicando qué cambió y por qué.

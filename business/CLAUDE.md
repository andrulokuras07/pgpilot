# Módulo `business` — Documentación de negocio de PgPilot

Documentos de discovery, validación de mercado y preparación para el Demo Day. No contiene código — solo documentación de negocio.

**Lo que NO hace:** nada técnico. El código vive en los otros módulos.

---

## Estado actual

- ✅ F4 — Lista de 5 candidatos a entrevistar
- ✅ F5 — Guion de entrevista (9 preguntas)
- ⬜ F3 — Investigación competitiva
- ⬜ F6-F8 — Entrevistas ejecutadas y documentadas
- ⬜ F9-F14 — Definición de problema, persona, pricing, TAM/SAM/SOM, go-to-market, diferenciador
- ⬜ F15 — Documento de negocio consolidado

---

## Estructura interna

```
business/
├── CLAUDE.md                # este archivo
├── README.md                # placeholder original
├── guion-entrevistas.md     # F5 — 9 preguntas para entrevistas de discovery
└── lista-entrevistados.md   # F4 — 5 candidatos con criterios de selección
```

---

## Cómo extender

### Documentar una entrevista (F6-F8)
Crear `business/entrevista-N.md` con: nombre y rol del entrevistado, fecha, respuestas resumidas por pregunta, insights principales.

### Agregar documentación de negocio
Crear el archivo correspondiente en esta carpeta y actualizar el estado en este CLAUDE.md.

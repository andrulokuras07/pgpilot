# Módulo `frontend` — UI de PgPilot

SPA en React + Vite con un editor Monaco para escribir SQL y un panel donde se muestra la respuesta del backend. Tema oscuro tipo VS Code.

**Lo que NO hace:** lógica de análisis, parsing, ni decisiones sobre detecciones. Solo manda el SQL al backend y renderiza lo que recibe.

---

## Estado actual

- ✅ B12 — Vite + React + Monaco con SQL highlight, tema oscuro, botón "Analizar"
- ✅ B14 — el botón hace `POST /analyze` al backend y muestra el JSON crudo en el panel lateral
- ✅ C10 — tarjetas por detección y recomendación (sustituye al JSON crudo)
- ✅ C11 — comparativo before/after del plan dentro de la tarjeta de recomendación
- ✅ E7 — comparativo enriquecido: titular de transición de tipo de nodo,
  filas estimadas por panel, resumen ejecutivo automático

---

## Cómo correrlo en desarrollo

```bash
cd frontend
npm install   # primera vez
npm run dev
```

El editor queda en `http://localhost:5173`. Para que el botón "Analizar" funcione, también hay que tener el backend corriendo en `localhost:8000` (ver `backend/CLAUDE.md`).

---

## Estructura de archivos

```
frontend/
├── package.json          # deps: react, react-dom, @monaco-editor/react; dev: vite, @vitejs/plugin-react
├── vite.config.js        # plugin react, port 5173 (strictPort)
├── index.html            # mount point #root
├── .gitignore            # node_modules, dist, .vite
└── src/
    ├── main.jsx              # createRoot + StrictMode
    ├── App.jsx               # editor Monaco + botón Analizar + panel de tarjetas
    ├── DetectionCard.jsx     # C10 — tarjeta por entrada de `detections[]`
    ├── RecommendationCard.jsx# C10 — tarjeta por entrada de `recommendations[]`
    ├── PlanComparison.jsx    # C11 + E7 — comparativo before/after enriquecido
    ├── index.css             # reset y color-scheme dark
    ├── App.css               # layout y tema VS Code
    └── Card.css              # estilos de tarjetas + comparativo (C10/C11/E7)
```

---

## Convenciones

- **Componentes funcionales con hooks únicamente** (R12). Nada de `class Component`.
- **Estilos:** CSS plano con tema VS Code hardcoded por ahora. Tailwind se agregará cuando un componente lo justifique (probablemente C10 al introducir tarjetas de detección).
- **Backend URL:** hardcoded en `App.jsx` como `http://localhost:8000/analyze`. Cuando se necesite distinguir dev/prod, mover a una variable Vite (`VITE_BACKEND_URL`).
- **Lenguaje del UI:** español. Mensajes de error en español también.

---

## Cómo extender

### Agregar un componente nuevo

1. Archivo `src/<NombreComponente>.jsx` con un componente funcional y sus propios hooks de estado.
2. Si tiene estilos propios, archivo hermano `<NombreComponente>.css` o un `<NombreComponente>.module.css` (CSS modules) si el ámbito lo justifica.
3. Importarlo en `App.jsx` y componerlo en el layout existente.

### Conectar un endpoint nuevo del backend

1. Definir la URL como constante arriba del componente.
2. Usar `fetch` con `Content-Type: application/json` (mismo patrón que `analizar()` en `App.jsx`).
3. Manejar tres estados: `cargando`, `error`, `respuesta`. Mostrar mensajes en español.

### Cambiar el tema o el layout del editor

`App.jsx` pasa props a `<Editor>`:

- `theme="vs-dark"` — tema VS Code oscuro nativo de Monaco.
- `defaultLanguage="sql"` — habilita syntax highlight de SQL.
- `options.minimap.enabled = false` — sin minimapa para no comer espacio.
- `options.automaticLayout = true` — el editor reacciona al resize del contenedor.

---

## Cómo se mapea el payload del backend a la UI (C10/C11)

El payload de `/analyze` (ver `backend/CLAUDE.md`) se proyecta así:

- `detections[]` → una `DetectionCard` por entrada. Muestra
  título humanizado, confianza del motor, y la lista de
  `evidence.matches[]` con tablas/columnas afectadas.
- `recommendations[]` → una `RecommendationCard` por entrada.
  Renderea:
  - **C10:** título, prosa de `explanation.text`, badges (origen
    LLM/plantilla, `sandbox_verdict`), bloques SQL copiables para
    `create_index_sql` y `explanation.suggested_rewrite` si existe,
    y un `<details>` con justificación / impacto / selectividad.
  - **C11 + E7:** componente `PlanComparison` debajo de la prosa.
    Consume `recommendation.sandbox_plan_comparison`
    (`{node_type_before, node_type_after, cost_before, cost_after,
    plan_rows_before, plan_rows_after}`) y
    `recommendation.sandbox_verdict`. Renderea, en este orden:
    1. **Titular de transición** — `El planner pasa de <Seq Scan> a
       <Index Scan>` (en verde si `node_type_before === "Seq Scan"` y
       `node_type_after` cambió a algo distinto = "ahora usa el índice").
       Se omite si los tipos son iguales o falta alguno.
    2. **Dos paneles "Antes" / "Después"** con tipo de nodo, `cost` y
       `filas est.` (de `plan_rows_*`). El panel "Después" lleva borde
       verde cuando el nodo mejoró.
    3. **Resumen ejecutivo automático** (`ExecutiveSummary`): si
       `cost_before` y `cost_after` son ambos > 0, "redujo el costo
       estimado de X a Y — Zx mejora estimada en sandbox (…)"; si no
       hay factor numérico fiable pero el nodo mejoró, la frase
       cualitativa "el planner deja el escaneo secuencial y pasa a usar
       el índice"; si ninguna aplica, no se muestra resumen.
    Si el comparativo viene `null` (sandbox no disponible, recomendación
    tipo ANALYZE), se renderea un mensaje neutral en lugar del panel.

**Honestidad de C11 + E7:** los costos del sandbox vienen de tablas
vacías por R6, así que la magnitud absoluta no representa producción.
La etiqueta de "Xx mejora" se acompaña del disclaimer "estimado en
sandbox (los costos son sobre tablas vacías — la magnitud real depende
de stats de producción)". El cambio cualitativo (Seq Scan → Index
Scan) sí es confiable y se resalta visualmente con borde verde. **No se
muestran tiempos:** el EXPLAIN del sandbox corre sin `ANALYZE`, así que
no hay tiempo real que reportar — el dato honesto es `plan_rows`
(filas estimadas), que de paso enseña que el índice cambia *cómo* se
llega a las filas, no *cuántas*.

## Lo que aún no hay

- Sin tests automatizados (no se justifica testing de UI mientras solo es un editor + un fetch). Cuando aparezcan reglas de negocio en el frontend (filtrado, agrupación de detecciones), se introducirá Vitest.
- Sin Tailwind. Decisión registrada en `PROGRESS.md` 2026-05-10.
- Sin manejo de configuración (env vars). El backend está hardcoded.

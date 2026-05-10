# Módulo `frontend` — UI de PgPilot

SPA en React + Vite con un editor Monaco para escribir SQL y un panel donde se muestra la respuesta del backend. Tema oscuro tipo VS Code.

**Lo que NO hace:** lógica de análisis, parsing, ni decisiones sobre detecciones. Solo manda el SQL al backend y renderiza lo que recibe.

---

## Estado actual

- ✅ B12 — Vite + React + Monaco con SQL highlight, tema oscuro, botón "Analizar"
- ✅ B14 — el botón hace `POST /analyze` al backend y muestra el JSON crudo en el panel lateral
- ⬜ C10 — tarjetas por detección en lugar de JSON crudo
- ⬜ C11 — comparativo before/after del plan

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
    ├── main.jsx          # createRoot + StrictMode
    ├── App.jsx           # editor Monaco + botón Analizar + panel de respuesta
    ├── index.css         # reset y color-scheme dark
    └── App.css           # layout y tema VS Code
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

## Lo que aún no hay

- Sin tests automatizados (no se justifica testing de UI mientras solo es un editor + un fetch). Cuando aparezcan reglas de negocio en el frontend (filtrado, agrupación de detecciones), se introducirá Vitest.
- Sin Tailwind. Decisión registrada en `PROGRESS.md` 2026-05-10.
- Sin manejo de configuración (env vars). El backend está hardcoded.

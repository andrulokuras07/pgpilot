import { useState } from "react";
import Editor from "@monaco-editor/react";

import DetectionCard from "./DetectionCard.jsx";
import RecommendationCard from "./RecommendationCard.jsx";
import "./App.css";
import "./Card.css";

const QUERY_INICIAL = `SELECT u.name, count(*)
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE o.created_at >= '2026-01-01'
GROUP BY u.name;`;

const BACKEND_URL = "http://localhost:8000/analyze";

function App() {
  const [query, setQuery] = useState(QUERY_INICIAL);
  const [respuesta, setRespuesta] = useState(null);
  const [error, setError] = useState(null);
  const [cargando, setCargando] = useState(false);

  async function analizar() {
    setCargando(true);
    setError(null);
    setRespuesta(null);
    try {
      const r = await fetch(BACKEND_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!r.ok) {
        throw new Error(`HTTP ${r.status}`);
      }
      const data = await r.json();
      setRespuesta(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1 className="title">PgPilot</h1>
        <span className="subtitle">Analizador de queries Postgres</span>
      </header>
      <main className="main">
        <section className="pane editor-pane">
          <div className="pane-header">
            <span className="pane-label">Query</span>
            <button
              type="button"
              className="boton-analizar"
              onClick={analizar}
              disabled={cargando}
            >
              {cargando ? "Analizando…" : "Analizar"}
            </button>
          </div>
          <div className="editor-container">
            <Editor
              height="100%"
              defaultLanguage="sql"
              theme="vs-dark"
              value={query}
              onChange={(v) => setQuery(v ?? "")}
              options={{
                fontSize: 14,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
              }}
            />
          </div>
        </section>
        <aside className="pane result-pane">
          <div className="pane-header">
            <span className="pane-label">Análisis</span>
          </div>
          <div className="result-body">
            <Resultado
              respuesta={respuesta}
              error={error}
              cargando={cargando}
            />
          </div>
        </aside>
      </main>
    </div>
  );
}

function Resultado({ respuesta, error, cargando }) {
  if (error) {
    return (
      <div className="cards-error">
        Error: {error}
        {"\n\n"}¿Está corriendo el backend en localhost:8000?
      </div>
    );
  }
  if (cargando) {
    return (
      <div className="cards-empty">Analizando la query, un momento…</div>
    );
  }
  if (!respuesta) {
    return (
      <div className="cards-empty">
        Aún no se ha analizado nada.
        {"\n"}Escribe SQL y haz clic en «Analizar».
      </div>
    );
  }
  const detections = respuesta.detections ?? [];
  const recommendations = respuesta.recommendations ?? [];
  if (detections.length === 0 && recommendations.length === 0) {
    return (
      <div className="cards-success">
        Sin anti-patterns detectados. PgPilot revisó el plan y no encontró
        problemas en los detectores activos.
      </div>
    );
  }
  return (
    <div className="cards-list">
      {detections.map((d, i) => (
        <DetectionCard key={`det-${i}`} detection={d} />
      ))}
      {recommendations.map((r, i) => (
        <RecommendationCard key={`rec-${i}`} recommendation={r} />
      ))}
    </div>
  );
}

export default App;

import { useState } from "react";
import Editor from "@monaco-editor/react";

import DetectionCard from "./DetectionCard.jsx";
import RecommendationCard from "./RecommendationCard.jsx";
import WorkloadTab from "./WorkloadTab.jsx";
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
  const [activeTab, setActiveTab] = useState("analyze");

  async function analizar(queryOverride) {
    const sql = queryOverride || query;
    if (queryOverride) setQuery(sql);
    setCargando(true);
    setError(null);
    setRespuesta(null);
    try {
      const r = await fetch(BACKEND_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: sql }),
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

  function handleWorkloadSelect(selectedQuery) {
    setQuery(selectedQuery);
    setActiveTab("analyze");
    analizar(selectedQuery);
  }

  return (
    <div className="app">
      <header className="header">
        <h1 className="title">PgPilot</h1>
        <span className="subtitle">Analizador de queries Postgres</span>
        <nav className="tab-nav">
          <button
            type="button"
            className={`tab-btn ${activeTab === "analyze" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("analyze")}
          >
            Analizar Query
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === "workload" ? "tab-active" : ""}`}
            onClick={() => setActiveTab("workload")}
          >
            Workload Analysis
          </button>
        </nav>
      </header>

      {activeTab === "analyze" && (
        <main className="main">
          <section className="pane editor-pane">
            <div className="pane-header">
              <span className="pane-label">Query</span>
              <button
                type="button"
                className="boton-analizar"
                onClick={() => analizar()}
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
      )}

      {activeTab === "workload" && (
        <main className="main workload-main">
          <section className="pane workload-pane">
            <WorkloadTab onSelectQuery={handleWorkloadSelect} />
          </section>
        </main>
      )}
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
  const errores = respuesta.errors ?? [];
  const parcial = Boolean(respuesta.partial);
  const vacio = detections.length === 0 && recommendations.length === 0;

  // Análisis completo y sin hallazgos → mensaje verde de "todo limpio".
  if (vacio && !parcial) {
    return (
      <div className="cards-success">
        Sin anti-patterns detectados. PgPilot revisó el plan y no encontró
        problemas en los detectores activos.
      </div>
    );
  }
  return (
    <div className="cards-list">
      {parcial && <BannerParcial errores={errores} />}
      {vacio && (
        <div className="cards-empty">
          No se completó el análisis (ver el aviso de arriba). No hay
          detecciones que mostrar.
        </div>
      )}
      {detections.map((d, i) => (
        <DetectionCard key={`det-${i}`} detection={d} />
      ))}
      {recommendations.map((r, i) => (
        <RecommendationCard key={`rec-${i}`} recommendation={r} />
      ))}
    </div>
  );
}

// E8: el backend devuelve resultados parciales con un flag de error
// cuando alguna etapa del pipeline falla. Mostramos un aviso arriba de
// las tarjetas; lo que sí se calculó (detecciones / recomendaciones
// determinísticas) se sigue renderizando debajo.
function BannerParcial({ errores }) {
  return (
    <div className="cards-warning">
      <div className="cards-warning-title">Análisis parcial</div>
      {errores.length > 0 ? (
        <ul>
          {errores.map((e, i) => (
            <li key={`err-${i}`}>{e.message ?? "Una etapa del análisis falló."}</li>
          ))}
        </ul>
      ) : (
        <span>
          Alguna etapa del análisis falló; los resultados pueden estar
          incompletos.
        </span>
      )}
    </div>
  );
}

export default App;

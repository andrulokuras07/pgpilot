import { useState } from "react";
import "./WorkloadTab.css";

const WORKLOAD_URL = "http://localhost:8000/workload";

function WorkloadTab({ onSelectQuery }) {
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleFileUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    setLoading(true);
    setError(null);
    setResults(null);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const r = await fetch(WORKLOAD_URL, {
        method: "POST",
        body: formData,
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${r.status}`);
      }
      const data = await r.json();
      setResults(data.top || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function formatTime(ms) {
    if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
    return `${ms.toFixed(2)}ms`;
  }

  return (
    <div className="workload-tab">
      <div className="workload-upload">
        <label className="workload-upload-label">
          <input
            type="file"
            accept=".csv,.json"
            onChange={handleFileUpload}
            className="workload-file-input"
          />
          <span className="workload-upload-btn">
            {loading ? "Procesando…" : "Subir pg_stat_statements"}
          </span>
        </label>
        <span className="workload-upload-hint">CSV o JSON</span>
      </div>

      {error && (
        <div className="workload-error">Error: {error}</div>
      )}

      {results && results.length === 0 && (
        <div className="workload-empty">
          No se encontraron queries en el archivo.
        </div>
      )}

      {results && results.length > 0 && (
        <table className="workload-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Score</th>
              <th>Tiempo total</th>
              <th>Tiempo promedio</th>
              <th>Llamadas</th>
              <th>Query</th>
            </tr>
          </thead>
          <tbody>
            {results.map((entry) => (
              <tr
                key={entry.rank}
                className="workload-row"
                onClick={() => onSelectQuery(entry.query)}
                title="Clic para analizar esta query"
              >
                <td className="workload-rank">{entry.rank}</td>
                <td className="workload-score">
                  <div className="score-bar-container">
                    <div
                      className="score-bar"
                      style={{ width: `${entry.score * 100}%` }}
                    />
                    <span className="score-value">
                      {(entry.score * 100).toFixed(0)}%
                    </span>
                  </div>
                </td>
                <td className="workload-time">{formatTime(entry.total_exec_time)}</td>
                <td className="workload-time">{formatTime(entry.mean_exec_time)}</td>
                <td className="workload-calls">{entry.calls.toLocaleString()}</td>
                <td className="workload-query">
                  {entry.query.length > 120
                    ? entry.query.slice(0, 120) + "…"
                    : entry.query}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default WorkloadTab;

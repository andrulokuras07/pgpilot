/**
 * Tarjeta de detección — C10. Muestra el tipo de anti-pattern detectado,
 * el nivel de confianza, y la lista de tablas/columnas afectadas
 * (`evidence.matches[]` que produce `motor.detect_seq_scan_on_large_table`).
 *
 * Es informativa y agnóstica de recomendaciones: una sola detección puede
 * generar 0..N recomendaciones (manejadas por `RecommendationCard`).
 */
import "./Card.css";

const TITULOS_POR_TIPO = {
  seq_scan_on_large_table: "Seq Scan sobre tabla grande con índice ignorado",
};

function tituloHumano(tipo) {
  return TITULOS_POR_TIPO[tipo] ?? tipo;
}

function porcentajeConfianza(valor) {
  if (typeof valor !== "number") return "—";
  return `${Math.round(valor * 100)}%`;
}

function DetectionCard({ detection }) {
  const matches = detection.evidence?.matches ?? [];
  return (
    <article className="card card-detection">
      <header className="card-header">
        <span className="card-tag tag-detection">Detección</span>
        <h2 className="card-title">{tituloHumano(detection.type)}</h2>
        <span className="card-confidence" title="Confianza del motor determinístico">
          confianza {porcentajeConfianza(detection.confidence)}
        </span>
      </header>
      {matches.length > 0 && (
        <div className="card-body">
          <p className="card-subtle">Tablas/columnas afectadas:</p>
          <ul className="match-list">
            {matches.map((m, i) => (
              <li key={i} className="match-item">
                <code>{m.table}</code>
                {m.column ? (
                  <>
                    <span className="match-sep">·</span>
                    <code>{m.column}</code>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

export default DetectionCard;

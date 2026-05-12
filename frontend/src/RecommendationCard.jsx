/**
 * Tarjeta de recomendación — C10. Una tarjeta por cada elemento de
 * `recommendations[]` del payload del backend. Muestra título, prosa,
 * insignias (origen LLM vs plantilla, validación de sandbox), bloque
 * SQL con botón "copiar", y debajo el comparativo before/after de C11.
 *
 * Decisión: el SQL se muestra siempre, incluso cuando `kind="analyze"`
 * (en ese caso `create_index_sql` trae `ANALYZE <tabla>;`). El usuario
 * lo copia y lo ejecuta en su BD.
 */
import { useState } from "react";

import PlanComparison from "./PlanComparison.jsx";
import "./Card.css";

function porcentajeConfianza(valor) {
  if (typeof valor !== "number") return "—";
  return `${Math.round(valor * 100)}%`;
}

function tituloRecomendacion(rec) {
  if (rec.kind === "analyze") {
    return `Ejecutar ANALYZE sobre ${rec.table}`;
  }
  return `Crear índice ${rec.index_method} sobre ${rec.table} (${rec.column})`;
}

function BotonCopiar({ texto }) {
  const [copiado, setCopiado] = useState(false);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1500);
    } catch {
      // clipboard puede fallar en http (no https) o sin foco — fallback silencioso.
      setCopiado(false);
    }
  }

  return (
    <button
      type="button"
      className="boton-copiar"
      onClick={copiar}
      disabled={!texto}
    >
      {copiado ? "✓ Copiado" : "Copiar SQL"}
    </button>
  );
}

function VerdictBadge({ verdict }) {
  if (!verdict) {
    return <span className="badge badge-neutral">sandbox no disponible</span>;
  }
  return (
    <span className={`badge badge-${verdict}`}>
      {verdict === "validated" && "validado en sandbox"}
      {verdict === "discarded" && "descartado por sandbox"}
      {verdict === "skipped_no_sandbox_signal" && "sin señal de sandbox"}
    </span>
  );
}

function SourceBadge({ source }) {
  if (source === "llm") {
    return <span className="badge badge-llm">explicación generada por IA</span>;
  }
  return (
    <span className="badge badge-template">explicación sin IA (plantilla)</span>
  );
}

function RecommendationCard({ recommendation }) {
  const rec = recommendation;
  const explanation = rec.explanation ?? {};

  return (
    <article className="card card-recommendation">
      <header className="card-header">
        <span className="card-tag tag-recommendation">Recomendación</span>
        <h2 className="card-title">{tituloRecomendacion(rec)}</h2>
        <span className="card-confidence" title="Confianza de la explicación">
          confianza {porcentajeConfianza(explanation.confidence)}
        </span>
      </header>

      <div className="card-badges">
        <SourceBadge source={explanation.source} />
        <VerdictBadge verdict={rec.sandbox_verdict} />
      </div>

      {explanation.text ? (
        <p className="card-body card-explanation">{explanation.text}</p>
      ) : null}

      {rec.justification ? (
        <details className="card-details">
          <summary>Detalles del motor</summary>
          <p className="card-subtle">
            <strong>Justificación:</strong> {rec.justification}
          </p>
          {rec.expected_impact && (
            <p className="card-subtle">
              <strong>Impacto esperado:</strong> {rec.expected_impact}
            </p>
          )}
          {typeof rec.selectivity === "number" && (
            <p className="card-subtle">
              <strong>Selectividad estimada:</strong>{" "}
              {rec.selectivity.toExponential(2)}
            </p>
          )}
        </details>
      ) : null}

      {explanation.suggested_rewrite ? (
        <div className="sql-block">
          <div className="sql-block-header">
            <span className="card-subtle">Reescritura sugerida</span>
            <BotonCopiar texto={explanation.suggested_rewrite} />
          </div>
          <pre className="sql-code">{explanation.suggested_rewrite}</pre>
        </div>
      ) : null}

      {rec.create_index_sql ? (
        <div className="sql-block">
          <div className="sql-block-header">
            <span className="card-subtle">SQL para aplicar</span>
            <BotonCopiar texto={rec.create_index_sql} />
          </div>
          <pre className="sql-code">{rec.create_index_sql}</pre>
        </div>
      ) : null}

      <PlanComparison
        comparison={rec.sandbox_plan_comparison}
        verdict={rec.sandbox_verdict}
      />

      {rec.sandbox_reason ? (
        <p className="card-subtle card-sandbox-reason">
          <strong>Veredicto del sandbox:</strong> {rec.sandbox_reason}
        </p>
      ) : null}
    </article>
  );
}

export default RecommendationCard;

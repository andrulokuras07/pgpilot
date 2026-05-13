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
  if (rec.kind === "finding") {
    const nombre = rec.code ? `[${rec.code}]` : "";
    return `Hallazgo ${nombre} en ${rec.table || "la query"}`;
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

// E9: las 4 validaciones R3 que el backend ya calculó por recomendación.
// Orden fijo para que la lectura visual sea consistente entre tarjetas.
// `null` representa "no aplica" (ej. findings sin SQL, ANALYZE sobre el
// índice existente) y se pinta neutro — no debe leerse como falla.
const VALIDACIONES = [
  {
    key: "schema_ok",
    label: "schema OK",
    titulo: "La tabla y columna referenciadas existen en el schema.",
  },
  {
    key: "no_duplicate_index",
    label: "no duplica índice",
    titulo: "El índice propuesto no duplica uno ya existente.",
  },
  {
    key: "syntax_valid",
    label: "sintaxis válida",
    titulo: "El SQL parsea con sqlglot.",
  },
  {
    key: "sandbox_improves",
    label: "sandbox confirma mejora",
    titulo:
      "El planner del sandbox cambia a un nodo Index/Bitmap al aplicar la recomendación.",
  },
];

function ValidationItem({ estado, label, titulo }) {
  let clase = "validation-pill";
  let icono = "—";
  let aria = "no aplica";
  if (estado === true) {
    clase += " validation-pass";
    icono = "✓";
    aria = "pasó";
  } else if (estado === false) {
    clase += " validation-fail";
    icono = "✗";
    aria = "falló";
  } else {
    clase += " validation-na";
  }
  return (
    <span className={clase} title={titulo} aria-label={`${label}: ${aria}`}>
      <span className="validation-icon" aria-hidden="true">
        {icono}
      </span>
      <span className="validation-label">{label}</span>
    </span>
  );
}

function ValidationIndicators({ validations }) {
  // Si el backend no envió `validations` (compatibilidad con respuestas
  // antiguas), no renderea nada — preferible al ruido de 4 N/A.
  if (!validations) return null;
  return (
    <div
      className="card-validations"
      role="group"
      aria-label="Validaciones de la recomendación"
    >
      <span className="card-validations-title">Validaciones</span>
      <div className="card-validations-list">
        {VALIDACIONES.map(({ key, label, titulo }) => (
          <ValidationItem
            key={key}
            estado={validations[key] ?? null}
            label={label}
            titulo={titulo}
          />
        ))}
      </div>
    </div>
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

      <ValidationIndicators validations={rec.validations} />

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

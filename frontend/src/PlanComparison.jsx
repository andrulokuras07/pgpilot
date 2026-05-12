/**
 * Comparativo before/after del plan — C11. Renderea dos paneles lado a
 * lado con el tipo de nodo y el costo total que el sandbox midió antes y
 * después de aplicar el índice recomendado.
 *
 * Recibe `recommendation.sandbox_plan_comparison` (puede ser `null` si
 * el sandbox no estaba disponible o si la recomendación fue saltada —
 * caso ANALYZE) y `recommendation.sandbox_verdict`. Cuando falta data
 * suficiente para mostrar mejora numérica, degrada a cualitativo
 * (sólo tipos de nodo) o muestra un mensaje neutral.
 *
 * Importante: el sandbox monta tablas vacías por R6, así que los costos
 * absolutos no representan producción. La señal honesta es el cambio
 * cualitativo del tipo de nodo (Seq Scan → Index Scan); el factor de
 * mejora se etiqueta como "estimado en sandbox" para no engañar al
 * usuario en el demo.
 */
import "./Card.css";

function formatCost(value) {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "0";
  if (value < 0.01) return value.toExponential(2);
  return value.toLocaleString("es-MX", { maximumFractionDigits: 2 });
}

function improvementFactor(before, after) {
  if (
    typeof before !== "number" ||
    typeof after !== "number" ||
    after <= 0 ||
    before <= 0
  ) {
    return null;
  }
  return before / after;
}

function PlanComparison({ comparison, verdict }) {
  if (!comparison) {
    return (
      <div className="plan-comparison plan-comparison-empty">
        <span className="comparison-empty-msg">
          Sin comparativo disponible — sandbox no configurado o recomendación
          no validable estructuralmente.
        </span>
      </div>
    );
  }

  const {
    node_type_before: typeBefore,
    node_type_after: typeAfter,
    cost_before: costBefore,
    cost_after: costAfter,
  } = comparison;

  const factor = improvementFactor(costBefore, costAfter);
  const nodoMejoro = typeBefore === "Seq Scan" && typeAfter && typeAfter !== "Seq Scan";

  return (
    <div className="plan-comparison">
      <header className="comparison-header">
        <span className="comparison-title">Comparativo del plan en sandbox</span>
        {verdict ? (
          <span className={`verdict-badge verdict-${verdict}`}>{verdict}</span>
        ) : null}
      </header>
      <div className="comparison-panes">
        <section className="comparison-pane comparison-before">
          <span className="comparison-label">Antes</span>
          <div className="comparison-node">{typeBefore ?? "—"}</div>
          <div className="comparison-cost">
            cost <strong>{formatCost(costBefore)}</strong>
          </div>
        </section>
        <div className="comparison-arrow" aria-hidden="true">
          →
        </div>
        <section
          className={`comparison-pane comparison-after ${nodoMejoro ? "comparison-after-better" : ""}`}
        >
          <span className="comparison-label">Después</span>
          <div className="comparison-node">{typeAfter ?? "—"}</div>
          <div className="comparison-cost">
            cost <strong>{formatCost(costAfter)}</strong>
          </div>
        </section>
      </div>
      {factor !== null && (
        <p className="comparison-summary">
          <strong>{factor.toFixed(1)}x</strong> mejora estimada en sandbox
          (costos sobre tablas vacías — la magnitud real depende de stats de
          producción).
        </p>
      )}
      {factor === null && nodoMejoro && (
        <p className="comparison-summary">
          Cambio cualitativo positivo: el planner pasa de escaneo secuencial a
          uso de índice.
        </p>
      )}
    </div>
  );
}

export default PlanComparison;

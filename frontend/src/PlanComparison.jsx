/**
 * Comparativo before/after del plan — C11 + E7 (versión enriquecida).
 * Renderea, para cada recomendación validada en sandbox:
 *   - La transición de tipo de nodo (¿pasó de Seq Scan a Index Scan?)
 *     como titular destacado.
 *   - Dos paneles lado a lado "Antes" / "Después" con tipo de nodo,
 *     costo estimado y filas estimadas por el planner en cada corrida.
 *   - Un resumen ejecutivo automático: "redujo el costo estimado de
 *     X a Y (Zx mejora)" — o, cuando no hay factor numérico fiable,
 *     el cambio cualitativo de tipo de nodo.
 *
 * Recibe `recommendation.sandbox_plan_comparison` (puede ser `null` si
 * el sandbox no estaba disponible o si la recomendación fue saltada —
 * caso ANALYZE) y `recommendation.sandbox_verdict`. Cuando falta data
 * suficiente para mostrar mejora numérica, degrada a cualitativo
 * (sólo tipos de nodo) o muestra un mensaje neutral.
 *
 * Honestidad (regla #1 del proyecto): el sandbox monta tablas vacías
 * por R6, así que los costos y filas absolutos no representan
 * producción. La señal honesta es el cambio cualitativo del tipo de
 * nodo (Seq Scan → Index Scan); el factor de mejora se etiqueta como
 * "estimado en sandbox" para no engañar al usuario en el demo. No se
 * muestran tiempos: el EXPLAIN del sandbox corre sin `ANALYZE` (sobre
 * tablas vacías un `EXPLAIN ANALYZE` no informaría), así que no hay
 * tiempo real que reportar.
 */
import "./Card.css";

function formatCost(value) {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "0";
  if (value < 0.01) return value.toExponential(2);
  return value.toLocaleString("es-MX", { maximumFractionDigits: 2 });
}

function formatRows(value) {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("es-MX");
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

function ComparisonPane({ label, nodeType, cost, rows, better }) {
  return (
    <section
      className={`comparison-pane comparison-${label} ${better ? "comparison-after-better" : ""}`}
    >
      <span className="comparison-label">{label === "before" ? "Antes" : "Después"}</span>
      <div className="comparison-node">{nodeType ?? "—"}</div>
      <div className="comparison-metric">
        cost <strong>{formatCost(cost)}</strong>
      </div>
      <div className="comparison-metric">
        filas est. <strong>{formatRows(rows)}</strong>
      </div>
    </section>
  );
}

function ExecutiveSummary({ factor, costBefore, costAfter, nodoMejoro }) {
  if (factor !== null) {
    return (
      <p className="comparison-summary">
        <strong className="comparison-summary-lead">Resumen:</strong> redujo el costo
        estimado de <strong>{formatCost(costBefore)}</strong> a{" "}
        <strong>{formatCost(costAfter)}</strong> — <strong>{factor.toFixed(1)}x</strong>{" "}
        mejora estimada en sandbox (los costos son sobre tablas vacías por R6, la
        magnitud real depende de las stats de producción).
      </p>
    );
  }
  if (nodoMejoro) {
    return (
      <p className="comparison-summary">
        <strong className="comparison-summary-lead">Resumen:</strong> cambio cualitativo
        positivo — el planner deja el escaneo secuencial y pasa a usar el índice. El
        sandbox monta tablas vacías (R6), así que no estima un factor numérico fiable; la
        señal honesta es el cambio de tipo de nodo.
      </p>
    );
  }
  return null;
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
    plan_rows_before: rowsBefore,
    plan_rows_after: rowsAfter,
  } = comparison;

  const factor = improvementFactor(costBefore, costAfter);
  const nodoMejoro = typeBefore === "Seq Scan" && typeAfter && typeAfter !== "Seq Scan";
  const huboTransicion = Boolean(typeBefore) && Boolean(typeAfter) && typeBefore !== typeAfter;

  return (
    <div className="plan-comparison">
      <header className="comparison-header">
        <span className="comparison-title">Comparativo del plan en sandbox</span>
        {verdict ? (
          <span className={`verdict-badge verdict-${verdict}`}>{verdict}</span>
        ) : null}
      </header>

      {huboTransicion && (
        <p className={`comparison-transition ${nodoMejoro ? "comparison-transition-better" : ""}`}>
          El planner pasa de <code>{typeBefore}</code> a <code>{typeAfter}</code>
          {nodoMejoro ? " — ahora usa el índice recomendado." : "."}
        </p>
      )}

      <div className="comparison-panes">
        <ComparisonPane label="before" nodeType={typeBefore} cost={costBefore} rows={rowsBefore} />
        <div className="comparison-arrow" aria-hidden="true">
          →
        </div>
        <ComparisonPane
          label="after"
          nodeType={typeAfter}
          cost={costAfter}
          rows={rowsAfter}
          better={nodoMejoro}
        />
      </div>

      <ExecutiveSummary
        factor={factor}
        costBefore={costBefore}
        costAfter={costAfter}
        nodoMejoro={nodoMejoro}
      />
    </div>
  );
}

export default PlanComparison;

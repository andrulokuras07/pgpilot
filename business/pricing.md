# PgPilot — Modelo de pricing

> Ticket F11 del backlog. Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026. Depende de la investigación competitiva en [`competencia.md`](./competencia.md).

## 1. Filosofía de pricing

PgPilot adopta un modelo **per-seat (por developer)** en lugar de **per-server**. Esta es una decisión deliberada que se aleja del estándar del segmento de monitoring de Postgres (pganalyze cobra por servidor, Datadog DBM por host) y se acerca al estándar de developer tools modernos (Cursor, Copilot, Linear, Notion).

**Razones para per-seat:**

- El usuario final de PgPilot es el developer que escribe el SQL, no la organización que opera el servidor. La recomendación se aplica a una persona que aprende y toma decisiones.
- Cursor (Pro $20 USD/mes, Business $40 USD/mes) y GitHub Copilot ($10 individual, $19 Business, $39 Enterprise) demuestran que el mercado de developer tools acepta y prefiere este modelo. Cursor llegó a $2 B ARR en febrero de 2026 con este pricing.
- Per-server castiga a los equipos que tienen muchas réplicas; per-seat alinea el costo con el valor entregado (cada developer optimiza queries, no cada servidor).
- Reduce fricción para empezar: un developer individual puede pagar de su tarjeta sin pasar por procurement; el modelo per-server arranca en $149/mes y requiere aprobación corporativa.

**Trade-off aceptado:** organizaciones con pocos developers pero muchos servidores Postgres pagan menos con PgPilot que con pganalyze, lo cual ataca directamente el upside de cuentas grandes. Mitigación: el tier Enterprise tiene un piso de $5,000 USD/año por organización para no perder economía de unidad en cuentas con 1-3 devs y 20+ servidores.

---

## 2. Tabla de tiers

| Tier | Precio | Comprador | Features incluidas | Justificación |
|---|---|---|---|---|
| **Free** | $0 USD/mes | Developer individual aprendiendo o evaluando | 1 base de datos · análisis ad-hoc ilimitados · modo LLM apagado (explicaciones por plantilla) · sandbox local · 0 workload analysis · sin SSO · soporte por GitHub Issues | Onboarding sin fricción y demostración de valor antes de cobrar. Sin LLM mantiene el costo marginal en cero. Compatible con la regla R5 (el producto funciona sin LLM). Equivale al trial de DBtune (hasta 3 DB) pero indefinido. |
| **Pro** | $29 USD/dev/mes | Backend developer senior o tech lead | Todo Free · hasta 3 bases de datos · LLM activado (Claude) · workload analysis (`pg_stat_statements`) · sandbox cloud · histórico de análisis 30 días · catálogo completo de detectores · soporte por correo | Posicionado entre pgMustard (95 €/año = ~$8 USD/mes, manual) y Cursor Pro ($20). El delta sobre Cursor refleja que PgPilot incluye sandbox cloud + costo Claude API (no marginal). Punto de entrada accesible para developers LATAM (1 hora de salario senior mexicano ≈ $25-35 USD). |
| **Team** | $49 USD/dev/mes (mínimo 3 devs) | Tech lead o engineering manager de equipo 3-20 devs | Todo Pro · DBs ilimitadas · SSO básico (Google / GitHub OAuth) · RBAC por equipo · histórico 90 días · workload compartido · panel de equipo · soporte por chat en horario hábil LATAM | Posicionado vs Cursor Business ($40) y Copilot Business ($19). Premium sobre Cursor por el costo del sandbox cloud compartido y por el panel de equipo. Mínimo 3 devs evita canibalizar Pro. |
| **Enterprise** | Desde $99 USD/dev/mes · piso $5,000 USD/año por organización | CTO, VP Engineering, DBA team lead | Todo Team · self-hosted Docker · modo offline (bundle JSON sin conexión a BD productiva) · SOC2 / ISO27001 readiness · audit logs · SSO empresarial (SAML, Okta) · detectores custom · retención configurable · SLA 99.9% · soporte dedicado con SLA respuesta 4 h | Posicionado vs pganalyze Enterprise (custom) y Copilot Enterprise ($39). El upcharge captura el costo de compliance + soporte dedicado. El piso anual asegura economía de unidad en cuentas pequeñas con datos sensibles (fintech / healthtech LATAM). |

---

## 3. Anatomía del costo unitario (sanity check)

Para validar que los precios cubren costos y dejan margen:

- **Costo variable por análisis (tier Pro):** API Anthropic Claude ~$0.02 promedio por análisis (sanitizer + prompt estructurado + validación cruzada, < 4 KB de tokens), sandbox Postgres efímero ~$0.001 por análisis (CPU + RAM por <30 s), infra fija prorrateada ~$0.005. Total ~$0.026 por análisis.
- **Uso promedio estimado por developer Pro:** 30 análisis/mes (basado en hipótesis de F4-F8, validar en entrevistas). Costo variable mensual ≈ $0.78/dev.
- **Margen bruto Pro:** $29 - $0.78 = $28.22 ≈ 97% gross margin. Hay espacio amplio para usuarios power que ejecuten 200 análisis/mes (costo ~$5.20, margen aún 82%).
- **Punto de equilibrio Free:** sin LLM, sin sandbox cloud, sin histórico. Costo variable estructural cercano a cero. Free no canibaliza Pro porque el valor diferencial (LLM, workload, histórico) es el motor de la conversión.

---

## 4. Estrategia de upgrade

- **Free → Pro:** se gatilla cuando el usuario conecta una segunda BD, pide explicación con LLM (prompt visible "necesitas Pro para activar Claude"), o pega un workload `pg_stat_statements` (la pestaña existe pero requiere Pro).
- **Pro → Team:** se gatilla cuando un segundo developer del mismo dominio email se registra y el primero lo invita; o cuando alguien crea un workspace y agrega a 2+ colaboradores.
- **Team → Enterprise:** se gatilla por procurement (compliance, datos sensibles, contrato anual) más que por features de producto. La sales motion cambia: outbound LATAM en sectores fintech / healthtech / govtech.

---

## 5. Posicionamiento contra cada competidor

- **vs pganalyze ($149-$399 USD/mes/servidor):** PgPilot es 5-10× más barato para equipos con muchos servidores y pocos developers, pero más caro para 1 servidor + 20 developers. Sales pitch: "no pagues por cada réplica de tu cluster, paga por cada developer que toma decisiones."
- **vs EverSQL (gratis vía Aiven):** EverSQL es imbatible en precio mientras estés dentro del ecosistema Aiven. PgPilot compite con (a) clientes que no quieren lock-in a Aiven, (b) clientes que necesitan validación en sandbox antes de aplicar recomendaciones, (c) clientes que necesitan modo offline.
- **vs DBtune (trial 3 DB):** no compite — DBtune ataca configuración de servidor, PgPilot ataca queries e índices. Mensaje complementario: "usa DBtune para tunear tu instancia, PgPilot para tunear tus queries."
- **vs pgMustard (95 €/año ≈ $8 USD/mes):** PgPilot es 3.6× más caro en Pro, lo cual es difícil de justificar para un developer individual. Mensaje: pgMustard es paste-and-go manual, PgPilot tiene workload, sandbox, histórico e idioma LATAM. Para developer Pro: $29 sigue siendo accesible (~1 café/día). Reconocer honestamente que pgMustard es la mejor opción para alguien que solo quiere analizar 1-2 planes a la semana.

---

## 6. Riesgos del modelo

- **Riesgo: anclaje pganalyze.** Si el evaluador (o cliente potencial) tiene en mente el pricing per-server de pganalyze, $29/dev suena caro hasta que se multiplica por developers. Mitigación: la tabla del pitch debe mostrar comparación a paridad real (ej: empresa con 10 devs + 5 servidores Postgres: pganalyze Scale ~$499/mes vs PgPilot Pro 10×$29 = $290/mes).
- **Riesgo: free tier ataca conversión.** Si Free incluye demasiado, el upgrade a Pro nunca llega. Mitigación: LLM y workload están detrás del paywall — son los dos features que motivan a pagar según hipótesis de F4-F8.
- **Riesgo: validación de pricing.** Estos precios no han sido validados con paying customers todavía. F6-F8 (entrevistas) tienen que probar el rango — específicamente la pregunta del backlog "¿pagarías $29 USD/mes por una herramienta que te recomiende índices y reescriba queries?". Si la respuesta moda en LATAM es "no, $15", reajustar Pro a $19 manteniendo Team y Enterprise.
- **Riesgo: cambio de Claude API pricing.** El cálculo de gross margin asume tokens Claude Sonnet 4.6 al pricing actual. Si Anthropic sube 2-3×, el margen Pro baja a 90% (sigue saludable). Si sube 10×, hay que considerar caché agresiva o downgrade a Haiku para queries sencillas.

---

## Fuentes

- [Cursor pricing 2026](https://www.cursor.com/pricing) — Pro $20 USD/mes, Business $40 USD/mes/seat (cita: Cursor llegó a $2 B ARR en febrero 2026)
- [GitHub Copilot pricing 2026](https://github.com/features/copilot/plans) — Individual $10/mes, Business $19/mes/seat, Enterprise $39/mes/seat
- [Linear pricing](https://linear.app/pricing) — desde $8/usuario/mes
- pganalyze pricing — Production $149/mes, Scale $399/mes, Enterprise custom (de [`competencia.md`](./competencia.md))
- pgMustard pricing — 95 €/año/usuario (de [`competencia.md`](./competencia.md))
- DBtune — trial gratuito hasta 3 DB (de [`competencia.md`](./competencia.md))
- Datadog DBM — $70/host (referencia de mercado, de [`competencia.md`](./competencia.md))

---

> **Nota de mantenimiento:** este archivo y `business/pricing.docx` contienen el mismo modelo. Si actualizas el `.md`, refleja los cambios también en el `.docx` para que no diverjan. Si las entrevistas F6-F8 cambian los rangos, actualizar la tabla §2, el sanity check §3, y la entrada correspondiente en `PROGRESS.md`.

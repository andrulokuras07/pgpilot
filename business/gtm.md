# PgPilot — Plan Go-to-Market (primeros 10 clientes)

> Ticket F13 del backlog. Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026. Depende del modelo de pricing en [`pricing.md`](./pricing.md).

## 1. Estrategia general

PgPilot adopta una motion **founder-led sales + content-driven inbound** para los primeros 10 clientes, no "marketing en redes". La razón: el ICP (Ideal Customer Profile, ver [`mercado.md`](./mercado.md) y `lista-entrevistados.md`) es un backend senior o tech lead LATAM con Postgres en producción, que confía en otros developers antes que en publicidad. Ese ICP se gana por demostración técnica, no por funnel de ads.

**No haremos en los primeros 12 meses:**

- Performance marketing pagado (Google Ads, Meta Ads).
- LinkedIn outreach masivo con plantillas.
- Pitch a fondos VC antes de tener tracción.
- Expandir a mercados angloparlantes (US, EU) — eso es año 3+.

**Sí haremos:**

- Catálogo de anti-patterns abierto en `/docs/patterns/` (15+ patterns ya documentados al cierre de Fase 3 — D2-D22). Cada `.md` rankea en buscadores y demuestra rigor técnico.
- Founder-led sales en 2-3 eventos LATAM presenciales del año.
- Pilotos gratuitos de 90 días para los primeros 5-10 prospects con criterios de conversión claros.
- Discord/Slack communities: PostgreSQL MX, Postgres LATAM, NodeMX, Platzi, FrontendCafé.

---

## 2. Plan paso a paso para los primeros 10 clientes

Timeline asume Demo Day el 14 de mayo de 2026 como kickoff comercial. Mes 0 = mayo 2026.

### Mes 0-1 (mayo-junio 2026): cimientos

- **Lanzamiento "Show HN / r/PostgreSQL":** post en Hacker News y r/PostgreSQL titulado "PgPilot — open catalog of 15 Postgres anti-patterns, with deterministic detection and sandbox validation." Tone técnico, link al catálogo de patterns público en `/docs/patterns/`. Target: 200-500 visitas al landing, 5-10 trials del tier Pro.
- **Publicación del catálogo de patterns como artículos individuales** en Dev.to en español: 15 artículos uno por anti-pattern. Cada uno linkea al producto. Calendario: 3 por semana durante 5 semanas.
- **Setup operativo:** landing con auth + Stripe (tier Free abierto, Pro tras credit card), Cal.com para agendar demos, Loom para video walkthroughs grabados.
- **Costo estimado:** $0 directo (Show HN gratis, Dev.to gratis), tiempo founder ~80 h.
- **Resultado esperado:** 3-5 conversaciones cualificadas; 0-1 cliente pagando (alguien que probó Pro y siguió pagando después del trial).

### Mes 2-3 (julio-agosto 2026): outreach personal

- **Founder-led outreach a 50 CTOs / tech leads LATAM** identificados en LinkedIn dentro de fintech, healthtech, ecommerce y SaaS B2B con Postgres en stack (señales: ofertas de trabajo mencionando Postgres, charlas técnicas, GitHub público). Mensaje personal mencionando un anti-pattern específico relevante a su stack. **No usar plantillas — cada mensaje 3-5 oraciones específicas al receptor.**
- **Target de respuesta:** 10-15 % responde (5-7 conversaciones), 30 % de esos se vuelve demo agendada (2-3 demos).
- **Pilot 90 días gratis** a los 2-3 prospects más calificados (criterios: equipo 5-20 devs, Postgres ≥1 TB en prod, mencionaron problema de performance espontáneamente).
- **Costo estimado:** Cal.com $12/mes, LinkedIn Premium $59.99/mes × 2 meses = $132. Tiempo founder ~120 h.
- **Resultado esperado:** 2-3 pilotos activos, 1-2 conversaciones de procurement iniciadas.

### Mes 4-5 (sept-oct 2026): primer evento — Nerdearla

- **Nerdearla Buenos Aires** (la edición 2026 espera ~15,000 personas, gratis, sponsored model — usar la fecha confirmada del año). El evento es el más grande de habla hispana en LATAM con foco developer.
- **Format de participación:**
  - Aplicar como speaker con charla "Detectando 15 anti-patterns de Postgres sin enviar tu SQL al LLM" (deadline call for papers: ~junio). Status backup: si no aceptan, asistir igual con merchandising básico.
  - Sponsor tier Bronze (~$3K-5K USD estimado, exacto depende del año — confirmar con organizadores). Stand chico con demo en vivo.
  - 30 demos agendadas durante los 5 días del evento (slots de 20 min en Cal.com, agendados pre-evento desde la lista de outreach).
- **Costo estimado:** sponsor $4K + vuelo + hospedaje ~$1.5K + comida/transporte ~$500 = **$6K USD**.
- **Resultado esperado:** 5 pilotos nuevos firmados, 30+ tarjetas / contactos LinkedIn de calidad.

### Mes 6 (nov 2026): conversión de pilotos

- **Cierre de los pilotos del mes 2-3** que llegan a fin del trial 90 días. Conversion target: 3 de 5 pilotos activos convierten a Team. ARR captado: 3 × ~15 devs × $49/mes × 12 ≈ $26 K ARR.
- **Cierre de pilotos del evento Nerdearla** (apenas iniciados, sin presión todavía).
- **Resultado esperado:** **3-5 clientes pagando**, mezcla Pro individual + Team.

### Mes 7-9 (dic 2026-feb 2027): segundo evento — Finnosummit / Fintech week MX

- **Finnosummit México** (sept de cada año, Expo Santa Fe CDMX, foco fintech) o **Mexico Fintech Week**. PgPilot encaja fuerte aquí: el ICP fintech tiene datos sensibles y por R7+R4+R6 vendemos privacidad como diferenciador real (ver [`diferenciador.md`](./diferenciador.md)).
- **Format de participación:** sponsor Bronze + 30 demos + 1 charla intentada.
- **Costo estimado:** $4-6K (similar a Nerdearla, varía por venue).
- **Resultado esperado:** 3-4 pilotos nuevos, 1-2 Enterprise iniciados (fintech mexicana mediana, 50-200 devs).

### Mes 10-12 (mar-may 2027): cierre y consolidación

- **Conversión de pilotos Nerdearla y Finnosummit.** Target: 5 nuevos clientes pagando.
- **Caso de estudio público con el primer cliente:** post de blog con métricas reales (queries optimizadas, % mejora, tiempo ahorrado por dev/mes). El cliente recibe descuento permanente 30 % por permitirlo. Es el activo de marketing #1 para el segundo año.
- **Total al cierre del mes 12:** **10 clientes pagando, ~$60-100 K ARR.**

---

## 3. Resumen — primeros 10 clientes

| Mes | Hito | Clientes acumulados | ARR acumulado estimado |
|---|---|---|---|
| 0-1 | Show HN + Dev.to + landing | 0-1 | $0-2 K |
| 2-3 | Outreach + primeros pilotos | 1-2 | $5-10 K |
| 4-5 | Nerdearla 2026 | 1-2 (mismo) | $5-10 K (pilotos no convertidos aún) |
| 6 | Conversión pilotos mes 2-3 | 4-5 | $25-35 K |
| 7-9 | Finnosummit / Fintech week MX | 5-7 | $35-50 K |
| 10-12 | Cierre pilotos eventos + caso de estudio | **10** | **$60-100 K** |

---

## 4. Costo total del plan

| Concepto | Costo USD |
|---|---|
| Stripe + Cal.com + landing hosting (12 meses) | $300 |
| LinkedIn Premium founder (12 meses) | $720 |
| Nerdearla 2026 (sponsor + viaje) | $6,000 |
| Finnosummit / Fintech week MX (sponsor + viaje) | $5,000 |
| Diseño gráfico evento (banner, flyers) | $500 |
| Anthropic Claude API (operación durante pilotos gratis × 12 meses) | $1,000 |
| Hospedaje cloud (backend + sandbox) | $1,500 |
| **Total** | **~$15,000 USD** |

**Compromiso de capital:** $15K USD para conseguir 10 clientes con ARR $60-100K. CAC blended ≈ $1,500 por cliente. LTV con tier Team a 3 años retención = ~$26K. **LTV/CAC ≈ 17×** — sano para SaaS B2B.

> Caveat: estos cálculos son optimistas y dependen de que se ejecute el plan completo. Si algún evento falla (no aceptan charla, asistencia baja), el cliente target del mes se desplaza.

---

## 5. Estrategia posterior (mes 13+, año 2)

Una vez con 10 clientes y ARR ~$80 K:

- **Pasar de founder-led a inbound dominante.** El catálogo de patterns acumula SEO, los casos de estudio empiezan a citarse, y los primeros clientes refieren.
- **Primer hire: AE (Account Executive) LATAM** con quota $200 K ARR año, salario base $25-30 K USD + comisión.
- **Expansión geográfica selectiva:** España (mismo idioma, ICP similar tech lead fintech), no US todavía (compite frontalmente con pganalyze).
- **Partner program:** consultoras LATAM (Stormatics-style) revenden PgPilot con margen 25 % a sus clientes Postgres.
- **Producto:** features Enterprise (audit logs, custom detectors, SAML) que los clientes Team grandes piden.
- **Meta año 2:** 50 clientes, $350 K ARR.

Esto alimenta el plan year-by-year esbozado en [`mercado.md`](./mercado.md) (§4) que llega a SOM medio $850 K ARR en año 4.

---

## 6. Riesgos y mitigaciones

- **Riesgo: Show HN flopea.** Probabilidad 60 %. Mitigación: no depender del lanzamiento viral — el plan funciona aunque el HN post quede ignorado, porque el outreach personal y los eventos son la columna vertebral.
- **Riesgo: Nerdearla no acepta la charla.** Probabilidad 50 %. Mitigación: asistir como sponsor / atendee igual; las charlas amplifican pero las demos del stand son el motor de generación de pipeline.
- **Riesgo: el pilot 90 días no convierte.** Probabilidad alta si los criterios de selección no son estrictos. Mitigación: criterios de selección documentados (equipo ≥5 devs, Postgres ≥1 TB, problema concreto mencionado), y check-in semanal del founder durante el pilot.
- **Riesgo: el ciclo de venta a fintech es más largo que 90 días.** Probabilidad 70 %. Mitigación: pricing tier Pro permite que un dev individual de la fintech "pruebe por su cuenta" en paralelo al pilot Team — convierte primero el individuo, luego el equipo.
- **Riesgo: no contar con autorización de los compañeros del proyecto para usar el repo como producto post-Demo Day.** Es académico hoy. Mitigación: tomar decisión post Demo Day; si el equipo no continúa, el caso de Go-to-market vive como documento de ejercicio académico (que es lo que F13 entrega para la rúbrica).

---

## Fuentes

- [Nerdearla 2025 en Buenos Aires (15K asistentes)](https://nerdearla.com/en/) y [perfil del evento en dev.events](https://dev.events/conferences/nerdearla-2025-buenos-aires-kx86j6gh)
- [Mexico Fintech Week](https://www.mexicofintechweek.com) y [Finnosummit 2026 en Expo Santa Fe CDMX](https://globalconference.ca/top-technology-conferences-in-mexico/)
- [Open Finance 2050 LATAM (mayo 2026)](https://mx.america-digital.com/?lang=en) (referencia evento fintech CDMX)
- Modelo de pricing y tiers — ver [`pricing.md`](./pricing.md)
- Diferenciadores defendibles — ver [`diferenciador.md`](./diferenciador.md)
- ICP y entrevistas planificadas — ver [`lista-entrevistados.md`](./lista-entrevistados.md) y [`guion-entrevistas.md`](./guion-entrevistas.md)

---

> **Nota de mantenimiento:** este archivo y `business/gtm.docx` contienen el mismo plan. Si actualizas el `.md`, refleja los cambios también en el `.docx`. Las fechas de eventos y los costos de sponsor pueden cambiar año con año — confirmar con los organizadores antes de comprometer presupuesto.

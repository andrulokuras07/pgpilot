# PgPilot — Análisis de mercado (TAM / SAM / SOM)

> Ticket F12 del backlog. Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026. Depende de la investigación competitiva en [`competencia.md`](./competencia.md) y del modelo de pricing en [`pricing.md`](./pricing.md).

## 1. Metodología

TAM, SAM y SOM no son números exactos — son cotas razonadas con fuente.

- **TAM (Total Addressable Market):** el tamaño global del mercado si PgPilot se vendiera en todo el mundo sin restricciones de idioma, geografía o segmento.
- **SAM (Serviceable Available Market):** la porción del TAM que PgPilot puede atender realísticamente dado su scope (Postgres) y su foco geográfico (LATAM en v1, expandible).
- **SOM (Serviceable Obtainable Market):** la fracción del SAM que PgPilot puede capturar en 3-5 años (1-5%, alineado al rango sugerido por el backlog F12).

Cada número se acompaña de fuente citable y razonamiento explícito. Donde hay incertidumbre, se elige la cota conservadora.

---

## 2. TAM — Mercado global de herramientas de optimización de bases de datos

### Punto de partida: DBMS global

Gartner reporta el mercado global de Database Management Systems (DBMS) en:

- **$119.7 B USD en 2024** (crecimiento 13.4 % YoY).
- **$137 B USD en 2025** (crecimiento 16 %).
- **$161 B USD proyectado para 2026** (crecimiento 18.4 %).

Esto NO es el TAM de PgPilot. PgPilot no vende DBMS, vende **una herramienta de optimización encima de DBMS**. El TAM relevante es la subcategoría "Database performance / optimization tools."

### Carve-out hacia el mercado addressable

Aplicamos tres recortes sucesivos:

1. **Postgres-only:** PostgreSQL adopción 55.6 % entre developers en 2025 (Stack Overflow Developer Survey 2025, citado por Percona y Yugabyte). Como proxy del gasto, Postgres captura un share creciente del mercado DBMS, estimado conservadoramente en 15-20 % del gasto enterprise (más bajo que el share de developer mindshare porque Oracle / SQL Server / DB2 dominan en gasto pesado pero estancado).
2. **Subset performance / optimization:** herramientas tipo pganalyze / Datadog DBM / EverSQL representan ~2-5 % del gasto DBMS total (basado en análisis de mercado de Mordor / Grand View Research que sitúan el subsegmento de database performance management en $4-6 B USD globales en 2025).
3. **Resultado:** TAM PgPilot global ≈ **$0.6-1.2 B USD ARR** en 2025-2026.

> **Cota conservadora elegida: TAM = $800 M USD ARR.**

### Sensibilidad

- Si Postgres acelera (CAGR 28 % proyectado por Research and Markets para serverless Postgres) y la subcategoría optimization captura más share (5 → 8 % por presión de costos cloud), el TAM podría llegar a $1.5-2 B USD para 2030.
- Si el mercado se consolida (pganalyze + Datadog + AWS RDS Insights nativo) y PgPilot queda fuera del estándar, el TAM efectivo cae a < $400 M.

---

## 3. SAM — LATAM con Postgres en producción

### Población de developers en LATAM

- **2.0 - 2.6 M developers en LATAM** (Statista 2023, actualizado por Alcor 2025 y Next Idea Tech 2025).
- **Brasil:** 759 K developers (cifra conservadora Alcor) a 5.4 M (cifra agresiva Howdy.com incluyendo aspirantes).
- **México:** 563 K (Alcor) a 1.9 M (Howdy).
- **Argentina + Colombia + Chile + resto:** ~500-800 K combinado.

> **Cota conservadora elegida: 2.0 M developers profesionales en LATAM.**

### Subset: developers backend que tocan Postgres en producción

Aplicamos dos filtros adicionales:

1. **Backend developers (vs frontend / mobile / data-only):** aproximadamente 40-50 % del total son backend o full-stack con responsabilidad de BD. Cota: **45 %**.
2. **Postgres específicamente:** dado el share de 55.6 % de Postgres entre developers y asumiendo overlap moderado en LATAM (los stacks dominantes en LATAM son Node/Express + Postgres, Django + Postgres, Spring + Postgres), aplicamos **55 %** del subset backend.

Resultado: 2.0 M × 45 % × 55 % ≈ **495 K developers LATAM backend con Postgres**.

### Conversión a ARR

A $29 USD/dev/mes (tier Pro, ver [`pricing.md`](./pricing.md)):

- 495 K × $29 × 12 = **$172 M USD ARR si cada developer paga Pro**.

Esto es teórico. No todos los developers son potenciales clientes pagantes — muchos trabajan en empresas que no pagan tooling, muchos están en proyectos personales, muchos no tendrían autorización. Aplicamos un coeficiente de "willingness to pay" de **20 %** (alineado con benchmarks de developer tools en mercados emergentes: 15-25 % de los developers están en empresas que pagan herramientas premium).

> **SAM elegido: 495 K × 20 % × $29 × 12 ≈ $34 M USD ARR.**

### Sensibilidad

- Si expandimos a US Hispanic (los Hispanic backend devs en US con afinidad cultural / idioma para tooling LATAM): +50-100 K dev potenciales, SAM podría llegar a $40-45 M.
- Si limitamos solo a México (foco realista para Demo Day y primer año): población México backend Postgres ≈ 140 K dev, SAM ≈ $10 M USD ARR.

---

## 4. SOM — Lo que PgPilot puede capturar en 3-5 años

Aplicando el rango sugerido por el backlog F12 (1-5 % del SAM en 3-5 años):

- **SOM bajo (1 %, 3 años):** $340 K USD ARR ≈ 970 developers pagando Pro ≈ 25-40 cuentas Team (asumiendo 15-25 devs promedio por cuenta).
- **SOM medio (2.5 %, 4 años):** $850 K USD ARR ≈ 2,400 developers pagando Pro ≈ 60-100 cuentas Team.
- **SOM alto (5 %, 5 años):** $1.7 M USD ARR ≈ 4,900 developers ≈ 120-200 cuentas Team.

> **SOM elegido para narrativa de pitch: $850 K USD ARR a 4 años (2.5 %).**

Esto cubre runway de un equipo fundador de 3-4 personas con salarios LATAM senior ($60-80 K USD/año c/u), gastos operativos cloud (~$50 K/año) y margen para reinvertir en producto. Sin VC, viable como bootstrapped a partir del año 2.

### Plan para llegar a SOM medio (referencia para F13 — go-to-market)

- **Año 1 (2026-2027):** 50 cuentas Pro individuales + 10 cuentas Team chicas. Adquisición vía contenido técnico (catálogo de patterns abierto), comunidad Postgres MX (PostgreSQL Day México), Discord de devs LATAM. ARR objetivo: $50 K.
- **Año 2 (2027-2028):** 200 cuentas Pro + 30 Team. Sales motion ligero (founder-led), una conferencia LATAM (FintechMX, Nerdearla). ARR objetivo: $250 K.
- **Año 3 (2028-2029):** 500 Pro + 80 Team + 5 Enterprise. Primer hire de sales LATAM. ARR objetivo: $500 K.
- **Año 4 (2029-2030):** SOM medio alcanzado. ARR objetivo: $850 K.

---

## 5. Comparación con la competencia

Para contexto (datos públicos o estimados conservadoramente):

| Empresa | ARR estimado | Geografía dominante | Modelo |
|---|---|---|---|
| **pganalyze** | $5-15 M USD (estimación, no público; ~1,000-3,000 servidores @ $149-$399/mes) | US + Europa | Per-server SaaS |
| **EverSQL (Aiven)** | Parte del ARR Aiven (~$200 M ARR Aiven global 2025) | Global, US/EU pesado | Bundle con Aiven |
| **DBtune** | $1-3 M USD (estimación seed, AWS Marketplace) | US + Europa | Per-instance SaaS |
| **pgMustard** | $0.3-1 M USD (95 €/año × pocos miles de devs) | Global anglo | Per-user SaaS |
| **PgPilot (SOM objetivo año 4)** | $850 K USD | LATAM | Per-developer SaaS |

PgPilot no aspira a competir con pganalyze en US. Aspira a ser **la opción default en LATAM** — un nicho geográfico que ningún competidor atiende con foco. La hipótesis "developers LATAM prefieren tooling en español con pricing accesible y modo offline" tiene señales fuertes en las 3 entrevistas F6/F7/F8 (los 3 son LATAM, ninguno usa pganalyze ni EverSQL, los 3 valoran read-only/privacidad, Raúl F8 pide self-hosted explícito); la prueba comercial real es post-Demo Day en los primeros pilotos.

---

## 6. Limitaciones del análisis

Honestidad obligada (alineado con el espíritu de F3):

- **Las cifras de developer population en LATAM varían 3× entre fuentes** (Alcor estima 2 M, Howdy estima 7 M incluyendo aspirantes y junior). Usamos la cota baja para no inflar SAM.
- **El coeficiente de 20 % "willingness to pay" no está validado a nivel agregado de mercado** — viene de benchmarks generales de developer tools, no de research específico de LATAM Postgres. Señal a nivel individual: en las 3 entrevistas F6/F7/F8 ninguno objetó el rango $50-200/BD, aunque Raúl (F8) cuestionó si el modelo por BD es el correcto cuando tienes 15-20 BDs. Para ajustarlo al alza o a la baja a nivel mercado se necesitan los primeros pilotos pagados post-Demo Day.
- **El 55 % de Postgres entre developers globales no se mapea automáticamente a LATAM.** Stack Overflow Developer Survey tiene sesgo anglo. En LATAM puede ser mayor (Postgres es default en muchos bootcamps mexicanos y brasileños) o menor (MySQL legado en agencias pequeñas).
- **El SAM excluye verticales adyacentes que podrían pagar más:** consultoras LATAM que venden optimización Postgres como servicio podrían pagar Enterprise para usar PgPilot como herramienta interna. Si esa hipótesis se valida, SAM efectivo crece 20-30 %.
- **El TAM global ($800 M) es una estimación cruzada de varios reports.** No hay un número Gartner publicado específico para "Postgres optimization tools." La cota puede estar off por ±40 %.

---

## Fuentes

- [Gartner: Forecast Database Management Systems Worldwide 2023-2029, 2025 Update](https://www.gartner.com/en/documents/7229830) — DBMS $137 B en 2025, $161 B en 2026
- [Percona: PostgreSQL's Proprietary Future? — Key Market Trends in 2025](https://experience.percona.com/postgresql/postgresql-market-in-2025/the-growing-dominance-of-postgresql)
- [Yugabyte: Why PostgreSQL Remains the Top Choice for Developers in 2025](https://www.yugabyte.com/blog/postgresql-top-choice-in-2025/) — adopción 55.6 % en 2025
- [Research and Markets: Serverless PostgreSQL Market Report 2026](https://www.researchandmarkets.com/reports/6226512/serverless-postgresql-market-report) — $2.19 B en 2026, CAGR 27.8 %
- [Alcor: LATAM Developers Portrait & Salaries 2025](https://alcor.com/latin-american-developers/) — Brasil 759 K, México 563 K
- [Statista: Latin America Number of Software Developers 2023](https://www.statista.com/statistics/1420346/latin-american-countries-number-of-software-developers/)
- [Next Idea Tech: How Many Software Developers in Latin America](https://blog.nextideatech.com/how-many-software-developers-in-latin-america/) — 2+ millones top talent
- [Howdy.com: 2025 Latin America Software Developer Salaries](https://www.howdy.com/blog/2025-latin-america-software-developer-salaries) — cifras agresivas Brasil 5.4 M, México 1.9 M

---

> **Nota de mantenimiento:** este archivo y `business/mercado.docx` contienen el mismo análisis. Si actualizas el `.md`, refleja los cambios también en el `.docx` para que no diverjan. Las cifras de developer population y DBMS market son del momento del análisis (mayo 2026); revisar el TAM con los reportes 2027 cuando se actualice F15.

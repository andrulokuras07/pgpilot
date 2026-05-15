# PgPilot — Documento de Negocio

> Plantilla 3 de 3 (Entregables Oficiales del Proyecto Final). Consolida F3 (competencia), F6/F7/F8 (3 entrevistas — Carlos Orellán, Jos Lugo, Raúl Zavaleta), F9 (problema), F10 (persona — Andrés Villanueva), F11 (pricing), F12 (mercado), F13 (go-to-market) y F14 (diferenciador) en un solo documento de evaluación.
>
> Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026.
>
> **Nota al evaluador:** las 3 entrevistas obligatorias de la plantilla están completas y documentadas en `business/entrevista-1.md` (F6 Carlos Orellán, DBA), `entrevista-2.md` (F7 Jos Lugo, ingeniero fullstack) y `entrevista-3.md` (F8 Raúl Zavaleta, desarrollador fullstack). Sus hallazgos se integraron a §2.2 (persona), §2.3 (frecuencia/severidad cuantificada con datos 3/3), §3.1 (resumen de entrevistas) y §3.3 (aprendizajes consolidados). La sección §10 (equipo) lleva un único `[PENDIENTE: COMPLETAR DATOS DEL EQUIPO]` para nombres / matrículas / reparto técnico exacto antes de la entrega final.

---

## Índice

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Problema](#2-problema)
3. [Investigación de usuarios](#3-investigación-de-usuarios)
4. [Solución](#4-solución)
5. [Análisis competitivo](#5-análisis-competitivo)
6. [Modelo de negocio](#6-modelo-de-negocio)
7. [Tamaño de mercado](#7-tamaño-de-mercado)
8. [Go-to-market](#8-go-to-market)
9. [Diferenciador defendible](#9-diferenciador-defendible)
10. [Por qué nuestro equipo](#10-por-qué-nuestro-equipo)
11. [Roadmap a 12 meses](#11-roadmap-a-12-meses)
12. [Ask](#12-ask)

---

## 1. Resumen ejecutivo

**Problema.** Cuando una query Postgres se vuelve lenta en producción y no hay DBA al lado, las opciones actuales fallan: ChatGPT alucina y viola compliance en sectores regulados; pganalyze ($149-$399/mes/servidor) excluye equipos pequeños; pgMustard es manual; EverSQL encierra al cliente en Aiven. El dev pierde horas con `EXPLAIN ANALYZE` o aplica recomendaciones sin validar.

**Solución.** PgPilot combina un **motor determinístico** (Python, 19 detectores auditables) que decide qué problema existe y qué fix proponer, con una **capa LLM** (Claude Sonnet) que solo explica lo que el motor ya decidió. Toda recomendación se **valida en un sandbox Postgres efímero** antes de mostrarla. Los literales SQL se **sanitizan antes** de cualquier llamada al LLM. Modo offline disponible (bundle JSON, sin conectar BD productiva a SaaS externo).

**Mercado.** TAM $800 M USD ARR (Postgres optimization, recorte sobre DBMS $137 B Gartner 2025). SAM LATAM ~495 K devs backend con Postgres × 20% WTP × $29/mes = **$34 M USD ARR**. SOM medio 4 años: **$850 K USD ARR** (2.5% SAM).

**Modelo.** Per-seat (Cursor / GitHub Copilot, no per-server). 4 tiers: Free $0 · Pro $29/dev · Team $49/dev (min 3) · Enterprise $99+/dev con piso $5K USD/año. Margen bruto Pro ≈ 97%.

**Diferenciador.** **Integridad arquitectónica de 4 defensores combinados** que un competidor no replica en 90 días sin rehacer su producto: motor determinístico + sanitización fuerte + validación en sandbox + modo offline. Foco LATAM (idioma, horario, network) como defensa comercial transversal.

**Equipo.** 6 estudiantes de Ingeniería en Sistemas Computacionales, Universidad Anáhuac Querétaro. Producto construido un semestre con metodología disciplinada (motor revisado por humanos, capa IA con guardrails) — el mismo método que permite venderlo como producto controlado.

**Ask.** Académico (Demo Day 14-may-2026): validación del modelo y guardrails frente al jurado. Comercial post-Demo: introducciones a 5-10 CTOs/tech leads LATAM (fintech/healthtech/SaaS) para pilotos gratuitos de 90 días + mentoría founder-led-sales LATAM.

---

## 2. Problema

### 2.1 Descripción del problema

Cuando un developer backend escribe una query nueva contra Postgres, no sabe con certeza si será lenta en producción **hasta que producción la pruebe**. Los síntomas aparecen tarde (p95, queja de cliente, timeout nocturno) y para entonces hay que leer `EXPLAIN ANALYZE` a mano. Si la empresa no tiene DBA dedicado — el caso de la mayoría de equipos LATAM medianos (5-50 devs) — el dev tiene 3 opciones, todas malas: **(1) ChatGPT** alucina índices y columnas + manda datos productivos a un tercero (viola LGPD / LFPDPPP / GDPR); **(2) pganalyze** a $149-$399/mes/servidor es prohibitivo en pesos LATAM; **(3) Resolverlo a mano** consume 2-8 horas-developer por incidente.

El problema no es de capacidad técnica del dev. Es **falta de herramienta intermedia**: algo más confiable que un LLM genérico, más barato que un SaaS enterprise, y que respete las restricciones de privacidad de los sectores regulados de LATAM.

### 2.2 User persona principal

**Andrés Villanueva — Tech Lead Backend.** Persona principal derivado de F10 (`business/persona.md`).

| Atributo | Valor |
|---|---|
| **Nombre ficticio** | Andrés Villanueva |
| **Rol** | Tech Lead / Backend Senior (asume rol de DBA de facto) |
| **Edad y experiencia** | 31 años, 8 años con Postgres en producción |
| **Ubicación** | Monterrey, NL, México (remoto con equipo distribuido LATAM) |
| **Empresa** | Fintech B2B de 45 personas — plataforma de pagos y nómina para PyMEs |
| **Tamaño de equipo / BDs** | Equipo de 8 devs backend · 3 bases Postgres en producción (principal ~180 GB transaccional, reportes ~40 GB, staging) |
| **Stack** | Node.js + TypeScript, PostgreSQL 15, Redis, AWS (RDS + ECS) |
| **Día típico** | 9 AM revisa `pg_stat_activity` a mano · 11:30 AM revisa PRs con migraciones sin proceso formal de validación de queries · 2 PM atiende alerta Datadog de P99 8 s y tarda 1.5-3 h diagnosticando manualmente · 4:30 PM responde a Slack del CTO sobre el incidente |
| **Pain points principales** | (1) No hay DBA y no debería serlo él — improvisa con Google + ChatGPT, sin proceso. (2) Ciclo de diagnóstico manual y lento (logs → EXPLAIN → interpretar plan → proponer fix → staging sin volumen real). (3) No puede pegar queries reales en herramientas externas por compliance (clientes de nómina, datos LFPDPPP). (4) Code reviews no detectan anti-patterns de SQL. (5) Los problemas escalan en cierre de quincena cuando la carga se multiplica × 10. |
| **Cómo resuelve hoy** | `pg_stat_statements` + psql manual · `EXPLAIN ANALYZE` a mano · Datadog APM para latencia de endpoints (no llega a la query) · ChatGPT/Claude con queries con literales borrados manualmente · pgBadger esporádicamente · NO usa pganalyze/EverSQL/DBtune (precio en USD inasumible o nunca los encontró) |
| **Costo mensual del problema** | 1.5-3 horas-developer por incidente individual, ≥1 incidente cada 2 semanas. Ciclo manual completo ≈ 4-8 horas-developer/mes a salario senior LATAM (~$50 USD/h) = $200-400 USD/mes en tiempo directo. Sin contar incidentes mayores en cierre de quincena. |
| **Decisor de compra** | Andrés es **usuario y comprador** para tier Pro ($29/mes — lo gestiona de su presupuesto personal de herramientas o lo expensa con justificante simple). Para Team requiere conversación con el CTO (típicamente < 1 semana si Andrés está convencido). |
| **Criterio de compra #1** | Privacidad — sin sanitización fuerte de literales y read-only verificable, el área legal de la empresa bloquea la herramienta. |

**Cita representativa (F10):**

> *"Cada vez que hay un incidente de performance, paso 2 o 3 horas haciendo lo mismo: buscar la query en los logs, pegarla en psql, correr el EXPLAIN, intentar entender el plan, proponer algo en staging que nunca tiene el mismo volumen que producción. Si existiera algo que me dijera 'esta query tiene un Seq Scan en la tabla transacciones porque le falta un índice compuesto en (empresa_id, fecha_creacion), aquí está el CREATE INDEX' — y que lo pudiera correr sin necesidad de exponer datos reales — lo compraría mañana."*

**Perfiles secundarios** (F10 §"Perfil secundario — cuándo aparece un perfil diferente"):

- **Staff Engineer / Engineering Manager** en empresas de 50-200 devs: mismo dolor, ciclo de venta más largo (30-90 días vs 1-7 días) porque procurement + CTO entran al proceso.
- **CTO fundador** en empresas de 5-15 devs: compra rápido y con menos fricción pero el presupuesto es más ajustado.

### 2.3 Frecuencia y severidad

**Gradiente de dolor cuantificado (F6 Carlos + F7 Jos + F8 Raúl + F10 Andrés):**

| Perfil | BD | Tiempo/mes |
|---|---|---|
| Carlos — DBA con equipo | 3 × ~30 GB (migración) | 0.5-1 h |
| Jos — ingeniero fullstack sin DBA | 2 × 500 MB-1 GB | ~10 h |
| Andrés — persona, tech lead fintech | 3 × ~180 GB | 4-8 h |
| Raúl — dev fullstack, 100+ BDs en carrera | 15-20 BDs activas, ~3 TB la mayor | 3-4 h (prod estable) / 16-20 h (dev) |

**Conclusión clave:** el dolor escala con la **ausencia de DBA dedicado** y con la **fase del ciclo de vida**, no con el tamaño absoluto. Jos (1 GB) dedica 10× más tiempo que Carlos (30 GB con equipo). Raúl confirma la dimensión "fase": pasa de **3-4 h/mes** en producción estable a **16-20 h/mes** en etapas tempranas (desarrollo, análisis, staging) — los queries existen aunque la BD aún no esté en producción.

**Anti-patterns reportados — 2 de 3 mapean a detectores activos de PgPilot; 1 oportunidad de roadmap:**

- **Carlos (F6):** `SELECT *` sobre tablas con BLOBs → **D9** (`select_star`). ✅ Detector activo.
- **Jos (F7):** JOINs sin índices generando producto cartesiano → **D16** (`seq_scan_missing_index`). Fix manual tomó **1 semana** completa. ✅ Detector activo.
- **Raúl (F8):** tabla de embarques de 300-400 GB en sistema logístico transnacional. Queries tardaban **horas** pese a tener índices. Solución manual: particionar físicamente la tabla + tablas temporales con `COPY` de Postgres para clonar embarques recientes (~300-400 MB). Funcionaba al 90% (fechas recientes); históricos de 5-7+ años seguían lentos. 🟢 **No es un detector activo hoy**; queda como oportunidad de roadmap (detección proactiva de tablas crecientes sin estrategia de particionamiento — adyacente a D22 `count_star_on_large_table` que ya señala tablas grandes).

**Severidad y costo mensual:** **$25-1,000 USD/equipo/mes** en tiempo directo (Raúl: 16-20 h/mes en dev × $25-50/h = $400-1,000/mes; Carlos: $25-50/mes; Jos: $250-500/mes). Por incidente mayor con impacto a operaciones: **$500-5,000 USD adicionales** (Gartner cost-of-downtime; el caso de Raúl con tabla de 300-400 GB en sistema logístico muestra el costo de no tener particionamiento proactivo).

**ROI a $29/dev/mes (Pro):** equipo de 5 devs = $145/mes; ahorra ≥2 h/mes diagnóstico + previene ≥1 incidente/trimestre → **ROI positivo desde el mes 1**. **Caso Raúl:** con 16-20 h/mes en etapas tempranas × $25-50/h = $400-1,000/mes en tiempo, una herramienta a $200/mes tiene ROI 2-5× inmediato. Sin embargo, cuestionó el modelo por BD con 15-20 BDs — sugiere explorar pricing por usuarios o por tiempo de ejecución.

---

## 3. Investigación de usuarios

> **Requisito obligatorio de la plantilla:** mínimo 3 entrevistas con personas del rol objetivo. Si no se hacen, este criterio se va a 0.

### 3.1 Resumen de entrevistas

3 de 3 entrevistas completadas (F6, F7, F8). Lista completa de candidatos y criterios de selección en `business/lista-entrevistados.md` (F4); transcripciones y respuestas detalladas en `business/entrevista-1.md`, `entrevista-2.md`, `entrevista-3.md`.

| Nombre / Rol del entrevistado | Empresa / Sector | Fecha | Duración |
|---|---|---|---|
| Carlos Orellán — DBA | Software house LATAM (3 BDs Postgres, migración a ~30 GB c/u) | 13 de mayo de 2026 | ~10 min (videollamada grabada) |
| Jos Lugo — Ingeniero de software (fullstack) | Equipo de desarrollo LATAM (2 BDs Postgres, 500 MB-1 GB c/u, ~20 tablas) | 13 de mayo de 2026 | ~10 min (videollamada grabada) |
| Raúl Zavaleta — Desarrollador fullstack / Ingeniero de software | Empresa de software LATAM (15-20 BDs Postgres, la más grande ~3 TB, 100+ BDs en su carrera) | 13 de mayo de 2026 | ~10 min (videollamada grabada) |

### 3.2 Preguntas hechas

9 preguntas (guion F5, texto completo en `business/guion-entrevistas.md`) que cubren: contexto del entrevistado, flujo manual de diagnóstico, herramientas usadas, tiempo invertido/mes, caso real reciente, encaje en workflow, objeciones de seguridad, proceso de code review, decisor y precio. El guion enfatiza **comportamiento pasado**, no intenciones futuras — la gente miente para no decepcionar.

### 3.3 Aprendizajes principales

9 insights consolidados de las 3 entrevistas (F6 Carlos + F7 Jos + F8 Raúl) cruzados con el persona F10 (Andrés):

1. **Dolor reactivo, no proactivo. ✅ 3/3.** Carlos: "actuamos por eventos"; Jos: 1 semana de fix manual; Raúl: 16-20 h/mes en etapas tempranas con diagnóstico manual (DBeaver + EXPLAIN ANALYZE). **Implicación:** insertarnos en el momento de la alerta, no antes.

2. **Anti-patterns reales → 2/3 mapean a detectores activos + 1 oportunidad de roadmap. ✅ Parcial.** D9 (Carlos), D16 (Jos); Raúl (tabla 300-400 GB sin particiones) no tiene detector hoy. **Implicación:** los casos de Carlos y Jos son demos directos del pitch; el de Raúl muestra la escala enterprise (queries que tardan horas por falta de particionamiento proactivo) y motiva el roadmap de un detector adyacente.

3. **CI/desarrollo como punto de entrada con matiz. ✅ 3/3.** Carlos: PR/CI con Liquibase; Jos: dev/staging; Raúl articula dos productos distintos — análisis de arquitectura (fase de diseño de la BD) y análisis de performance en tiempo real (cualquier momento del ciclo, desde staging temprano hasta producción para mantenimiento). **Implicación:** PgPilot necesita múltiples superficies (editor + GitHub Action + monitor de workload).

4. **Privacidad y read-only son bloqueador legal. ✅ 3/3 con escalada por sector.** Carlos: read-only; Jos: no logs, control por tabla; Raúl: conexión punto a punto segura, read-only indiscutible, datos efímeros, preguntó si es on-premise o de terceros. **Implicación:** modo offline + tier Enterprise self-hosted abren el sector regulado LATAM.

5. **Decisor heterogéneo — "es el CTO" matizada. ⚠️ Parcial.** Carlos: CTO; Jos: dual técnico + gerencial (líder de infra + gerente); Raúl: equipo técnico impulsa la necesidad, CTO/directivo toma la decisión final. **Implicación:** Pro/Team con sales bottom-up al equipo técnico como impulsor + cierre con CTO/gerencia en empresas con proceso formal; Enterprise top-down al CTO.

6. **No usan herramientas especializadas. ✅ 3/3.** Ninguno usa pganalyze / EverSQL / DBtune. Raúl usa DBeaver Enterprise + pg_stat_statements + EXPLAIN ANALYZE (herramientas nativas, no SaaS). **Implicación:** PgPilot compite con "hacerlo a mano" en LATAM, no con pganalyze.

7. **Modelo de licencia per-BD cuestionado por escala enterprise. ⚠️ 1/3 cuestiona, 2/3 sin objeción.** Raúl (15-20 BDs activas, la mayor ~3 TB) cuestionó si el pricing por BD es el correcto a esa escala y sugirió explorar modelos por usuarios o por tiempo de ejecución. Carlos y Jos no objetaron el rango $50-200/BD. **Implicación:** mantener el modelo per-seat Pro $29 / Team $49 como principal; evaluar add-on por flota de BDs o tier por tiempo de ejecución para cuentas Enterprise con 15+ BDs; plan B "$19" queda como contingencia.

8. **Dolor escala con ausencia de DBA, no con tamaño puro de BD. ⚠️ Hipótesis matizada.** Jos (1 GB sin DBA) = 10 h/mes > Carlos (30 GB con equipo) = 1 h/mes. **Implicación:** ICP correcto es "5-20 devs sin DBA", no "≥100 GB".

9. **Monitor proactivo de degradación como 2º caso de uso. 🟢 Oportunidad nueva (Raúl).** *"Que revise queries existentes y avise cuáles se pueden optimizar"*. **Implicación:** feature Q3/Q4 sobre `pg_stat_statements` con tracking histórico + alertas.

**Hipótesis resueltas / abiertas:** WTP $29 🟡 sin objeción de Carlos y Jos, pero Raúl cuestionó el modelo per-BD para flotas grandes — falta validación con paying customers; "dolor crece con tamaño" ⚠️ matizada (DBA-ausencia y fase del ciclo de vida son los predictores reales); modo offline sin LLM 🟡 parcial (Raúl pide tratamiento efímero y prefiere on-premise; R5 explícito no preguntado — confirmar en pilotos).

**Cambios al producto / pricing / GTM derivados de F6 + F7 + F8:**

- **Producto:** GitHub Action CI en Q2; self-hosted Docker Enterprise en Q3; monitor de degradación en Q3/Q4.
- **Pricing:** mantener per-seat Pro $29 y Team $49 como modelo principal; evaluar add-on por flota de BDs o tier por tiempo de ejecución para Enterprise con 15+ BDs (señal de Raúl); plan B "$19" como contingencia.
- **GTM:** Pro/Team bottom-up con el equipo técnico como impulsor + aprobación de gerente/CTO en empresas con proceso formal (señal consistente Carlos/Jos/Raúl); Enterprise top-down a CTO + finanzas.
- **Messaging:** #1 "Read-only + sanitización fuerte"; #2 "Self-hosted disponible"; #3 "Detecta los anti-patterns que ya te dolieron — D9/D16 con casos reales + detección proactiva de tablas sin particiones".

---

## 4. Solución

El developer abre el editor web de PgPilot (tema oscuro tipo VS Code, en español), pega una query problemática y pulsa "Analizar". En 2-4 segundos aparecen tarjetas con detecciones, ejemplo:

> *"Detectamos un Seq Scan sobre `posts` (12.3 M filas) con filtro `WHERE author_id = $1`. Recomendamos `CREATE INDEX idx_posts_author_id ON posts(author_id);`. Validado en sandbox: costo 45,231 → 287 (158× mejora). Confianza: alta."*

Debajo, comparativo before/after del plan EXPLAIN con 4 indicadores de validación verdes (schema OK, no duplica índice, sintaxis válida, sandbox confirma mejora). El dev copia el SQL, lo lleva a su PR, mergea con tranquilidad. Si el LLM está habilitado (Pro+), una explicación pedagógica describe **por qué** y **qué riesgo** evita el índice.

### 4.1 Funcionalidades core

| Feature | Beneficio para el usuario |
|---|---|
| **19 detectores documentados + catálogo público (`/docs/patterns/`)** | El dev entiende qué se busca, no es una caja negra. SEO orgánico. |
| **`CREATE INDEX` listo para copiar al PR** | Del análisis al PR en minutos, no horas. |
| **Validación en sandbox efímero antes de mostrar + comparativo before/after** | Recomendación con costo verificado, no sugerencia plausible. Evidencia en el PR. |
| **Workload analysis sobre `pg_stat_statements`** | Top 10 queries por impacto (tiempo total, no frecuencia) — ataca primero lo que más duele. |
| **Sanitización fuerte de literales pre-LLM + modo "LLM apagado" con plantillas** | Compliance auditable + resiliencia si Anthropic se cae. |
| **Modo offline / bundle JSON** | Para fintech/healthtech LATAM: análisis sin conectar la BD productiva a ningún SaaS. |

**Estado al cierre del semestre (AppDB v1):** 18/20 queries detectadas (≥16 objetivo), 0/10 falsos positivos (<3 objetivo), modo "LLM apagado" funcional.

---

## 5. Análisis competitivo

> **Requisito obligatorio de la plantilla:** mínimo 3 competidores reales investigados. Investigación completa en `business/competencia.md` (F3). Aquí se resume y consolida.

### 5.1 Tabla comparativa

| Característica | pganalyze | EverSQL (Aiven) | DBtune | pgMustard | **PgPilot** |
|---|---|---|---|---|---|
| **Foco principal** | Monitoring continuo + advisors | Rewrite automático IA | Tuning de parámetros (ML) | Visualizador de EXPLAIN | Detección + recomendaciones validadas |
| **Precio entrada (USD/mes)** | $149/servidor | Gratis (vía Aiven) | Trial 3 DB; comercial no público | ~$8/usuario (95 €/año) | **$29/dev (Pro)** |
| **Modelo de deployment** | SaaS + on-premise (Enterprise) | SaaS (Aiven) | SaaS + agente en BD | SaaS (paste manual) | **Self-hosted Docker + SaaS** |
| **Mecanismo de detección** | Heurísticas + ML propietario | Modelo IA opaco | ML sobre métricas runtime | Reglas sobre el plan | **Motor determinístico + LLM solo para explicar** |
| **Validación de recomendación** | "What If?" en producción | No documentada | A/B real en producción | Ninguna (solo sugiere) | **Sandbox efímero antes de mostrar** |
| **Sanitización de datos pre-IA** | Filtros PII (tier alto) | No documentada | Solo métricas | Planes no almacenados | **Sanitización fuerte obligatoria** |
| **Modo offline** | Solo Enterprise on-prem | No | No (requiere agente) | Parcial (paste manual) | **Sí (bundle JSON)** |

### 5.2 Análisis honesto

PgPilot **no** es mejor en todo:

- **vs pganalyze** — ellos: telemetría histórica 100 días, integraciones cloud maduras, "What If?" en producción, compliance enterprise. Nosotros: precio accesible, motor auditable (no ML opaco), sanitización por diseño, idioma y horario LATAM.
- **vs EverSQL (Aiven)** — ellos: gratis dentro de Aiven, soporta MySQL, +100K ingenieros instalados. Nosotros: sin lock-in, motor determinístico vs IA opaca, validación con sandbox, catálogo público.
- **vs DBtune** — ellos: tuning autónomo de parámetros con 50-1000% mejora medida. **No competimos** — DBtune tunea parámetros, PgPilot tunea queries; mensaje complementario.
- **vs pgMustard** — ellos: ~$8/mes vs $29 Pro, paste-and-go pulido. Nosotros: workload analysis, sandbox de validación, `CREATE INDEX` listo, modo offline, español.

### 5.3 Espacio en blanco

**Nuestro nicho:** developers backend LATAM con Postgres en producción en empresas medianas (5-50 devs) en sectores regulados (fintech, healthtech, govtech), que no pueden pagar pganalyze ni mandar SQL con datos a ChatGPT.

**Por qué los competidores no atienden bien este nicho:** pganalyze tiene economía de unidad enterprise que erosionaría bajando a $30/dev; EverSQL depende del ecosistema Aiven (lock-in); DBtune ataca un eje ortogonal; pgMustard es paste-and-go individual sin workload ni compliance. **Ninguno tiene contenido, soporte ni network LATAM.**

**Por qué nosotros sí:** equipo fundador LATAM con ciclo de procurement local, stacks dominantes (Node+Postgres fintech mexicana, Spring+Postgres bancos brasileños), restricciones cambiarias USD, y acceso a comunidades regionales (PostgreSQL MX, Devs México, FrontendCafé) — no se replica con un Country Manager contratado desde fuera.

---

## 6. Modelo de negocio

> Análisis completo en `business/pricing.md` (F11). Aquí se resume.

### 6.1 Tipo de modelo de revenue

- [ ] Suscripción mensual / anual
- [ ] Por uso (pago por análisis ejecutado)
- [x] **Por seat (por developer activo)** — modelo principal
- [ ] Por instancia (por BD monitoreada)
- [x] **Freemium con tier pago** — tier Free permanente como acquisition
- [ ] Otro

**Decisión deliberada:** per-seat, no per-server. La razón: el usuario final es el developer que escribe el SQL y aprende del análisis, no la organización que opera el servidor. El modelo per-seat está validado en developer tools modernos (Cursor llegó a $2 B ARR en febrero 2026 con per-seat; GitHub Copilot $10/$19/$39; Linear desde $8/usuario). Per-server castigaría a equipos con muchas réplicas y alinea mal el costo con el valor entregado.

### 6.2 Tiers de pricing

| Tier | Precio | Comprador objetivo | Qué incluye |
|---|---|---|---|
| **Free** | $0 USD/mes | Developer individual aprendiendo o evaluando | 1 BD · análisis ad-hoc ilimitados · modo LLM apagado (plantillas) · sandbox local · sin workload · sin SSO · soporte por GitHub Issues |
| **Pro** | $29 USD/dev/mes | Backend senior / tech lead | Todo Free · hasta 3 BDs · LLM activado (Claude) · workload analysis · sandbox cloud · histórico 30 días · catálogo completo · soporte por correo |
| **Team** | $49 USD/dev/mes (mínimo 3 devs) | Tech lead / engineering manager de equipo 3-20 devs | Todo Pro · BDs ilimitadas · SSO básico (Google/GitHub OAuth) · RBAC por equipo · histórico 90 días · workload compartido · panel de equipo · soporte por chat en horario LATAM |
| **Enterprise** | Desde $99 USD/dev/mes · piso $5,000 USD/año por organización | CTO / VP Engineering / DBA team lead | Todo Team · self-hosted Docker · modo offline · SOC2/ISO27001 readiness · audit logs · SSO empresarial (SAML, Okta) · detectores custom · SLA 99.9% · soporte dedicado con SLA 4 h |

### 6.3 Justificación del precio

- **$29 Pro** se ubica entre pgMustard ($8) y Cursor Pro ($20). El delta sobre Cursor refleja sandbox cloud + costo Claude API (no marginal). Punto de entrada accesible para LATAM (~1 h de salario senior mexicano).
- **$49 Team** alineado a Cursor Business ($40) con premium por sandbox compartido y panel de equipo. El mínimo de 3 devs evita canibalizar Pro.
- **$99+ Enterprise** captura el costo de compliance + soporte dedicado. El piso anual de $5 K/año asegura economía de unidad en cuentas pequeñas con datos sensibles (fintech LATAM).
- **Margen bruto Pro estimado ≈ 97%** asumiendo 30 análisis/mes/dev (costo variable ~$0.78 por mes — Claude API + sandbox + infra prorrateada). Hay holgura amplia para usuarios power.

**Validación pendiente / hecha.** Los precios no se han probado con paying customers (la prueba real es post-Demo Day). De las 3 entrevistas: Raúl (F8, desarrollador fullstack) cuestionó el modelo por BD con 15-20 BDs — sugirió explorar pricing por usuarios o por tiempo de ejecución. Carlos (F6) y Jos (F7) no expresaron objeción al rango $50-200/BD aunque no se les preguntó precio per-dev exacto. **Conclusión:** se mantiene Pro $29 y Team $49, pero el feedback de Raúl sugiere considerar un modelo alternativo para cuentas con muchas BDs. El plan B "$19" documentado en `pricing.md` §6 queda como contingencia para casos donde el dev no tenga autonomía de compra y dependa 100% del CTO con presupuesto en pesos.

---

## 7. Tamaño de mercado

> Análisis completo, fuentes y sensibilidades en `business/mercado.md` (F12).

### 7.1 TAM

**Definición.** Universo total de herramientas de optimización para Postgres a nivel global, sin restricciones de geografía o idioma.

**Cálculo.** Partiendo del mercado DBMS global de **$137 B USD** en 2025 (Gartner 2025 Forecast Update), aplicamos dos recortes sucesivos:

1. **Postgres-only:** ~15-20% del gasto DBMS (Postgres tiene 55.6% adopción developer per Stack Overflow 2025; ese share se traduce más conservadoramente en gasto enterprise).
2. **Subset performance/optimization:** ~2-5% del gasto DBMS (mercado de database performance management estimado en $4-6 B globales por Mordor / Grand View Research).

**Resultado: TAM = $800 M USD ARR (cota conservadora).** Rango razonable: $0.6 - 1.2 B USD ARR.

**Fuentes.** Gartner: Forecast Database Management Systems Worldwide 2023-2029 (2025 Update). Yugabyte / Percona reports sobre adopción Postgres 2025. Mordor / Grand View Research sobre database performance management.

### 7.2 SAM

**Definición.** Porción del TAM que PgPilot puede atender realísticamente en su scope inicial (Postgres) y foco geográfico (LATAM).

**Cálculo.**

- 2.0 M developers profesionales en LATAM (Statista 2023, Alcor 2025 — cota conservadora; Howdy.com llega a 7 M incluyendo aspirantes).
- 45% son backend / full-stack con responsabilidad de BD = 900 K.
- 55% usan Postgres específicamente (alineado a Stack Overflow 2025 + observación de stacks dominantes en LATAM: Node/Postgres en fintech mexicana, Spring/Postgres en bancos brasileños) = **495 K developers backend LATAM con Postgres**.
- 20% willingness-to-pay (benchmark conservador de developer tools en mercados emergentes; 15-25% rango) = 99 K developers potencialmente pagantes.
- × $29 USD/mes × 12 meses = **SAM = $34 M USD ARR**.

**Fuentes.** Statista: Latin America Number of Software Developers 2023. Alcor: LATAM Developers Portrait & Salaries 2025 (Brasil 759 K, México 563 K). Next Idea Tech 2025.

### 7.3 SOM

**Definición a 4 años.** Lo que PgPilot puede capturar entre mayo 2026 y mayo 2030, dado un equipo fundador pequeño y crecimiento por content + founder-led sales.

**Supuestos de penetración.** El backlog F12 sugiere 1-5% del SAM en 3-5 años. Elegimos la cota media:

- **SOM bajo (1%, 3 años):** $340 K USD ARR ≈ 970 developers Pro ≈ 25-40 cuentas Team.
- **SOM medio (2.5%, 4 años):** $850 K USD ARR ≈ 2,400 developers Pro ≈ 60-100 cuentas Team. **← elegido como narrativa.**
- **SOM alto (5%, 5 años):** $1.7 M USD ARR ≈ 4,900 developers ≈ 120-200 cuentas Team.

**Por qué $850 K es el SOM elegido.** Cubre el runway de un equipo fundador de 3-4 personas con salarios LATAM senior ($60-80 K USD/año c/u), gastos operativos cloud (~$50 K/año), y margen para reinvertir en producto. Viable como bootstrapped a partir del año 2, sin requerir ronda VC.

### 7.4 Tendencias relevantes

Por qué el mercado es atractivo **AHORA**:

- **Postgres ganando share aceleradamente** — 55.6% adopción developer 2025 (Stack Overflow), desde 45% en 2022. Serverless Postgres CAGR 27.8%.
- **Presión de costos cloud** — AWS RDS / Aurora subieron precio 2024-2025; empresas LATAM con presupuesto en pesos optimizan para defender margen.
- **Regulación de datos endureciéndose** — LGPD Brasil, LFPDPPP México (actualización 2026), Colombia, Argentina. Sanitizar por diseño pasa de buena práctica a obligación legal.

---

## 8. Go-to-market

> Plan completo, costos y timeline en `business/gtm.md` (F13). Aquí se resume.

### 8.1 Primeros 10 clientes

**Estrategia general.** Founder-led sales + content-driven inbound. No performance marketing, no LinkedIn outreach masivo, no pitch a VC antes de tracción. El ICP es un backend senior LATAM que confía en otros developers, no en publicidad.

**Plan paso a paso (mes 0 = mayo 2026, Demo Day como kickoff comercial):**

| Mes | Hito | Clientes acum. | ARR acum. estimado |
|---|---|---|---|
| 0-1 | Show HN + 15 artículos Dev.to (uno por anti-pattern) + landing con Stripe + Cal.com | 0-1 | $0-2 K |
| 2-3 | Founder-led outreach a 50 CTOs/tech leads LATAM en LinkedIn con mensaje personal (no plantillas), 2-3 pilotos 90 días firmados | 1-2 | $5-10 K |
| 4-5 | **Nerdearla 2026 Buenos Aires** (~15K asistentes, ICP LATAM): sponsor Bronze + 30 demos + intento de charla | 1-2 (sin convertir aún) | $5-10 K |
| 6 | Conversión de pilotos del mes 2-3 (target 3 de 5 convierten a Team) | 4-5 | $25-35 K |
| 7-9 | **Finnosummit MX / Fintech Week** (fintech LATAM, encaje fuerte por privacidad): sponsor + demos + 1 charla intentada | 5-7 | $35-50 K |
| 10-12 | Cierre de pilotos eventos + caso de estudio público con primer cliente (descuento 30% permanente a cambio de permitirlo) | **10** | **$60-100 K** |

**Costo total del plan: ~$15,000 USD** (Stripe + Cal + landing + LinkedIn Premium + 2 sponsors de eventos + viaje + diseño + Claude API durante pilotos gratis + hosting). **CAC blended ≈ $1,500/cliente.** LTV Team a 3 años retención ≈ $26 K. **LTV/CAC ≈ 17×** (sano para SaaS B2B).

**Por qué este plan funciona.** El catálogo de patterns abierto en `/docs/patterns/` acumula SEO con cada artículo. Cada anti-pattern publicado en Dev.to en español es un artículo que rankea para "anti patrón Postgres seq scan", "índice cubriente Postgres", etc. — términos que un dev LATAM busca cuando ya tiene el problema. Los eventos generan demos cualificadas, los pilotos convierten 3 de 5, y el primer caso de estudio se vuelve el activo de marketing #1 para el año 2.

### 8.2 Estrategia de growth (después de los 10)

Con 10 clientes y ~$80 K ARR (cierre mes 12): **(1)** inbound dominante (catálogo SEO + casos de estudio + referidos); **(2)** primer hire AE LATAM mes 13 con quota $200 K ARR, salario $25-30 K + comisión; **(3)** partner program con consultoras LATAM (margen 25%); **(4)** expansión a España (mismo idioma, NO US todavía — competiría con pganalyze). **Meta año 2:** 50 clientes, $350 K ARR → SOM medio $850 K en año 4.

---

## 9. Diferenciador defendible

> La pregunta de oro: si el competidor más fuerte les copia el feature mañana, ¿por qué los clientes seguirían con ustedes? Análisis completo en `business/diferenciador.md` (F14).

**El competidor verdadero no es pganalyze, es ChatGPT genérico gratis.** Esa es la baseline real del developer que evalúa el producto.

**Nuestro diferenciador es: la integridad arquitectónica de cuatro defensores combinados.**

| # | Defensor | Por qué es difícil de copiar |
|---|---|---|
| **1** | **Motor determinístico que decide, LLM que solo explica.** Las decisiones de detección viven en código Python testeable (`/motor/detectors/`). El LLM se invoca **después** de que el motor ya decidió, y solo para prosa pedagógica. Si el LLM contradice al motor, gana el motor (regla R1 del proyecto). | Cambiar a este shape requiere reescribir la pipeline central de un competidor que hoy delega decisión al LLM (EverSQL). 6-12 meses de proyecto para una empresa establecida. Una vez que entrenaste a tus clientes en "la herramienta puede alucinar", revertir esa percepción cuesta más que rehacer el producto. |
| **2** | **Sanitización fuerte de literales antes del LLM.** `ia/sanitizer.py` reemplaza strings, números, fechas, UUIDs y emails con placeholders **antes** de cualquier llamada al LLM. Tests B11 verifican con `grep` que ningún dato sensible aparece. | Implementarlo serio requiere parser SQL (`sqlglot`), no regex, y mantenerlo por versión de Postgres. Más importante: ChatGPT y Cursor mandan todo el contexto a su proveedor. Para empresas con LGPD/LFPDPPP/HIPAA, esa diferencia es bloqueador legal. PgPilot ofrece un camino auditable: el sanitizer es código del producto, no una promesa de proveedor. |
| **3** | **Validación en sandbox efímero antes de mostrar.** Cada recomendación pasa por un segundo Postgres efímero donde se aplica el `CREATE INDEX` propuesto y se compara `EXPLAIN` antes/después. Si el planner no usa el índice o el costo no baja, la recomendación se descarta. R6 prohíbe copiar datos: el sandbox monta schema con stats falseadas. | pganalyze tiene "What If?" pero corre en producción del cliente. Falsear stats sin copiar datos es una decisión arquitectónica fuerte. ChatGPT no puede validar nada — su output es texto. Esa es la diferencia entre "sugerencia plausible" y "sugerencia verificada". |
| **4** | **Modo offline / bundle JSON.** El módulo `/conector` opera contra un bundle JSON exportado por el cliente sin conexión a la BD productiva. Nunca tocamos su BD en ese modo. | Requiere desacoplar el motor del extractor de stats — si el competidor diseñó su producto asumiendo "siempre hay una conexión viva", refactorizar es trabajo de meses. Es argumento de venta literal: fintech mexicana mediana no firma SOC2 con un SaaS extranjero que pide credenciales de su Postgres productivo. |

**Defensor comercial transversal (foco LATAM).** No es arquitectónico — es de posicionamiento — pero es real:

- Producto, docs, catálogo de patterns, soporte y onboarding **en español**. pganalyze tiene 0 contenido en español.
- Soporte en **horario hábil LATAM** (CST/CDT/BRT). pganalyze responde en EST/PST con delay 12-24 h.
- Founders entienden el ciclo de procurement de una fintech mexicana, los topes de presupuesto, las restricciones cambiarias y los stacks dominantes (Node + Postgres / Spring + Postgres).
- Network en comunidades LATAM (Postgres MX, Devs México, FrontendCafé) que una sales motion fría desde San Francisco no compite.

**Trade-off honesto.** El foco LATAM se erosiona si pganalyze decide entrar a LATAM en serio (contratar Country Manager LATAM en 2027 podría replicar idioma + horario en 6 meses). Cuando eso pase, la defensa baja a los cuatro arquitectónicos — que es lo que se diseñó para resistir esa presión.

**Por qué la combinación es la defensa, no las piezas.** Ninguno de los cuatro defensores es único de PgPilot por separado. Lo único difícil es **combinar los cuatro con la misma integridad arquitectónica**, porque cada uno restringe el diseño de los otros (sanitización fuerte empuja al motor determinístico; motor determinístico empuja al sandbox; sandbox sin copiar datos empuja al modo offline). Replicar una pieza es fácil; replicar el sistema entero exige rehacer el producto, y un competidor establecido prefiere no romper su producto que ya funciona.

---

## 10. Por qué nuestro equipo

Equipo de 6 estudiantes de Ingeniería en Sistemas Computacionales, Universidad Anáhuac Querétaro, materia SIS2404 — Bases de Datos Avanzadas. Construimos PgPilot durante un semestre con metodología disciplinada: motor determinístico revisado por humanos, capa de IA encapsulada con guardrails (sanitización + cross-validation + fallback a plantillas), decisiones de arquitectura tomadas por el equipo con bitácora versionada en `docs/decisiones.md` y `PROGRESS.md`.

**Integrantes y reparto técnico real** (basado en autores de los commits en `git shortlog -sn`):

| Integrante | Matrícula | Área principal | Componentes implementados |
|---|---|---|---|
| Andrés Angulo | 00508857 | Backend + orquestador + infraestructura | Repo y estructura, Docker Compose (AppDB :5434 + sandbox :5435), pool read-only con timeout, extractor de schema vía `pg_catalog` y de tamaños de tabla con categorización, parser EXPLAIN JSON con `PlanNode` (16+ tipos de nodo), helper `find_nodes` (DFS pre-order), detectores **D2 (Nested Loop con outer grande), D9 (SELECT *), D20 (índice cubriente) y D22 (count(*) sin WHERE)**, recomendador con filtro de selectividad (umbral 20%), validador en sandbox por cambio de tipo de nodo (Seq Scan → Index Scan), scaffold frontend (Vite + React + Monaco), backend FastAPI `/analyze`, wiring backend↔frontend (B14), scripts de medición empírica de cobertura. |
| Alexander Riggs | 00509910 | Conector + sandbox + negocio | Extractor de stats por columna (`pg_stats` con `n_distinct`, `null_frac`, `most_common_vals`, `correlation`), cache de metadata con fingerprint MD5 y detección de drift por content hash, modo offline con bundle JSON portable (`export_bundle`/`load_bundle`/`validate_bundle`), sandbox Postgres efímero con `pg_restore_relation_stats` (PG18+), pool de sandbox separado, orquestación `explain_in_sandbox` con cleanup `try/finally`. Investigación competitiva (F3, 4 competidores), modelo de pricing per-seat 4 tiers (F11), TAM/SAM/SOM con metodología razonada (F12, $800M / $34M / $850K), plan go-to-market founder-led + content-driven (F13, Show HN + Nerdearla + Finnosummit), **diferenciador defendible (F14) con marco "el competidor real es ChatGPT"**, documento de negocio consolidado (F15, .docx preservando plantilla del profesor). |
| Diego Núñez | 00516279 | Detectores estructurales + workload | Detectores D3 (LIKE wildcard inicio), D4 (función no-immutable), D5 (OR cruzando tablas), D7 (subquery correlacionada). Parser `pg_stat_statements` con heurística JSON/CSV, scoring por `total_exec_time`, endpoint `POST /workload` con multipart, tab "Workload Analysis" en frontend, cleanup de schemas zombies, timeouts duros en sandbox, fix del orquestador `/analyze` para que los 18 detectores corran. Lista de candidatos a entrevistar (F4) y guion de 9 preguntas (F5). |
| Regina Valenzuela | 00508321 | Capa IA (sanitización) + detectores índices | Sanitizador de literales con 5 tipos de placeholders ($LITERAL_<tipo>_<i>), test de privacidad con `grep` externo (email + RFC + tarjeta de prueba). Detectores D16 (índice faltante, el más rentable: 7 queries), D11 (índice parcial bool), D17 (cardinalidad JOIN → `CREATE STATISTICS`), D19 (`NOT IN` nullable → bug silencioso). Refactor `motor/detectors/_common.py`. README bilingüe del repo (macOS + WSL2 + Windows con troubleshooting). Documento de arquitectura consolidado. User persona Andrés Villanueva (F10). |
| Emilio Tolosa | 00520630 | Documentación externa + validación en frontend | Docs externas de `/conector` (garantías read-only contractuales), `/motor` (pipeline + tabla de los 19 detectores con confianzas verificadas), `/ia` (system-prompt + Pydantic + cruz-validador + modo "LLM apagado", crítica para Q&A), `/sandbox` (R6 "no se copian datos" + tabla "qué sí/qué no se falsea"). Indicadores de validación R3 en frontend (helper `_compute_validations` + componente `ValidationIndicators` con 4 píldoras: schema_ok, no_duplicate_index, syntax_valid, sandbox_improves). Auditoría final del catálogo de 19 patterns. Índice maestro `docs/README.md`. |
| David Ramírez | 00492597 | Detectores SQL + capa de validación IA | Detectores D12 (cast implícito que invalida btree), D14 (CTE materializada innecesaria), D18 (HAVING → WHERE), D8 (IN → EXISTS dual plan+SQL). Capa `/ia`: validador Pydantic con reintentos (rechazo de JSON malformado, `explanation` vacío, `confidence` fuera de rango), cross-validator de identificadores contra schema (descarta índice duplicado, columna inexistente, SQL no parseable), plantillas determinísticas con confianza ajustable por selectividad, orquestador `explain_recommendation` con fallback a plantilla ante cualquier excepción del LLM (garantiza R5). |

**Por qué este equipo es el adecuado:** (1) **conocemos el mercado** — developers LATAM en formación; el persona Andrés Villanueva es una versión adulta de nosotros; (2) **disciplina arquitectónica demostrada** — la regla R1 ("motor decide, LLM explica, sandbox valida") está codificada en `RULES.md` y verificada en tests automatizados, no es slide de pitch; (3) **honestidad declarada** — el documento marca explícitamente qué hipótesis siguen abiertas tras las 3 entrevistas; (4) **bitácora versionada** — 3,000+ líneas de `PROGRESS.md` al cierre del semestre, trazabilidad que no se improvisa.

**Sobre el tamaño del equipo (6 personas).** La rúbrica oficial calibra para equipos de 5. Trabajamos como 6 con el conocimiento del profesor: el alumno adicional asumió las áreas de documentación externa y validación en frontend que de otro modo habrían quedado descubiertas. El reparto arriba demuestra contribuciones independientes y simétricas — no hay polizones; cada miembro defiende componentes específicos en el Q&A.

---

## 11. Roadmap a 12 meses

Si el proyecto continúa post-Demo Day como producto comercial:

- **Q1 (may-jul 2026):** GitHub Action CI + primer paso del monitor de degradación + cobertura AppDB v2 + landing con Stripe + Cal.com. Show HN, 15 artículos Dev.to, 50 outreach LATAM. Setup legal y staging.
- **Q2 (ago-oct 2026):** SSO básico + RBAC + detectores extra + workload export. **Nerdearla 2026** sponsor. 3-5 pilotos activos, primer cliente pagando. Decisión: continuar comercial o cerrar académico.
- **Q3 (nov 2026 - ene 2027):** Modo offline production-ready, SAML empresarial, audit logs, detectores custom Enterprise. **Finnosummit / Fintech Week MX**. Primer Enterprise + caso de estudio público. Primer hire AE LATAM si pipeline lo justifica.
- **Q4 (feb-may 2027):** PG17/18 compat verificada, coverage >70%. Cierre con 10 clientes pagando, $60-100 K USD ARR. AE LATAM con quota.

**Visión 1 año (2027):** 10 clientes LATAM, $60-100 K ARR, primer hire de sales, bootstrapped sin VC. **Visión 4 años (2030):** SOM medio $850 K ARR, 60-100 cuentas Team, expansión a España, partner program con 3-5 consultoras.

---

## 12. Ask

**Académico (Demo Day, 14-may-2026):** validación del modelo de detección y guardrails frente al jurado y equipos rivales (PgGuardian, PgVault) — defensas a "¿cómo evitan alucinaciones?", "¿qué pasa si su LLM se cae?", "¿por qué pagar vs ChatGPT?" en `business/qa-prep.md` (F19) y verificables en código (R1, R3, R4, R6, R7). Crédito justo por la disciplina arquitectónica codificada y testeada.

**Comercial (post-Demo, si el equipo decide continuar):** introducciones a 5-10 CTOs/tech leads LATAM en fintech, healthtech y SaaS B2B para pilotos gratuitos de 90 días (profesores de la materia, ex-alumnos en industria, programa de Innovación y Emprendimiento Anáhuac); mentoría en founder-led-sales LATAM (ciclo de procurement mexicano, eventos que sí valen sponsor); espacio de validación verano 2026 para el plan Q1 (Show HN + outreach + primer pilot) antes de la decisión definitiva del equipo.

---

## Referencias internas

- **Catálogo de detección:** `docs/patterns/` (19 anti-patterns, uno por archivo `.md`).
- **Arquitectura técnica:** `docs/arquitectura.md` (F2).
- **Reglas inviolables:** `RULES.md` raíz.
- **Bitácora del proyecto:** `PROGRESS.md` (3,000+ líneas).
- **Investigación competitiva:** `business/competencia.md` (F3).
- **Modelo de pricing:** `business/pricing.md` (F11).
- **Análisis de mercado (TAM/SAM/SOM):** `business/mercado.md` (F12).
- **Plan go-to-market:** `business/gtm.md` (F13).
- **Diferenciador defendible:** `business/diferenciador.md` (F14).
- **Guion de entrevistas:** `business/guion-entrevistas.md` (F5).
- **Lista de candidatos a entrevistar:** `business/lista-entrevistados.md` (F4).
- **Entrevistas ejecutadas (3 de 3):** `business/entrevista-1.md` (F6 — Carlos Orellán, DBA), `business/entrevista-2.md` (F7 — Jos Lugo, ingeniero fullstack), `business/entrevista-3.md` (F8 — Raúl Zavaleta, desarrollador fullstack).

---

## Fuentes citadas

### Mercado
- Gartner — Forecast Database Management Systems Worldwide 2023-2029 (2025 Update). DBMS $137 B en 2025, $161 B en 2026.
- Percona — *PostgreSQL's Proprietary Future? Key Market Trends in 2025*.
- Yugabyte — *Why PostgreSQL Remains the Top Choice for Developers in 2025*. Adopción 55.6%.
- Research and Markets — *Serverless PostgreSQL Market Report 2026*. CAGR 27.8%.
- Mordor Intelligence / Grand View Research — Database Performance Management market estimates.

### Developers LATAM
- Alcor — *LATAM Developers Portrait & Salaries 2025*. Brasil 759 K, México 563 K (cifras conservadoras).
- Statista — *Latin America Number of Software Developers 2023*.
- Next Idea Tech — *How Many Software Developers in Latin America*.
- Howdy.com — *2025 Latin America Software Developer Salaries* (cifras agresivas, usadas como cota alta).

### Competencia
- pganalyze — <https://pganalyze.com> y <https://pganalyze.com/pricing>.
- EverSQL (Aiven) — <https://www.eversql.com>.
- DBtune — <https://www.dbtune.com> y <https://docs.dbtune.com/aws-rds/>.
- pgMustard — <https://www.pgmustard.com> y <https://www.pgmustard.com/pricing>.
- Datadog Database Monitoring — <https://www.datadoghq.com/product/database-monitoring/>.

### Pricing benchmark (developer tools per-seat)
- Cursor — <https://www.cursor.com/pricing>. Pro $20/mes, Business $40/mes/seat. $2 B ARR en feb 2026.
- GitHub Copilot — <https://github.com/features/copilot/plans>. Individual $10, Business $19, Enterprise $39.
- Linear — <https://linear.app/pricing>. Desde $8/usuario/mes.

### Eventos LATAM (go-to-market)
- Nerdearla Buenos Aires — <https://nerdearla.com/en/> y <https://dev.events/conferences/nerdearla-2025-buenos-aires-kx86j6gh>.
- Mexico Fintech Week — <https://www.mexicofintechweek.com>.
- Finnosummit CDMX — <https://globalconference.ca/top-technology-conferences-in-mexico/>.

---

> **Nota de mantenimiento:** este archivo y `business/negocio.docx` deben contener la misma información. **El `.docx` quedó desincronizado tras la actualización del 2026-05-13 que integró F7+F8** (cabecera, §2.3, §3.1 tabla de 3 entrevistas, §3.3 9 insights consolidados, §6.3 validación de pricing por Raúl, §11 roadmap y referencias internas). Regenerar `negocio.docx` antes de la entrega final del Demo Day. Si los pilotos post-Demo Day cambian materialmente alguna hipótesis (rango de precio, persona, hallazgo central), agregar entrada en `PROGRESS.md` explicando qué cambió y por qué.

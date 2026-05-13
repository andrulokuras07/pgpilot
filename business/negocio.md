# PgPilot — Documento de Negocio

> Plantilla 3 de 3 (Entregables Oficiales del Proyecto Final). Consolida F3 (competencia), F6 (entrevista 1 — Carlos Orellán), F9 (problema), F10 (persona — Andrés Villanueva), F11 (pricing), F12 (mercado), F13 (go-to-market) y F14 (diferenciador) en un solo documento de evaluación.
>
> Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026.
>
> **Nota al evaluador:** F6 (1 de 3 entrevistas) ya está documentada en `business/entrevista-1.md` y sus hallazgos se integraron a §2.2 (persona), §2.3 (frecuencia/severidad), §3.1 (resumen entrevistas) y §3.3 (aprendizajes). F7 y F8 (entrevistas 2 y 3) siguen en agendamiento; cuando aterricen se actualizará §3.1 con sus filas correspondientes y se expandirá §3.3 con los hallazgos nuevos. La sección §10 (equipo) lleva un único `[PENDIENTE: COMPLETAR DATOS DEL EQUIPO]` para nombres / matrículas / reparto técnico exacto antes de la entrega final.

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

**Problema.** Cuando una query Postgres se vuelve lenta en producción, el developer que la escribió rara vez tiene un DBA al lado para diagnosticarla. Las opciones actuales fallan en distintos ejes: pegarle el SQL a ChatGPT viola compliance en sectores regulados (fintech, healthtech, govtech LATAM) y produce alucinaciones de índices y columnas; pganalyze cuesta $149-$399 USD/mes/servidor y excluye a equipos pequeños; pgMustard es manual de un plan a la vez; EverSQL encierra al cliente en el ecosistema Aiven. El resultado: el dev pierde horas leyendo `EXPLAIN ANALYZE` a mano, o aplica recomendaciones plausibles pero sin validar.

**Solución.** PgPilot analiza queries Postgres combinando un **motor determinístico** (Python puro, 19 detectores de anti-patterns con reglas auditables) que decide qué problema existe y qué índice o rewrite recomendar, con una **capa LLM** (Claude Sonnet) que solo explica pedagógicamente lo que el motor ya decidió. Toda recomendación se **valida en un sandbox Postgres efímero** antes de mostrarse al usuario — si el planner no usa el índice o el costo no baja, la sugerencia se descarta. Los literales del SQL se **sanitizan antes** de cualquier llamada al LLM. Modo offline disponible vía bundle JSON: el cliente nunca conecta su BD productiva a un SaaS externo.

**Mercado.** TAM global de herramientas de optimización Postgres: **$800 M USD ARR** (recorte sobre el mercado DBMS global de $137 B reportado por Gartner 2025, aplicando 15-20% Postgres y 2-5% subcategoría performance/optimization). SAM LATAM (~495 K developers backend con Postgres, willingness-to-pay 20%): **$34 M USD ARR**. SOM medio a 4 años (2.5% del SAM): **$850 K USD ARR**.

**Modelo.** Per-seat (alineado a Cursor / GitHub Copilot, no per-server de pganalyze). Cuatro tiers: Free ($0), Pro ($29 USD/dev/mes), Team ($49/dev/mes mínimo 3 devs), Enterprise (desde $99/dev/mes con piso $5 K USD/año por organización). Margen bruto Pro estimado ≈ 97% al uso promedio hipotético de 30 análisis/mes.

**Diferenciador.** Cuatro defensores arquitectónicos combinados que un competidor establecido no puede replicar en 90 días sin rehacer su producto: motor determinístico que decide + sanitización fuerte pre-LLM + validación en sandbox + modo offline. A esto se suma foco LATAM (idioma, horario, network) como defensa comercial transversal. La defensa real es la **integridad arquitectónica** del sistema completo, no una pieza individual.

**Equipo.** 5 estudiantes de Ingeniería en Sistemas Computacionales, Universidad Anáhuac Querétaro, con experiencia repartida en backend Python, frontend React, infra Docker y bases de datos. El producto se construyó durante un semestre con metodología disciplinada (motor determinístico revisado por humanos, capa de IA encapsulada con guardrails) — el mismo método que permite venderlo como producto controlado.

**Ask.** En contexto académico (Demo Day 14 de mayo 2026): validación del modelo de detección y de los guardrails frente a evaluadores y equipos rivales. En contexto comercial (post-Demo): introducciones a 5-10 CTOs/tech leads LATAM en fintech/healthtech/SaaS para los primeros pilotos gratuitos de 90 días, y mentoría en la motion founder-led-sales para LATAM.

---

## 2. Problema

### 2.1 Descripción del problema

Cuando un developer backend escribe una query nueva contra Postgres, no tiene cómo saber con certeza si será lenta en producción **hasta que producción la pruebe**. Los síntomas aparecen tarde: alertas de p95 latencia, queja de un cliente, un timeout en una corrida nocturna. Para entonces el dev abre `EXPLAIN ANALYZE`, intenta leer un árbol de nodos que mezcla Seq Scan, Nested Loop, Hash Join y costos estimados vs reales, y compara mentalmente contra los índices que recuerda haber creado meses atrás.

Si la empresa no tiene DBA dedicado — que es el caso de la mayoría de equipos LATAM medianos (5-50 devs) — el dev hace una de tres cosas, todas malas:

1. **Pegarle la query a ChatGPT.** Funciona a veces pero alucina índices que no existen, columnas que renombraron, sintaxis de versiones viejas. Más importante: **manda datos productivos a un tercero** sin auditoría, lo cual viola la regla básica de compliance en cualquier empresa con datos personales (LGPD en Brasil, LFPDPPP en México, GDPR si tiene operación europea).
2. **Comprar pganalyze o equivalente.** $149-$399 USD/mes/servidor es prohibitivo para una startup LATAM con presupuesto en pesos. Una fintech mexicana mediana con 5 servidores Postgres pagaría $7.5 K USD/año mínimo — un costo que requiere aprobación de procurement y compite con hires.
3. **Resolverlo a mano.** El dev senior dedica 2-8 horas por incidente leyendo el plan, probando hipótesis de índices, esperando que `ANALYZE` corra. El dev junior copia stack overflow y reza.

El problema no es de capacidad técnica del dev. Es de **falta de herramienta intermedia**: algo más confiable que un LLM genérico, más barato que un SaaS enterprise, y que respete las restricciones de privacidad reales de los sectores regulados de LATAM.

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

**Datos primarios (entrevista F6 Carlos Orellán + persona F10 Andrés Villanueva + F9 análisis):**

- **Frecuencia de optimización reactiva (Carlos, DBA, BDs ~30 GB c/u):** 30 min a 1 hora al mes. Actúan por eventos, no proactivamente. Validación parcial: equipos chicos con menor volumen tienen menos incidentes detectados pero también menos visibilidad de los problemas latentes.
- **Frecuencia de incidentes mayores (Andrés, Tech Lead, BD principal ~180 GB):** 1.5-3 horas-developer por incidente, ≥1 incidente cada 2 semanas. En cierres de quincena (carga × 10) los incidentes se multiplican. El ciclo manual completo de un mes promedio ≈ 4-8 horas-developer.
- **Anti-pattern real reportado (Carlos, F6 pregunta 5):** `SELECT *` sobre tablas con BLOBs causó queries lentas detectadas en pruebas; resolución manual columna por columna. Ese anti-pattern es exactamente D9 (`select_star`) del catálogo PgPilot — validación directa del valor del producto.

**Severidad:**

- **Por incidente menor (query lenta detectada en staging o early prod):** 2-8 horas-developer para diagnosticar + corregir + revisar PR. A salario LATAM senior ($25-50 USD/h, Glassdoor / Levels.fyi ajustado LATAM, citado en F9), eso es $50-400 USD por incidente. Con 1-2 incidentes/mes ≈ **$50-800 USD/mes en horas perdidas** según tamaño de BD y equipo.
- **Por incidente mayor (afecta clientes o métricas de negocio):** además de las horas técnicas, hay costo de oportunidad (transacciones fallidas, churn, contacto cliente). Gartner cost-of-downtime benchmarks (citados en F9 §5) sitúan un incidente de producción por query lenta entre **$500 y $5,000 USD** dependiendo del volumen transaccional. Para Andrés (cierre de quincena con × 10 de carga) el extremo alto del rango es realista.
- **Costo invisible:** Andrés improvisa el rol de DBA sin que sea su responsabilidad formal. La feature siguiente se atrasa una semana cada vez que hay un incidente. El CTO percibe el problema como "rendimiento" pero no ve que viene de la ausencia de proceso, no de un dev mediocre.

**ROI estimado (F9 §5):** equipo de 5 devs en tier Pro = $145 USD/mes. Si PgPilot ahorra 2 horas/mes de diagnóstico ($50-100 USD) **+** previene 1 incidente/trimestre ($500+ USD), el ROI es positivo desde el primer trimestre.

> Pendiente: F7 y F8 (entrevistas 2 y 3) ampliarán estos rangos con perfiles de equipos más grandes y/o sectores adyacentes. F15 se actualizará cuando aterricen.

---

## 3. Investigación de usuarios

> **Requisito obligatorio de la plantilla:** mínimo 3 entrevistas con personas del rol objetivo. Si no se hacen, este criterio se va a 0.

### 3.1 Resumen de entrevistas

F6 completada (1 de 3); F7 y F8 en agendamiento al cierre de este documento. Lista completa de candidatos y criterios de selección en `business/lista-entrevistados.md` (F4); transcripción y respuestas detalladas en `business/entrevista-1.md`.

| Nombre / Rol del entrevistado | Empresa / Sector | Fecha | Duración |
|---|---|---|---|
| Carlos Orellán — DBA | Software house LATAM (3 BDs Postgres, migración a ~30 GB c/u) | 13 de mayo de 2026 | ~10 min (videollamada grabada) |
| [PENDIENTE: F7] — perfil objetivo: Tech lead / Backend senior con Postgres ≥100 GB | [PENDIENTE: en agendamiento] | [PENDIENTE] | 25-30 min |
| [PENDIENTE: F8] — perfil objetivo: CTO o Engineering Manager LATAM | [PENDIENTE: en agendamiento] | [PENDIENTE] | 25-30 min |

### 3.2 Preguntas hechas

Las 9 preguntas del guion (F5, ver `business/guion-entrevistas.md` para texto completo y objetivo de cada una):

1. **Contexto.** ¿Cuántas bases de datos Postgres manejas en producción y cuál es el tamaño aproximado de la más grande?
2. **Comportamiento actual.** Cuando te llega una queja de "la app está lenta", ¿cuáles son los primeros 3 pasos que das para diagnosticar si es un problema de queries?
3. **Stack actual.** ¿Qué herramientas usas hoy para analizar queries lentas? (`pg_stat_statements`, `EXPLAIN ANALYZE` manual, pgBadger, algún SaaS tipo Datadog/pganalyze...)
4. **Dolor cuantificado.** ¿Cuánto tiempo al mes estimas que le dedicas a optimizar queries o investigar problemas de rendimiento en Postgres?
5. **Historia concreta.** ¿Puedes contarme un caso reciente donde una query lenta causó un problema real en producción? ¿Cómo lo resolviste y cuánto tardaste?
6. **Encaje en workflow.** Si existiera una herramienta que analiza automáticamente tus queries y te da el SQL corregido listo para copiar, ¿en qué parte de tu flujo de trabajo la usarías?
7. **Objeciones de seguridad.** ¿Qué te preocuparía de darle acceso a una herramienta así a tu base de datos de producción? ¿Qué garantías necesitarías?
8. **Oportunidad de integración.** ¿Tu equipo tiene algún proceso formal de code review para queries o migraciones antes de que lleguen a producción?
9. **Decisor y precio.** Si esta herramienta costara entre $50 y $200 USD/mes por base de datos, ¿quién en tu empresa tomaría la decisión de compra?

El guion enfatiza **comportamiento pasado**, no intenciones futuras ("no preguntar ¿usarías nuestro producto?" — la gente miente para no decepcionar).

### 3.3 Aprendizajes principales

7 insights concretos de la entrevista con Carlos Orellán (F6) cruzados contra el persona F10 (Andrés Villanueva). Marcamos cuáles **validan** hipótesis previas, cuáles las **falsan**, y cuáles **abren oportunidad nueva** para producto, pricing o GTM:

1. **El dolor existe pero es reactivo, no proactivo.** ✅ Validado. Carlos: "actuamos por eventos, cuando alguien reporta algo." Andrés vive lo mismo a mayor escala. Implicación para producto: PgPilot no compite con el flujo "no hay problema, no actuamos" — compite por el ciclo reactivo cuando ya hay un incidente. Punto de inserción ideal: el momento en que llega la alerta.

2. **SELECT * es un anti-pattern real que ya les ha dolido.** ✅ Validado. Carlos resolvió un caso en producción reemplazando `SELECT *` por columnas específicas. Ese anti-pattern es exactamente el detector D9 (`select_star`) del catálogo PgPilot — el producto detecta hoy un dolor real reportado. Implicación: usar ese caso como demo concreta en el pitch.

3. **CI/CD y el linter de SQL son el punto de entrada ideal.** ✅ Validado. Carlos mencionó **dos veces** la integración como linter en el pull request y como parte del CI con Liquibase. Esto **valida la hipótesis 5** previa (code review pre-merge > análisis reactivo) y **abre oportunidad nueva de producto**: GitHub Action / GitLab CI integration en roadmap Q2 2026-2027.

4. **Read-only es innegociable.** ✅ Validado fuertemente. La preocupación #1 de Carlos es que la herramienta tenga privilegios de escritura. PgPilot ya cumple esto por diseño (R7 read-only forzado en `conector`). Implicación para messaging: poner "read-only por diseño" como bullet #1 en la landing, no como tercer beneficio. Andrés (F10 §"Criterios de compra") confirma el mismo bloqueador.

5. **El decisor de compra es el CTO, no el dev.** ✅ Validado. Carlos: "normalmente es el CTO". Implicación crítica para GTM: el outreach mes 2-3 del plan F13 debe priorizar **CTOs y tech leads**, no developers individuales. El tier Pro es el caballo de Troya (un dev lo paga de su bolsillo, demuestra valor internamente), pero el verdadero ARR escala vía Team/Enterprise con el CTO como comprador.

6. **No usan herramientas especializadas de Postgres.** ✅ Validado. Carlos usa Rapid7 + CloudWatch + EXPLAIN manual. Andrés usa Datadog + psql + ChatGPT. **Ninguno usa pganalyze, EverSQL ni DBtune.** Implicación: PgPilot **no compite con pganalyze en el mercado LATAM** — los devs LATAM aún no son clientes de pganalyze. Compite con "no hacer nada" o con "hacerlo a mano" — un baseline más fácil de superar.

7. **Privacidad de datos productivos es bloqueador legal, no preocupación técnica.** ✅ Validado (especialmente en Andrés F10): "Sé que hay herramientas buenas pero no puedo darles acceso a producción. Legalmente no puedo." En fintech B2B con datos de nómina (RFC, CURP, salarios), el área legal bloquea cualquier herramienta sin sanitización fuerte o modo offline. Implicación: el modo offline (bundle JSON) no es un nice-to-have, es **el feature que abre la puerta del sector regulado LATAM**.

**Hipótesis pendientes (a validar en F7 y F8):**

- 🟡 **Willingness-to-pay específico $29 USD/dev/mes en LATAM.** Carlos no expresó objeción al rango $50-200/BD pero no se le preguntó por precio per-dev exacto. F7/F8 deben preguntar específicamente por el rango Pro y por el dis-/in-comformidad a $29.
- 🟡 **Hipótesis "el dolor crece con el tamaño de la BD".** Carlos está en migración (pocos MB → 30 GB), Andrés ya está a 180 GB. F7/F8 idealmente cubren un perfil de equipo en escala mayor (≥500 GB) para confirmar la curva.
- 🟡 **¿Los equipos adoptarían PgPilot sin LLM (modo offline)?** No se preguntó a Carlos directamente. F7 debe incluir esta pregunta para validar la utilidad del modo plantillas (R5).

**Cambios al producto/pricing/GTM derivados de F6 + F10 (decisiones provisionales, sujetas a F7/F8):**

- **Producto:** priorizar GitHub Action / GitLab CI integration en Q2 (insight #3).
- **Pricing:** mantener tier Pro $29 hasta tener señal contraria en F7/F8 (sin objeción explícita en F6).
- **GTM:** redirigir outreach mes 2-3 del plan F13 a CTOs/tech leads en vez de developers individuales (insight #5). El tier Pro se distribuye bottom-up; el tier Team/Enterprise se vende top-down al CTO.
- **Messaging:** elevar "read-only por diseño" y "modo offline para sectores regulados" a los bullets #1 y #2 de la landing (insights #4 y #7).

---

## 4. Solución

PgPilot se ve así desde el lado del usuario:

El developer abre el editor web de PgPilot (interfaz tipo VS Code, tema oscuro, en español). Pega una query SQL que cree problemática — por ejemplo, una que aparece en su `pg_stat_statements` con tiempo total alto. Pulsa "Analizar". En 2-4 segundos aparecen tarjetas con detecciones:

> *"Detectamos un Seq Scan sobre la tabla `posts` (12.3 M filas) con filtro `WHERE author_id = $1`. La tabla no tiene índice en `author_id`, lo que fuerza al planner a leer toda la tabla. Recomendamos `CREATE INDEX idx_posts_author_id ON posts(author_id);`. Validado en sandbox: costo estimado baja de 45,231 a 287 (158× mejora). Confianza: alta."*

Debajo, un comparativo before/after del plan de EXPLAIN con costos resaltados. El dev puede copiar el SQL con un clic, llevarlo a su PR, mergear con tranquilidad. Si el LLM está habilitado (tier Pro+), una explicación adicional en prosa pedagógica describe **por qué** el motor identificó este patrón y **qué riesgo** evita el índice. Cuatro indicadores verdes muestran las validaciones que pasó la recomendación: schema OK, no duplica índice existente, sintaxis válida, sandbox confirma mejora.

A las 24 horas el dev ha procesado 5-10 queries de su workload y ha aplicado 2-3 índices recomendados. Su p95 baja. Su PR fue aprobado más rápido porque incluyó el plan before/after. El tech lead del equipo lo nota y agrega la URL del editor a su onboarding interno.

### 4.1 Funcionalidades core

| Feature | Beneficio para el usuario |
|---|---|
| **Editor web con análisis on-demand** | Pega query, recibe detecciones en segundos sin instalar nada local. Onboarding cero fricción. |
| **19 detectores de anti-patterns documentados** | Cobertura amplia y conocida del catálogo público (`/docs/patterns/`). El dev entiende qué se busca, no es una caja negra. |
| **Recomendación de índice con `CREATE INDEX` listo para copiar** | Productividad inmediata: del análisis al PR en minutos, no horas. |
| **Validación en sandbox antes de mostrar** | Confianza en la recomendación: no es una sugerencia plausible, es una sugerencia con costo before/after verificado. |
| **Comparativo before/after del plan EXPLAIN** | Evidencia en el PR para que el reviewer apruebe rápido y para defender la decisión en code review. |
| **Workload analysis sobre `pg_stat_statements`** | Top 10 queries por impacto (tiempo total, no frecuencia) — ataca primero lo que más duele. |
| **Sanitización fuerte de literales pre-LLM** | Compliance: ningún dato productivo sale del perímetro hacia el LLM. Auditable. |
| **Modo offline / bundle JSON** | Para fintech/healthtech LATAM: análisis sin conectar la BD productiva a ningún SaaS. |
| **Modo "LLM apagado" con plantillas** | Resiliencia: el producto funciona aunque Anthropic se caiga. Las explicaciones son más secas pero válidas. |
| **Catálogo abierto en `/docs/patterns/`** | Transparencia y SEO: cada anti-pattern es un artículo público que demuestra rigor técnico. |

**Estado al cierre del semestre (validación funcional sobre la BD demo del curso, AppDB v1):**

- 18 de 20 queries plantadas detectadas correctamente (objetivo rúbrica ≥16, superado).
- 0 falsos positivos sobre 10 queries sanas (objetivo rúbrica <3, superado).
- Modo "LLM apagado" funcional (resiliencia validada).

---

## 5. Análisis competitivo

> **Requisito obligatorio de la plantilla:** mínimo 3 competidores reales investigados. Investigación completa en `business/competencia.md` (F3). Aquí se resume y consolida.

### 5.1 Tabla comparativa

| Característica | pganalyze | EverSQL (Aiven) | DBtune | pgMustard | **PgPilot** |
|---|---|---|---|---|---|
| **Foco principal** | Monitoring continuo + advisors | Rewrite automático IA | Tuning de parámetros (ML) | Visualizador de EXPLAIN | Detección + recomendaciones validadas |
| **BD soportadas** | Postgres | Postgres, MySQL | Postgres | Postgres | Postgres |
| **Precio entrada (USD/mes)** | $149/servidor | Gratis (vía Aiven) | Trial 3 DB; comercial no público | ~$8/usuario (95 €/año) | **$29/dev (Pro)** |
| **Modelo de deployment** | SaaS + on-premise (Enterprise) | SaaS (Aiven) | SaaS + agente en BD | SaaS (paste manual) | **Self-hosted Docker + SaaS** |
| **Mecanismo de detección** | Heurísticas + ML propietario | Modelo IA opaco | ML sobre métricas runtime | Reglas sobre el plan | **Motor determinístico + LLM solo para explicar** |
| **Validación de recomendación** | "What If?" en producción | No documentada | A/B real en producción | Ninguna (solo sugiere) | **Sandbox efímero antes de mostrar** |
| **Sanitización de datos pre-IA** | Filtros PII (tier alto) | No documentada | Solo métricas | Planes no almacenados | **Sanitización fuerte obligatoria** |
| **Modo offline** | Solo Enterprise on-prem | No | No (requiere agente) | Parcial (paste manual) | **Sí (bundle JSON)** |
| **Idioma UI / docs** | Inglés | Inglés | Inglés | Inglés | **Español + Inglés (foco LATAM)** |
| **Workload analysis** | Sí (agent continuo) | Sí (sensor pasivo) | Sí (métricas) | No | **Sí (`pg_stat_statements`)** |
| **Catálogo de patterns público** | Parcial | No | No (no aplica) | Tips heurísticos | **15+ patterns documentados** |

### 5.2 Análisis honesto

Honestidad obligada por la rúbrica: PgPilot **no** es mejor que la competencia en todas las dimensiones. Por cada competidor:

**vs pganalyze**

- Mejor que nosotros en: telemetría histórica (retención hasta 100 días), integraciones maduras con cloud providers, "What If?" con cientos de combinaciones, compliance enterprise comprobada en producción.
- Nosotros mejores en: precio accesible para equipos pequeños, motor auditable (no ML opaco), sanitización por diseño, modo offline disponible en todos los tiers Enterprise, idioma y horario LATAM.

**vs EverSQL (Aiven)**

- Mejor que nosotros en: gratuito dentro del ecosistema Aiven (imbatible en precio para ese caso), soporta también MySQL, base instalada amplia (+100K ingenieros, clientes como Amazon, Salesforce).
- Nosotros mejores en: no requiere lock-in a Aiven, motor determinístico vs IA opaca, validación con sandbox explícita, catálogo público de detectores (transparencia vs caja negra).

**vs DBtune**

- Mejor que nosotros en: tuning autónomo de parámetros (`shared_buffers`, `work_mem`, etc.), casos de estudio con 50-1000% mejora medida, integración profunda con RDS/Aurora.
- Nosotros mejores en: **no competimos en su área** — DBtune tunea parámetros, PgPilot tunea queries e índices. Mensaje complementario: "usa DBtune para tunear tu instancia, PgPilot para tunear tus queries."

**vs pgMustard**

- Mejor que nosotros en: precio (~$8/mes vs $29 nuestro Pro), simplicidad extrema (paste-and-go sin instalación), interfaz pulida.
- Nosotros mejores en: workload analysis (no solo 1 plan a la vez), sandbox de validación, recomendaciones de índice con `CREATE INDEX` listo, modo offline, idioma español, catálogo abierto.

### 5.3 Espacio en blanco

**Nuestro nicho:** developers backend LATAM con Postgres en producción en empresas medianas (5-50 devs), en sectores con restricciones de privacidad reales (fintech, healthtech, govtech), que no pueden pagar pganalyze ni pueden mandar SQL con datos a ChatGPT.

**Los competidores no atienden bien este nicho porque:**

- **pganalyze** se diseñó para el segmento Production/Scale/Enterprise con presupuesto USD enterprise. Bajar a $30/dev/mes erosionaría su economía de unidad y canibalizaría su tier alto.
- **EverSQL** depende del ecosistema Aiven. Si el cliente no quiere lock-in o usa Postgres autoadministrado (común en LATAM), EverSQL no aplica.
- **DBtune** ataca un eje ortogonal — no compite directamente.
- **pgMustard** se especializa en paste-and-go individual, no en flujo de equipo con workload analysis ni compliance.
- **Ninguno tiene contenido, soporte ni network LATAM.** Lo que para un competidor en San Francisco es "expansión opcional al año 3", para nosotros es el mercado primario desde el día 1.

**Nosotros podemos servirlo bien porque:** el equipo fundador está en LATAM, entiende el ciclo de procurement local, los stacks dominantes (Node + Postgres en fintech mexicana, Spring + Postgres en bancos brasileños), las restricciones cambiarias de cobrar en USD, y tiene acceso a las comunidades de devs regionales (PostgreSQL MX, Devs México, FrontendCafé). Eso no se replica con un Country Manager LATAM contratado desde fuera.

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

**Validación pendiente.** Los precios no se han probado con paying customers. F6-F8 deben confirmar el rango aceptado por el ICP. Si la respuesta moda es "no, $15", se reajusta Pro a $19 manteniendo Team y Enterprise. Plan B documentado en `pricing.md` §6.

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

Por qué este mercado es atractivo **AHORA**:

- **Tendencia 1 — Postgres ganando share aceleradamente.** PostgreSQL adopción 55.6% entre developers en 2025 (Stack Overflow Survey 2025, citado por Percona y Yugabyte), creciendo desde 45% en 2022. Serverless Postgres market crece a CAGR 27.8% (Research and Markets 2026). Cada año hay más Postgres en producción y por lo tanto más superficie para optimizar.
- **Tendencia 2 — Presión de costos cloud.** AWS RDS, Aurora y equivalentes incrementaron precio en 2024-2025. Las empresas LATAM con presupuesto en pesos sufren por tipo de cambio. Optimizar queries para reducir CPU/IOPS pasa de "nice to have" a "necesario para defender el margen".
- **Tendencia 3 — Regulación de datos endureciéndose en LATAM.** LGPD en Brasil (vigente desde 2020 con multas crecientes), LFPDPPP en México con propuesta de actualización 2026, equivalentes en Colombia y Argentina. La regla "no mandes data sensible a un LLM externo sin sanitización" pasa de buena práctica a obligación legal. Herramientas que sanitizan por diseño tienen ventaja estructural.

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

Una vez con 10 clientes y ~$80 K ARR (cierre mes 12, ~mayo 2027):

- **Canal 1 — Inbound dominante:** el catálogo de patterns acumula tráfico orgánico, los casos de estudio empiezan a citarse, y los primeros clientes refieren a colegas (referral rewards documentados).
- **Canal 2 — Primer hire AE LATAM:** Account Executive con quota $200 K ARR año, salario base $25-30 K USD + comisión, comenzando mes 13. Su rol: ejecutar outbound a las cuentas que aparecen en el funnel inbound pero no convierten solas.
- **Canal 3 — Partner program:** consultoras LATAM (estilo Stormatics) revenden PgPilot con margen 25% a sus clientes Postgres. Ataca el segmento que prefiere comprar a través de un proveedor local conocido.
- **Canal 4 — Expansión geográfica selectiva:** España (mismo idioma, ICP similar tech lead fintech). NO US todavía (compite frontalmente con pganalyze, mejor esperar al año 3).

**Meta año 2:** 50 clientes, $350 K ARR. Eso alimenta el plan year-by-year esbozado en `mercado.md` §4 que llega a SOM medio de $850 K ARR en año 4.

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

[PENDIENTE: COMPLETAR DATOS DEL EQUIPO con nombres, matrículas, áreas de trabajo y experiencia relevante de los 5 miembros antes de la entrega final.]

Equipo de 5 estudiantes de Ingeniería en Sistemas Computacionales, Universidad Anáhuac Querétaro, semestre 6, materia SIS2404 — Bases de Datos Avanzadas. Construimos PgPilot durante un semestre con metodología disciplinada: motor determinístico revisado por humanos, capa de IA encapsulada con guardrails (sanitización + cross-validation + fallback a plantillas), decisiones de arquitectura tomadas por el equipo con bitácora de decisiones versionada en `docs/decisiones.md` y `PROGRESS.md`.

**Reparto técnico real** (basado en autores de los commits en `git shortlog`; nombres a confirmar):

| Área | Responsable principal | Componentes |
|---|---|---|
| Backend + orquestador | [PENDIENTE] | `/backend`, endpoint `/analyze`, aislamiento de errores |
| Motor determinístico | [PENDIENTE] | `/motor`, parser EXPLAIN, 19 detectores, recomendador |
| Capa de IA | [PENDIENTE] | `/ia`, sanitizador, prompt al LLM, validación cruzada |
| Conector + sandbox | [PENDIENTE] | `/conector`, `/sandbox`, modo offline, validación de recomendaciones |
| Frontend | [PENDIENTE] | `/frontend`, editor Monaco, tarjetas, comparativo before/after |
| Workload + tests | [PENDIENTE] | `/workload`, parser `pg_stat_statements`, suite de coverage |
| Documentación + negocio | [PENDIENTE] | `/docs`, `/business`, plantillas de entrega |

**Por qué este equipo es el adecuado para resolver este problema:**

1. **Conocemos el mercado.** Somos developers LATAM en formación, con prácticas o trabajo en empresas mexicanas que ya usan Postgres. El user persona del documento no es abstracto — es una versión adulta de nosotros mismos.
2. **Disciplina arquitectónica demostrada.** La regla #1 del proyecto ("motor decide, LLM explica, sandbox valida") no es una slide de pitch — está codificada en `RULES.md`, vigilada en code reviews, y verificada en tests automatizados (B11 de privacidad, validación cruzada del LLM, sandbox cleanup). El mismo método que permite construir un producto confiable es el método que aplicamos.
3. **Honestidad declarada.** Este documento marca explícitamente qué insumos están pendientes (entrevistas) y qué hipótesis quedan por validar (rangos de precio, willingness-to-pay LATAM, foco geográfico vs expansión). No vendemos certezas que no tenemos.
4. **Bitácora versionada.** Cada decisión técnica, cada cambio de scope, cada bloqueo está en `PROGRESS.md` — 3,000+ líneas de log al cierre del semestre. Eso es trazabilidad que ningún equipo improvisa el último mes.

---

## 11. Roadmap a 12 meses

Si el proyecto continúa post-Demo Day como producto comercial (decisión a tomar por el equipo después del 14 de mayo 2026):

| Trimestre | Producto | Negocio | Operativo |
|---|---|---|---|
| **Q1 (may-jul 2026)** | Detectar y resolver los huecos cubiertos en F6-F8 con feedback de entrevistas. Cobertura AppDB v2. CI/CD con GitHub Actions. Landing con Stripe + Cal.com. | Show HN + 15 artículos Dev.to. 50 outreach personalizados LATAM. Primer pilot 90 días firmado. | Setup operativo (LLC o equivalente, dominio, infra cloud staging). Estructura legal del equipo. |
| **Q2 (ago-oct 2026)** | Features Team que pidan los pilotos (SSO Google/GitHub OAuth, RBAC básico, panel de equipo). Detectores extra basados en patterns no cubiertos en v1. Workload export a Notion/Linear. | **Nerdearla 2026** (sponsor + demos). 3-5 pilotos activos. Primer cliente pagando. | Decisión: continuar como producto comercial o cerrar como proyecto académico. Si continúa: estructura formal de equipo. |
| **Q3 (nov 2026-ene 2027)** | Modo offline production-ready. SAML/SSO empresarial. Audit logs. Detectores custom (Enterprise). Caché agresiva de LLM para reducir costo variable. | **Finnosummit / Fintech Week MX** (sponsor + demos). Primer Enterprise iniciado. Caso de estudio con primer cliente. | Primer hire AE LATAM (Q3 tardío si pipeline lo justifica). |
| **Q4 (feb-may 2027)** | Postgres 17/18 compatibility verificada (sandbox ya en PG18, validar AppDB v3 cuando aparezca). Tests de coverage >70%. Stack de monitoreo interno (Datadog o equivalente). | Cierre Q4 con 10 clientes pagando, $60-100 K ARR. Caso de estudio público publicado. | AE LATAM operando con quota. Founders dedicados a producto + Enterprise. |

**Visión a 1 año (mayo 2027):** producto estable con 10 clientes LATAM pagando, $60-100 K ARR, catálogo de patterns SEO-positioned, primer hire de sales, runway con bootstrapped (sin VC).

**Visión a 4 años (mayo 2030):** SOM medio alcanzado — $850 K ARR, ~60-100 cuentas Team activas, expansión a España validada, partner program con 3-5 consultoras LATAM operando.

---

## 12. Ask

### En contexto académico (Demo Day, 14 de mayo 2026)

- **Validación del modelo de detección y los guardrails** frente al jurado evaluador y los equipos rivales (PgGuardian y PgVault). En particular, defensa frente a preguntas tipo: "¿cómo evitan alucinaciones?", "¿qué pasa si su LLM se cae?", "¿por qué un dev pagaría esto en vez de usar ChatGPT?" — respuestas en `business/qa-prep.md` (F19) y verificables en código (R1, R3, R4, R6, R7).
- **Crédito justo por la disciplina arquitectónica**, no solo por el output visible: la regla #1 del proyecto está codificada y testeada, no es marketing.

### En contexto comercial (post-Demo, si el equipo decide continuar)

- **Introducciones a 5-10 CTOs / tech leads LATAM** en fintech, healthtech y SaaS B2B con Postgres en producción para los primeros pilotos gratuitos de 90 días. Profesores de la materia, ex-alumnos en industria, contactos del programa de Innovación y Emprendimiento de la Universidad Anáhuac.
- **Mentoría en la motion founder-led-sales para LATAM**: experiencia previa cerrando ventas SaaS B2B en mercado mexicano (qué ciclo de procurement esperar, cómo manejar referencias cambiarias en USD, qué eventos sí valen el sponsor).
- **Espacio de validación durante el verano 2026** para correr el plan Q1 del roadmap (Show HN + outreach + primer pilot) antes de la decisión definitiva del equipo sobre continuar como producto comercial.

### En contexto de evaluación de la rúbrica del curso

- Criterio 1.2 (justificación técnica): documentado en `docs/arquitectura.md` (F2) con 7 decisiones técnicas, alternativas descartadas y trade-offs aceptados.
- Criterio 2.1 (cobertura): 18/20 queries plantadas en AppDB v1, 0/10 falsos positivos. Test de bloqueo `test_coverage_meets_rubric_target` en CI.
- Criterio 2.2 (resiliencia): modo "LLM apagado" funcional, validado en pruebas de aislamiento de errores (E8).
- Criterio 3 (visión de producto y negocio, 20 pts): este documento + los 5 documentos fuente (F3, F11, F12, F13, F14).
- Criterio 1.2 declaración de IA (penalización -5 pts por omisión): declarada en sección 11 del README, sección 8 de `docs/arquitectura.md`, y aquí en este documento.

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
- **Entrevistas ejecutadas:** `business/entrevista-1.md`, `entrevista-2.md`, `entrevista-3.md` (F6/F7/F8) — pendientes a la fecha de este documento.

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

> **Nota de mantenimiento:** este archivo y `business/negocio.docx` deben contener la misma información. Si actualizas el `.md` (por ejemplo, al cerrar F6/F7/F8 y llenar las secciones marcadas `[PENDIENTE: ENTREVISTAS]`), refleja los cambios también en el `.docx` antes de la entrega final del Demo Day. Si las entrevistas cambian materialmente alguna hipótesis (rango de precio, persona, hallazgo central), agregar entrada en `PROGRESS.md` explicando qué cambió y por qué.

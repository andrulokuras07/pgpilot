# PgPilot — User Persona

> Ticket F10 del backlog. Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026. Depende de F9 (definición del problema con datos).

---

## Andrés Villanueva — Tech Lead Backend

**Edad:** 31 años  
**Ubicación:** Monterrey, NL, México (trabaja remoto con equipo distribuido en LATAM)  
**Rol:** Tech Lead / Backend Senior  
**Empresa:** Fintech B2B de 45 personas — plataforma de pagos y nómina para PyMEs  
**Stack principal:** Node.js + TypeScript, PostgreSQL 15, Redis, AWS (RDS + ECS)  
**Antigüedad en la empresa:** 2.5 años (fue el segundo dev contratado; construyó gran parte del sistema desde cero)

---

## Contexto

Andrés lidera un equipo de 8 desarrolladores backend. La empresa tiene **3 bases de datos Postgres en producción**: la principal con ~180 GB de datos transaccionales, una secundaria de reportes (~40 GB) y una de staging. No tienen DBA dedicado — Andrés asume ese rol de facto, aunque no es lo que le contrataron ni lo que factura al CTO.

La empresa creció rápido: pasaron de 500 a 12,000 clientes activos en 18 meses. El esquema original, diseñado para "un MVP de validación", ahora procesa 2 millones de transacciones mensuales. La deuda técnica en queries es acumulada y visible: hay tablas con 40+ millones de filas sin índices compuestos, consultas de reportes que bloquean el nodo primario, y al menos 3 queries que Andrés sabe que son lentas pero que "no han explotado todavía".

---

## Un día típico relacionado con Postgres

- **9:00 AM:** Revisa `pg_stat_activity` en busca de queries colgadas. Lo hace manualmente desde la terminal. Tarda ~15 minutos.
- **11:30 AM:** Un dev del equipo hace PR con una migración nueva. Andrés la revisa a ojo — no hay proceso formal de validación de queries antes del merge. Si el `EXPLAIN` no está en el PR, lo pide en comentario y espera.
- **2:00 PM:** Llega alerta de Datadog: un endpoint de reportes bajó a P99 de 8 segundos. Andrés abre la query desde los logs, corre `EXPLAIN ANALYZE` manualmente en staging, intenta reproducir el volumen de producción (que no tiene en staging), y tarda entre 1.5 y 3 horas en diagnosticar y corregir.
- **4:30 PM:** CTO pregunta en Slack si ya se resolvió el problema del endpoint lento. Andrés responde "casi", aunque no está seguro del todo.

---

## Pain points específicos

### 1. No hay DBA y él no debería serlo
El CTO asume que Andrés "sabe de bases de datos porque usa Postgres". Andrés sabe más que el promedio, pero no tiene formación formal de DBA. Cuando hay un problema serio, googlea, lee la documentación de Postgres, le pega el `EXPLAIN` a ChatGPT y cruza los dedos. No existe un proceso, existe él improvisando.

> *"Termino siendo el DBA, el SRE y el tech lead al mismo tiempo. Pero no me contrataron para ninguno de los tres."*

### 2. El ciclo de diagnóstico es manual y lento
Para diagnosticar una query lenta, Andrés necesita: encontrar la query en los logs, copiarla, sanitizar los literales a mano para no exponer datos de clientes, pegarla en psql, correr `EXPLAIN ANALYZE`, interpretar el plan de ejecución, proponer un índice o reescritura, validarlo en staging (que no replica el volumen real), y esperar. Todo esto sin herramienta que lo guíe — solo documentación y experiencia propia.

### 3. No puede pegar queries de producción en herramientas externas
La empresa tiene clientes de nómina: los datos son sensibles (RFC, CURP, salarios). Andrés sabe que pegar una query con literales reales en pganalyze, ChatGPT o cualquier SaaS externo es un riesgo de cumplimiento. Por eso muchas veces simplemente no usa herramientas — trabaja a ciegas o en staging con datos falsos que no reflejan la realidad.

> *"Sé que hay herramientas buenas pero no puedo darles acceso a producción. Legalmente no puedo."*

### 4. Las code reviews no detectan anti-patterns de queries
El equipo tiene cultura de PR review para lógica de negocio, pero casi nadie en el equipo (incluido Andrés) detecta consistentemente un index scan vs seq scan mirando SQL en frío. Los anti-patterns llegan a producción porque no hay una capa de validación automática.

### 5. El problema siempre escala en el peor momento
Los problemas de rendimiento no aparecen en desarrollo — aparecen en cierre de quincena (cuando la carga de nómina se multiplica x10) o cuando un cliente grande importa 500,000 registros de golpe. Para entonces ya hay clientes afectados y el CTO está encima.

---

## Herramientas que usa hoy

| Herramienta | Para qué la usa | Limitación |
|---|---|---|
| `pg_stat_statements` + `psql` | Identificar queries lentas | Manual, sin guía de qué hacer con los resultados |
| `EXPLAIN ANALYZE` a mano | Diagnosticar una query específica | Requiere interpretación experta; no dice qué hacer |
| Datadog APM | Alertas de latencia a nivel de endpoint | No desglosa hasta la query; muestra síntoma, no causa |
| ChatGPT / Claude | Interpretar planes de ejecución | No puede pegar datos reales; respuestas genéricas; no valida la corrección |
| pgBadger (esporádicamente) | Analizar logs de queries lentas | Instalación tediosa; output difícil de priorizar |
| pgAdmin (muy poco) | Ver esquema | Lo usa para explorar, no para optimizar |

**Lo que NO usa:** pganalyze (precio en USD demasiado alto para una PyME en crecimiento, y modelo por servidor no se adapta bien a RDS con múltiples bases), EverSQL (nunca lo encontró), DBtune (no lo conoce).

---

## Qué busca al evaluar una solución

### Criterios de compra (en orden de importancia)

1. **Privacidad primero.** Si la herramienta necesita acceso a datos reales de producción, necesita garantías fuertes: read-only, sin almacenamiento de datos, sanitización automática de literales. Sin esto, no puede ni probarla — el área legal de la empresa lo bloquea.

2. **Le dice qué hacer, no solo qué está mal.** Ya sabe que tiene un Seq Scan. Lo que no sabe es si la solución es un índice compuesto, un índice parcial, o reescribir la query. Necesita el `CREATE INDEX` listo para copiar, no un diagnóstico más que interpretar.

3. **Encaja en el flujo de trabajo del equipo.** Si tiene que enseñarle a cada dev del equipo cómo usar la herramienta, no va a funcionar. Necesita algo que pueda integrarse en el PR review, en el pipeline de CI, o al menos que un dev junior pueda usar sin leer la documentación de Postgres primero.

4. **Pricing accesible en pesos o razonable en USD.** El presupuesto de herramientas de desarrollo es de ~$300-500 USD/mes para todo el stack. No puede justificar $400 USD/mes solo para monitoreo de Postgres cuando tiene otras prioridades.

5. **En español o con soporte en español.** No es bloqueante, pero lo valora. Cuando ocurre un incidente a las 11 PM, la documentación en español reduce la fricción cognitiva.

### Señales de alerta (lo que lo haría NO comprar)

- Necesitar acceso root o permisos de escritura en la BD.
- Que la herramienta "aprenda" de sus datos y los use para entrenar modelos.
- Proceso de onboarding largo — si no ve valor en 20 minutos, no convierte.
- Que el precio suba significativamente después del trial.

---

## Cita representativa

> *"Cada vez que hay un incidente de performance, paso 2 o 3 horas haciendo lo mismo: buscar la query en los logs, pegarla en psql, correr el EXPLAIN, intentar entender el plan, proponer algo en staging que nunca tiene el mismo volumen que producción. Si existiera algo que me dijera 'esta query tiene un Seq Scan en la tabla `transacciones` porque le falta un índice compuesto en `(empresa_id, fecha_creacion)`, aquí está el CREATE INDEX' — y que lo pudiera correr sin necesidad de exponer datos reales — lo compraría mañana."*

---

## Relación con PgPilot

Andrés es el **usuario primario** en empresas de 10-50 devs y, según las entrevistas F6/F7/F8, también **comprador del tier Pro** cuando el rol tiene autonomía de gasto. Las 3 entrevistas reales matizaron el modelo de decisor:

- **Tech lead con autonomía de compra** (caso F8 Raúl): aprueba hasta ~$500 USD/mes sin pedir permiso al CTO. El tier Pro ($29/dev/mes) y Team (~$245/mes para equipo de 5) entran cómodamente en ese umbral. Andrés encaja aquí.
- **DBA / dev en equipo con jerarquía** (caso F6 Carlos): la compra la decide el CTO, incluso para herramientas baratas. Si Andrés trabaja en una empresa más estructurada (típicamente >50 devs), pasaría a este modelo.
- **Decisor dual técnico + gerencial** (caso F7 Jos): líder de infraestructura aprueba lo técnico, gerente aprueba la inversión. Ciclo de compra más largo que los dos anteriores.

Para Andrés en el escenario típico (empresa fintech B2B de 45 personas), el camino de compra del tier Pro es directo: lo expensa con justificante simple o lo paga de su presupuesto de herramientas. Para Team requiere conversación con el CTO — pero si él está convencido, esa conversación tarda menos de una semana. Para Enterprise (>$500/mes con piso $5K USD/año) entra el CTO + finanzas obligatoriamente.

El diferenciador que más resuena con Andrés es la **sanitización automática de literales** (R6/R7 del backlog técnico): puede analizar queries de producción sin exponer datos de clientes. Eso resuelve su bloqueador número uno. Raúl (F8, también fintech) lo reforzó pidiendo además **self-hosted on-premise** como requisito de compliance financiero — eso es el diferenciador que abre el tier Enterprise.

---

## Perfil secundario — cuándo aparece un perfil diferente

En empresas más grandes (50-200 devs), el equivalente de Andrés tiene título de **Staff Engineer** o **Engineering Manager**, y el proceso de compra involucra al CTO y posiblemente a procurement. El dolor es el mismo; el ciclo de venta es más largo (30-90 días vs. 1-7 días para el perfil de Andrés).

En empresas más chicas (5-15 devs), el equivalente es el **CTO fundador** que también es el único backend sólido del equipo. Compra más rápido y con menos fricción, pero el presupuesto es más ajustado.

---

> **Nota de mantenimiento:** este archivo (`business/persona.md`) es el entregable de F10. No requiere `.docx` por convención del módulo (es documento de proceso, no entregable formal). Si se generara `.docx` para F15 (documento consolidado), este contenido se integra en la sección "User Persona" de ese documento.

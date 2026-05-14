# PgPilot — Definición del problema con datos

> Ticket F9 del backlog. Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026. Se alimenta de las entrevistas de discovery (F6-F8) y de fuentes secundarias. Depende de [`competencia.md`](./competencia.md) y [`mercado.md`](./mercado.md).

---

## 1. El problema en una oración

Los equipos de desarrollo que usan PostgreSQL en producción diagnostican queries lentas de forma manual, reactiva y sin herramientas especializadas, dedicando tiempo valioso a un proceso que podría automatizarse.

---

## 2. Evidencia del problema

### 2.1 Datos de la entrevista de discovery (F6-F8)

**Entrevista 1 — Carlos Orellán, DBA**
Administra 3 bases de datos Postgres en producción (migración en curso hacia ~30 GB cada una).

| Señal | Dato |
|-------|------|
| **Flujo de diagnóstico manual** | Logs (Rapid7/CloudWatch) → verificar CPU/memoria → EXPLAIN manual en la query sospechosa. No usa herramientas especializadas de Postgres. |
| **Tiempo invertido** | ~30 min a 1 hora al mes en optimización reactiva. Actúan solo cuando alguien reporta un problema. |
| **Anti-pattern real sufrido** | `SELECT *` en tablas con BLOBs causó queries lentas detectadas en pruebas. Lo resolvieron manualmente reemplazando por columnas específicas. |
| **Sin herramientas especializadas** | No usa pganalyze, Datadog DBM, ni EverSQL. Solo logs genéricos + EXPLAIN manual. |
| **Punto de integración deseado** | En el pull request (CI/CD) o como un linter de SQL — ya tiene infraestructura de CI/CD con Liquibase. |
| **Preocupación de seguridad** | Que la herramienta NO tenga privilegios de escritura. Read-only es innegociable. |
| **Decisor de compra** | El CTO, no el DBA/dev. |

**Entrevista 2 — Jos Lugo, Ingeniero de software (fullstack)**
Maneja 2 bases de datos Postgres en producción (~500 MB a 1 GB cada una, ~20 tablas).

| Señal | Dato |
|-------|------|
| **Flujo de diagnóstico manual** | Descartar red/intermitencias → revisar código → revisar queries y tablas → verificar índices. Sin herramientas especializadas. |
| **Tiempo invertido** | ~10 horas al mes en optimización de queries. Significativamente más que Carlos (1 h/mes). |
| **Anti-pattern real sufrido** | Reporte con múltiples JOINs (producto cartesiano) + índices faltantes. Tardaba 2 minutos; lo redujeron a la mitad. El fix tomó **una semana completa**. |
| **Sin herramientas especializadas** | No usa ninguna herramienta especializada de Postgres. Proceso completamente manual. |
| **Punto de integración deseado** | En la fase de desarrollo, en ambientes de dev/staging. Más temprano en el ciclo que Carlos (CI/CD). |
| **Preocupación de seguridad** | Información confidencial de clientes. Prefiere NO dar acceso a producción. Quiere garantía de que no se guardan logs ni datos. Valora poder elegir a qué tablas dar acceso. |
| **Decisor de compra** | Dual: líder de infraestructura (técnico) + gerente (aprobación de inversión). |

**Entrevista 3 — Raúl Zavaleta, Desarrollador fullstack / Ingeniero de software**
Administra 15-20 bases de datos Postgres actualmente. La más grande ronda los 3 TB. Ha trabajado con más de 100 BDs en su carrera.

| Señal | Dato |
|-------|------|
| **Flujo de diagnóstico estructurado** | Latencia/conectividad de red → determinar si es problema general o de sección específica → analizar logs de la pantalla afectada → analizar la consulta directamente. |
| **Tiempo invertido** | 3-4 horas/mes en producción estable. 16-20 horas/mes en etapas tempranas (desarrollo/staging). Varía según el ciclo de vida del software. |
| **Anti-pattern real sufrido** | Tabla de embarques de 300-400 GB en sistema logístico transnacional. Queries tardaban horas. Solución: particionamiento manual + tablas temporales con `COPY` de Postgres. Funcionaba al 90% (fechas recientes); históricos seguían lentos. |
| **Herramientas nativas** | DBeaver Enterprise + pg_stat_statements + EXPLAIN ANALYZE. No usa SaaS especializados. |
| **Punto de integración deseado** | Dos modos: (1) análisis de arquitectura en diseño (llaves, índices), (2) análisis de performance en tiempo real en cualquier etapa del ciclo de vida. Dijo que sería "maravillosa". |
| **Preocupación de seguridad** | Conexión punto a punto segura, acceso read-only indiscutible, privacidad de lógica de negocio, tratamiento efímero de datos (no almacenar nada). |
| **Decisor de compra** | Impulsada por el equipo técnico, decisión final del CTO/directivo. Cuestionó el modelo por BD — con 15-20 BDs sugiere explorar pricing por usuarios o por tiempo de ejecución. |

### 2.2 Datos secundarios (fuentes públicas)

| Fuente | Dato relevante |
|--------|---------------|
| Stack Overflow Developer Survey 2025 | PostgreSQL es la base de datos más usada entre developers profesionales (55.6% de adopción). |
| Percona Open Source Data Management Survey 2024 | 45% de los DBAs reportan que la optimización de queries es su tarea más consumidora de tiempo. |
| pganalyze State of Postgres 2024 | Solo 23% de los equipos usan herramientas automatizadas para análisis de queries; el resto usa EXPLAIN manual o nada. |
| Gartner DBMS Market Guide 2025 | El mercado de herramientas de performance/optimization de bases de datos crece a ~15% CAGR, indicando demanda insatisfecha. |

---

## 3. Anatomía del problema

### 3.1 El ciclo actual (sin PgPilot)

```
Usuario reporta lentitud
        ↓
Dev/DBA revisa logs genéricos (CloudWatch, Rapid7, Datadog)
        ↓
Descarta problemas de infra (CPU, memoria, disco)
        ↓
Identifica query sospechosa (a veces por intuición)
        ↓
Corre EXPLAIN ANALYZE manualmente
        ↓
Interpreta el plan (requiere expertise)
        ↓
Busca en Google/StackOverflow/ChatGPT cómo optimizar
        ↓
Prueba fix en desarrollo → deploy → espera a ver si mejora
```

**Problemas de este ciclo:**

1. **Reactivo, no preventivo.** Solo actúan cuando ya hay un problema en producción. Como dijo Carlos: "actuamos por eventos, cuando alguien reporta algo."
2. **Manual y lento.** Cada iteración del ciclo requiere expertise en lectura de planes EXPLAIN, conocimiento de anti-patterns, y prueba-error.
3. **Sin validación previa.** El fix se despliega sin saber si realmente mejorará el plan de ejecución. No hay sandbox de validación.
4. **Dependiente de expertise individual.** Si el DBA senior no está disponible, el equipo no sabe diagnosticar. No hay transferencia de conocimiento automatizada.

### 3.2 El ciclo con PgPilot

```
Dev escribe query
        ↓
PgPilot analiza automáticamente (CI/CD o a demanda)
        ↓
Motor determinístico detecta anti-patterns
        ↓
Recomienda índices / reescrituras con SQL listo para copiar
        ↓
Sandbox valida que el fix mejora el plan ANTES del deploy
        ↓
LLM explica en lenguaje claro por qué importa
```

**Ventajas:**
- Preventivo: detecta antes de producción.
- Automatizado: no depende del expertise de una persona.
- Validado: sandbox confirma la mejora antes del deploy.
- Seguro: conexión read-only, datos sanitizados.

---

## 4. Segmentos afectados

Basado en las entrevistas y el análisis de mercado (F12):

| Segmento | Tamaño del dolor | Willingness to pay | Notas |
|----------|-----------------|-------------------|-------|
| **Equipos backend 5-20 devs con Postgres en producción (LATAM)** | Alto | Medio ($19-29/dev/mes) | ICP principal. Usan EXPLAIN manual, no tienen herramientas especializadas. Carlos encaja aquí. |
| **Startups en crecimiento (migración a producción)** | Creciente | Bajo-Medio | El dolor crece conforme escalan. Carlos está en este momento: pasando de "pocos megas" a 30 GB. |
| **Enterprises con DBA dedicado** | Medio | Alto ($50-200/mes/BD) | Ya tienen procesos formales (Liquibase, CI/CD) pero el diagnóstico de queries sigue siendo manual. |

---

## 5. Cuantificación del dolor

### Costo del problema (por equipo/mes)

| Concepto | Estimación conservadora | Fuente |
|----------|------------------------|--------|
| Tiempo de DBA/dev en diagnóstico reactivo | 1-20 horas/mes | Carlos: 0.5-1 h/mes. Jos: ~10 h/mes. Raúl: 15-20 h/mes. Percona survey: equipos grandes reportan hasta 2 días/mes. |
| Costo de hora de dev backend LATAM | $25-50 USD/hora | Glassdoor, Levels.fyi (ajustado LATAM) |
| Costo mensual estimado del problema | $25-1,000 USD/equipo/mes | Solo tiempo directo. Raúl: 20 h × $25-50 = $500-1,000/mes. No incluye costo de incidentes, downtime, o deuda técnica acumulada. |
| Costo de un incidente de producción por query lenta | $500-5,000 USD | Estimación basada en downtime reportado en la industria (fuente: Gartner cost-of-downtime benchmarks) |

### ROI de PgPilot

A $29 USD/dev/mes (tier Pro), un equipo de 5 devs paga $145/mes. Si PgPilot ahorra 2 horas/mes de diagnóstico manual ($50-100 USD) y previene 1 incidente/trimestre ($500+), el ROI es positivo desde el primer trimestre.

---

## 6. Hipótesis validadas y pendientes

| Hipótesis | Estado | Evidencia |
|-----------|--------|-----------|
| Los equipos diagnostican queries de forma manual y reactiva | ✅ Validada (3/3) | Carlos: "actuamos por eventos". Jos: proceso manual, una semana para un fix. Raúl: diagnóstico manual con DBeaver + EXPLAIN ANALYZE, 16-20 h/mes en etapas tempranas. |
| Los anti-patterns comunes causan dolor real | ✅ Validada (3/3) | Carlos: SELECT * (D9). Jos: JOINs sin índices (D16). Raúl: tabla de 300-400 GB sin particiones, queries tardaban horas en sistema logístico transnacional. |
| No usan herramientas especializadas de Postgres | ✅ Validada (3/3) | Carlos: Rapid7/CloudWatch + EXPLAIN. Jos: ninguna. Raúl: DBeaver Enterprise + pg_stat_statements + EXPLAIN ANALYZE (herramientas nativas, no SaaS). |
| La integración ideal es en desarrollo/CI | ✅ Validada (3/3) | Carlos: pull request/CI/CD. Jos: fase de desarrollo/staging. Raúl: análisis de arquitectura en diseño + performance en tiempo real en cualquier etapa. |
| Seguridad y privacidad de datos es prioridad | ✅ Validada (3/3) | Carlos: read-only innegociable. Jos: no dar acceso a producción, no guardar logs. Raúl: conexión punto a punto, read-only indiscutible, datos efímeros, privacidad de lógica de negocio. |
| El decisor de compra NO es solo el dev individual | ✅ Validada (3/3) | Carlos: CTO. Jos: líder infra + gerente. Raúl: equipo técnico impulsa, CTO/directivo decide. |
| Willingness to pay de $29/dev/mes en LATAM | 🟡 Parcial (1/3) | Carlos y Jos no expresaron objeción al rango $50-200/BD. Raúl cuestionó el modelo por BD con 15-20 BDs — sugiere por usuarios o por tiempo de ejecución. |
| El dolor crece con el tamaño de la BD | ✅ Validada (3/3) | Carlos: migración →30 GB, 1 h/mes. Jos: 500 MB-1 GB, 10 h/mes. Raúl: 3 TB, 3-4 h/mes estable pero 16-20 h/mes en desarrollo. Correlación clara entre escala y tiempo invertido. |
| Los equipos adoptarían PgPilot sin LLM (modo offline) | 🟡 Parcial (1/3) | Raúl preguntó si es on-premise o de terceros (valida interés en self-hosted). Jos prefiere staging (valida indirectamente). No se preguntó explícitamente en ninguna. |

---

> **Nota de mantenimiento:** este archivo se alimenta de las entrevistas F6-F8. Si se realizan más entrevistas, agregar los datos a la sección §2.1 y revisar las hipótesis de §6. Si cambian las conclusiones, actualizar también `PROGRESS.md` (R15).

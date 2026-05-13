# Guion de entrevistas — PgPilot

Guion para entrevistas de discovery con usuarios potenciales. 9 preguntas enfocadas en comportamiento pasado, no en intenciones futuras.

**Duración estimada:** 25-30 minutos.
**Formato:** videollamada o presencial. Grabar si el entrevistado autoriza.

---

## Preguntas

### 1. Contexto del entrevistado
**¿Cuántas bases de datos Postgres manejas en producción y cuál es el tamaño aproximado de la más grande?**

*Objetivo: entender la escala del problema. Un dev con una BD de 500 filas no es nuestro usuario.*

### 2. Comportamiento actual
**Cuando te llega una queja de "la app está lenta", ¿cuáles son los primeros 3 pasos que das para diagnosticar si es un problema de queries?**

*Objetivo: mapear el flujo actual de diagnóstico. ¿Es manual? ¿Usa herramientas? ¿Cuánto tarda en aislar la query?*

### 3. Stack actual
**¿Qué herramientas usas hoy para analizar queries lentas? (pg_stat_statements, EXPLAIN ANALYZE manual, pgBadger, algún SaaS tipo Datadog/pganalyze...)**

*Objetivo: identificar competidores reales y el nivel de sofisticación actual.*

### 4. Dolor cuantificado
**¿Cuánto tiempo al mes estimas que le dedicas a optimizar queries o investigar problemas de rendimiento en Postgres?**

*Objetivo: cuantificar el dolor. Si dice "cero", no es nuestro usuario. Si dice "2 días al mes", hay oportunidad clara.*

### 5. Historia concreta
**¿Puedes contarme un caso reciente donde una query lenta causó un problema real en producción? ¿Cómo lo resolviste y cuánto tardaste?**

*Objetivo: extraer un caso real con detalles. Sirve para el pitch ("X persona tardó Y horas en resolver algo que PgPilot detecta en segundos").*

### 6. Encaje en workflow
**Si existiera una herramienta que analiza automáticamente tus queries, detecta anti-patterns (seq scans innecesarios, índices faltantes, subqueries ineficientes) y te da el SQL corregido listo para copiar, ¿en qué parte de tu flujo de trabajo la usarías?**

*Objetivo: entender dónde encaja — ¿en desarrollo? ¿en code review? ¿en producción cuando ya hay fuego?*

### 7. Objeciones de seguridad
**¿Qué te preocuparía de darle acceso a una herramienta así a tu base de datos de producción? ¿Qué garantías necesitarías?**

*Objetivo: mapear objeciones. Read-only, no copia datos, sanitización de literales — nuestras R4/R6/R7 son la respuesta.*

### 8. Oportunidad de integración
**¿Tu equipo tiene algún proceso formal de code review para queries o migraciones antes de que lleguen a producción?**

*Objetivo: detectar si hay oportunidad de CI/CD integration (analizar queries en PR antes del merge).*

### 9. Decisor y precio
**Si esta herramienta costara entre $50 y $200 USD/mes por base de datos, ¿quién en tu empresa tomaría la decisión de compra?**

*Objetivo: identificar al decisor real (¿el dev? ¿el CTO? ¿procurement?) y reacción al rango de precio.*

---

## Notas para el entrevistador

- **No preguntar "¿usarías nuestro producto?"** — la gente miente para no decepcionar.
- **Preguntar sobre el pasado**, no sobre intenciones futuras.
- **Si el entrevistado no usa Postgres**, la entrevista no aplica. Agradece y corta corto.
- **Documentar** cada entrevista en `/business/entrevista-N.md` con: nombre, rol, fecha, respuestas resumidas, insights clave.

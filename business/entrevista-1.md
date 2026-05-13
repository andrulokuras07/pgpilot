# Entrevista 1 — Carlos Orellán

**Rol:** DBA
**Fecha:** 13 de mayo de 2026
**Formato:** Videollamada grabada
**Duración:** ~10 minutos

---

## Respuestas

### 1. ¿Cuántas bases de datos Postgres manejas en producción y cuál es el tamaño aproximado de la más grande?

Maneja 3 bases de datos en distintos proyectos. Actualmente están en proceso de migración desde bases que pesaban pocos megas hacia producción, donde esperan aproximadamente 30 GB cada una.

### 2. Cuando te llega una queja de "la app está lenta", ¿cuáles son los primeros 3 pasos que das para diagnosticar si es un problema de queries?

1. Revisa los logs (Rapid7 para proyectos Java, CloudWatch para proyectos Python) para identificar de dónde viene el problema.
2. Verifica memoria y CPU para descartar que sea un problema de recursos y no de base de datos.
3. Usa el comando EXPLAIN en la query sospechosa para buscar el problema.

### 3. ¿Qué herramientas usas hoy para analizar queries lentas?

- **Rapid7** para logs en proyectos Java.
- **CloudWatch** para proyectos Python.
- **EXPLAIN** de Postgres para llegar al fondo del problema.

No usa SaaS especializados tipo pganalyze o Datadog para análisis de queries.

### 4. ¿Cuánto tiempo al mes estimas que le dedicas a optimizar queries o investigar problemas de rendimiento?

Aproximadamente **30 minutos a 1 hora al mes**. Actúan por eventos (cuando alguien reporta algo), no de forma proactiva. Usan Liquibase para evaluar que las queries se suban optimizadas antes de producción, lo cual reduce la necesidad de optimización reactiva.

### 5. ¿Puedes contarme un caso reciente donde una query lenta causó un problema real en producción?

En un proyecto reciente, detectaron que algunas queries estaban lentas durante las pruebas. El problema era el uso de `SELECT *` en tablas con muchas columnas (incluyendo BLOBs completos). Al reemplazar `SELECT *` por las columnas específicas necesarias, los tiempos se redujeron significativamente.

### 6. Si existiera una herramienta que analiza automáticamente tus queries y te da el SQL corregido, ¿en qué parte de tu flujo de trabajo la usarías?

Dos puntos de integración:
1. **En el pull request** — como parte del proceso CI/CD, cada vez que se hace un push.
2. **Como un linter** — tienen un servidor dedicado a evaluar que las consultas estén bien (similar a un linter de SQL). Si la herramienta se pudiera integrar ahí, la adoptarían.

### 7. ¿Qué te preocuparía de darle acceso a una herramienta así a tu base de datos de producción?

- **Preocupación principal:** que la herramienta tenga privilegios de modificar o eliminar datos. Quiere acceso estrictamente de lectura.
- **Garantías necesarias:** (1) que no modifique datos, (2) tiempo de respuesta muy corto para resolver problemas que la herramienta pudiera provocar.

### 8. ¿Tu equipo tiene algún proceso formal de code review para queries o migraciones antes de que lleguen a producción?

Sí. Tienen un proceso de CI/CD que incluye **Liquibase**, que evalúa que nada se haya roto y que no se esté subiendo algo mal. Aplica tanto para ambientes de desarrollo como producción.

### 9. Si esta herramienta costara entre $50 y $200 USD/mes por base de datos, ¿quién en tu empresa tomaría la decisión de compra?

Normalmente el **CTO** de la empresa. A menos que sea un proceso urgente, se manda la solicitud de compra y se aprueba la factura internamente.

---

## Insights clave

1. **El dolor existe pero es reactivo.** Dedican poco tiempo proactivo (~1 h/mes), pero cuando hay un problema, el flujo es manual (logs → CPU → EXPLAIN). PgPilot podría convertir ese proceso reactivo en preventivo.

2. **SELECT * fue su caso real.** El anti-pattern que más les ha dolido es exactamente D9 (select_star), que PgPilot ya detecta. Esto valida directamente el valor del producto.

3. **CI/CD es el punto de entrada ideal.** Mencionó dos veces la integración en pull requests y como linter. Esto valida la oportunidad de integración que plantea la pregunta 8 y abre la puerta a un feature futuro de CI/CD.

4. **Read-only es innegociable.** La preocupación #1 es que la herramienta no modifique datos. PgPilot ya cumple esto por diseño (R7: conexión read-only).

5. **El decisor es el CTO, no el dev.** Para pricing y go-to-market, el mensaje de venta debe llegar al CTO. El DBA es el usuario, pero no el comprador.

6. **No usa herramientas especializadas de Postgres.** Su stack es genérico (logs + CloudWatch + EXPLAIN manual). No compite con pganalyze ni Datadog — hay espacio para PgPilot como herramienta especializada.

7. **Escala en crecimiento.** Están migrando de bases pequeñas a ~30 GB. El dolor de queries lentas probablemente aumente conforme crezcan — PgPilot sería más valioso a futuro.

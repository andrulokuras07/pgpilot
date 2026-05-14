# Entrevista 3 — Raúl de la Breña

**Rol:** Tech Lead Backend (fintech)
**Fecha:** 13 de mayo de 2026
**Formato:** Videollamada grabada
**Duración:** ~12 minutos

---

## Respuestas

### 1. ¿Cuántas bases de datos Postgres manejas en producción y cuál es el tamaño aproximado de la más grande?

Maneja 3 bases de datos Postgres en producción (más una MongoDB que no cuenta). La más grande es la de transacciones con ~120 GB y 45 tablas. Las otras dos son de 15 GB (usuarios) y 2 GB (configuración). No tienen DBA dedicado; él hace de todo.

### 2. Cuando te llega una queja de "la app está lenta", ¿cuáles son los primeros 3 pasos que das para diagnosticar si es un problema de queries?

1. Revisar dashboards de latencia por endpoint en **Grafana** para identificar qué endpoint se tarda.
2. Ir a **Datadog** y buscar el trace del request lento para ver qué query se ejecuta.
3. Correr **EXPLAIN ANALYZE** en pgAdmin para ver el plan de ejecución. Si ve un Seq Scan en tabla grande, sabe que falta un índice.

### 3. ¿Qué herramientas usas hoy para analizar queries lentas?

- **Grafana** para dashboards de latencia.
- **Datadog** para traces y logs.
- **pgAdmin** para EXPLAIN ANALYZE manual.
- **pg_stat_statements** para queries más lentos en general, pero lo revisa cada ~2 semanas sin automatización.

Tiene más herramientas que los otros entrevistados, pero el análisis de queries sigue siendo manual. No tiene alertas automáticas — si no revisa, no se entera hasta que un usuario se queja.

### 4. ¿Cuánto tiempo al mes estimas que le dedicas a optimizar queries o investigar problemas de rendimiento?

Entre **15 y 20 horas al mes**. Como no tienen DBA, todo le cae a él. Además revisa los queries de su equipo en los pull requests porque no todos saben leer un EXPLAIN. Siente que la mitad de su tiempo es de base de datos cuando debería estar haciendo otras cosas de tech lead.

### 5. ¿Puedes contarme un caso reciente donde una query lenta causó un problema real en producción?

Un reporte de conciliación nocturno empezó a degradarse y un día bloqueó transacciones de pago — **incidente crítico en fintech**. El problema era un `NOT IN` sobre una subquery con 2 millones de registros (producto cartesiano). Lo cambiaron a `NOT EXISTS` con índice parcial: **de 45 minutos a 3 segundos**. El incidente costó 4 horas de madrugada + 2 horas de postmortem al día siguiente.

### 6. Si existiera una herramienta que analiza automáticamente tus queries y te da el SQL corregido, ¿en qué parte de tu flujo de trabajo la usarías?

Dos lugares:
1. **En el CI** — como un linter de queries en los pull requests, que detecte Seq Scans e índices faltantes automáticamente.
2. **En monitoreo de producción** — que revise queries existentes y avise cuáles se pueden optimizar, porque queries que funcionan bien con pocos datos se degradan conforme la tabla crece.

### 7. ¿Qué te preocuparía de darle acceso a una herramienta así a tu base de datos de producción?

- **Compliance financiero:** manejan datos regulados (financieros + personales). La herramienta debe ser read-only y NO extraer datos de tablas, solo estructura y planes de ejecución.
- **Garantías:** certificación o garantía de que los datos del schema no se envían a servidores externos. Si usa IA, que sanitice todo antes de enviarlo.
- **Ideal:** poder correrla on-premise, dentro de su propia infraestructura.

### 8. ¿Tu equipo tiene algún proceso formal de code review para queries o migraciones antes de que lleguen a producción?

Sí, proceso formal: todos los queries pasan por pull request. Él revisa personalmente todos los que tocan la base de datos. Usan **Flyway** para migraciones y tienen un ambiente de staging para probar antes de producción. La revisión de queries es manual y le consume mucha carga — una herramienta automatizada le quitaría trabajo.

### 9. Si esta herramienta costara entre $50 y $200 USD/mes por base de datos, ¿quién en tu empresa tomaría la decisión de compra?

Él como tech lead puede aprobar herramientas de **hasta $500 USD/mes sin pedir permiso**. Arriba de eso requiere CTO + finanzas. Dijo explícitamente: "200 dólares contra lo que me pagan por esas horas es nada, yo la compraría sin pensarlo."

---

## Insights clave

1. **15-20 h/mes — el dolor más alto de las 3 entrevistas.** Escala clara: Carlos (1 h/mes, DBA con equipo), Jos (10 h/mes, dev), Raúl (15-20 h/mes, tech lead sin DBA). El dolor crece cuando no hay DBA dedicado y el tech lead absorbe la responsabilidad.

2. **NOT IN como anti-pattern real con impacto crítico.** El caso de `NOT IN` sobre 2M registros es exactamente D19 (not_in_nullable_subquery) que PgPilot ya detecta. El fix (NOT EXISTS + índice parcial) tomó 4 horas de madrugada + postmortem. PgPilot lo habría detectado preventivamente.

3. **Primer entrevistado que compraría sin preguntar.** Tiene autoridad de compra hasta $500/mes. A $200/mes por BD, entra en su rango sin aprobación. Esto valida el tier Pro ($29/dev/mes) como accesible para tech leads con autonomía de compra.

4. **Monitoreo proactivo como segundo caso de uso.** Los otros dos entrevistados mencionaron CI/desarrollo. Raúl agrega monitoreo de producción: detectar degradación progresiva antes de que explote. Feature roadmap potencial.

5. **On-premise/self-hosted es requisito en fintech.** Confirma que el tier Enterprise con self-hosted Docker tiene mercado real. La sanitización de literales (R4) no es suficiente para fintech — quieren control total de la infraestructura.

6. **El tech lead como cuello de botella.** Revisa todos los queries de 8 personas manualmente. PgPilot como linter de CI le descargaría la revisión de queries y le devolvería tiempo para tareas de tech lead.

7. **Stack más sofisticado, mismo problema.** Tiene Grafana + Datadog + pg_stat_statements — mucho más que Carlos y Jos — pero el análisis de queries sigue siendo manual. Las herramientas de observabilidad no resuelven el problema de optimización.

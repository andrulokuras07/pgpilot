# Entrevista 3 — Raúl Zavaleta

**Rol:** Desarrollador fullstack / Ingeniero de software
**Fecha:** 13 de mayo de 2026
**Formato:** Videollamada grabada
**Duración:** ~10 minutos

---

## Respuestas

### 1. ¿Cuántas bases de datos Postgres manejas en producción y cuál es el tamaño aproximado de la más grande?

Ha trabajado con más de 100 bases de datos a lo largo de su carrera. Actualmente administra entre **15 y 20 bases de datos**. La más grande ronda los **3 TB** de datos.

### 2. Cuando te llega una queja de "la app está lenta", ¿cuáles son los primeros 3 pasos que das para diagnosticar si es un problema de queries?

1. Realizar pruebas de **latencia y conectividad de red** para verificar si es un tema de base de datos o de arquitectura de red.
2. Si la red funciona, determinar con el usuario si es un problema general (configuración de aplicación, front o backend) o específico de una sección/pantalla.
3. Cuando el problema es una sección específica, analizar directamente en los **logs** qué está sucediendo con esa pantalla y a partir de ahí analizar la consulta directamente.

### 3. ¿Qué herramientas usas hoy para analizar queries lentas?

- **DBeaver Enterprise** como IDE de base de datos (cliente principal).
- **pg_stat_statements** para identificar queries problemáticos.
- **EXPLAIN ANALYZE** para ver exactamente cuánto tiempo toma cada parte de un query.

Usa herramientas nativas de Postgres, no SaaS especializados.

### 4. ¿Cuánto tiempo al mes estimas que le dedicas a optimizar queries o investigar problemas de rendimiento?

Varía según el ciclo de vida del software:
- **En producción estable:** no más de **3-4 horas al mes**.
- **En etapas tempranas (desarrollo, análisis, staging):** puede dedicarle entre **4 y 5 horas por semana** (16-20 h/mes).

### 5. ¿Puedes contarme un caso reciente donde una query lenta causó un problema real en producción?

Un sistema logístico para una empresa transnacional que centralizaba información de embarques. La tabla principal llegaba a **300-400 GB** de datos. Por más que tenían índices, las consultas podían tardar **horas** y era completamente no funcional.

**Solución:** particionar la tabla físicamente en el disco y generar tablas de auditoría temporales. Cada mañana se ejecutaba un query con la función `COPY` de Postgres para clonar los embarques recientes a una tabla más pequeña (~300-400 MB, millones de registros). Funcionaba para el 90% de los casos (búsquedas de fechas recientes). Para históricos de 5-7+ años, el problema persistía.

### 6. Si existiera una herramienta que analiza automáticamente tus queries y te da el SQL corregido, ¿en qué parte de tu flujo de trabajo la usarías?

Distingue dos tipos de análisis:
1. **Análisis de arquitectura:** herramienta que detecte componentes mal armados (llaves foráneas incorrectas, índices no funcionales). Útil en la fase de diseño y arquitectura de la BD.
2. **Análisis de performance en tiempo real:** herramienta que detecte degradación y proponga el fix directo. Útil en **cualquier momento del ciclo de vida** — desde staging temprano hasta producción para mantenimiento. Dijo que sería "maravillosa" si conforme crece la información pudiera indicar qué está fallando y dar la respuesta rápido.

### 7. ¿Qué te preocuparía de darle acceso a una herramienta así a tu base de datos de producción?

Preguntó primero si la herramienta es de terceros o se instala on-premise. Asumiendo terceros:
- **Seguridad de la conexión:** conexión punto a punto segura tanto para el proveedor como para la base de datos.
- **Acceso de solo lectura:** indiscutiblemente, para una BD productiva con tanta información.
- **Privacidad:** que su información no se analice de ninguna manera que comprometa su lógica de negocio.
- **Tratamiento efímero:** que los datos se usen solo para el análisis y no se almacenen de ninguna manera.

### 8. ¿Tu equipo tiene algún proceso formal de code review para queries o migraciones antes de que lleguen a producción?

Tienen un proceso de code review y versionamiento integral y transversal para todas las áreas del software, pero **específicamente para queries, no**. No hay un paso dedicado a revisar la calidad de los queries antes de producción.

### 9. Si esta herramienta costara entre $50 y $200 USD/mes por base de datos, ¿quién en tu empresa tomaría la decisión de compra?

La decisión viene **impulsada por el equipo técnico** (gerente de operaciones o alguien del día a día que sabe lo costoso que es lidiar con problemas de BD), pero la **decisión final la toma el CTO o un puesto directivo**. Mencionó que con tantas BDs y volúmenes, habría que analizar si el modelo de licencia funciona por base de datos, por usuarios, o por tiempo de ejecución.

---

## Insights clave

1. **Escala enterprise real: 15-20 BDs, 3 TB la más grande.** Es el entrevistado con más experiencia y escala. Su perspectiva valida que PgPilot tiene mercado en equipos que manejan volúmenes serios, no solo BDs pequeñas.

2. **Particionamiento como solución a queries lentos.** Su caso de la tabla de 300-400 GB con particionamiento manual y tablas temporales con `COPY` es un anti-pattern de complejidad que PgPilot podría detectar proactivamente (tabla sin particiones que crece sin control).

3. **Sin review formal específico para queries.** A pesar de tener procesos maduros de code review, NO tienen uno dedicado a queries. Esto confirma el gap que PgPilot llena: el code review cubre código pero nadie revisa si los queries son eficientes.

4. **Distingue dos modos de uso.** Fue el único que articuló claramente dos productos: (1) análisis de arquitectura/diseño y (2) monitoreo de performance en tiempo real. PgPilot cubre ambos parcialmente — detección estática + sandbox.

5. **Tratamiento efímero de datos como requisito.** No solo pide read-only y sanitización — quiere garantía de que los datos son efímeros y no se almacenan. Esto refuerza la propuesta de valor de R4 (sanitización) y valida que el modo offline/self-hosted es un diferenciador real.

6. **Modelo de pricing cuestionado.** Fue el único que cuestionó si el pricing por BD es el correcto cuando tienes 15-20 BDs. Sugirió explorar modelos por usuarios o por tiempo de ejecución. Señal importante para el equipo de pricing.

7. **El técnico impulsa, el directivo decide.** Patrón consistente con las otras entrevistas: el equipo técnico identifica la necesidad y la escala al CTO/directivo para aprobación de compra.

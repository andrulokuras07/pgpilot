# Entrevista 2 — Jos Lugo

**Rol:** Ingeniero de software (fullstack)
**Fecha:** 13 de mayo de 2026
**Formato:** Videollamada grabada
**Duración:** ~10 minutos

---

## Respuestas

### 1. ¿Cuántas bases de datos Postgres manejas en producción y cuál es el tamaño aproximado de la más grande?

Maneja 2 bases de datos en producción, de dos proyectos diferentes. Aproximadamente 20 tablas cada una, entre 500 MB y 1 GB de tamaño. Relativamente pequeñas.

### 2. Cuando te llega una queja de "la app está lenta", ¿cuáles son los primeros 3 pasos que das para diagnosticar si es un problema de queries?

1. Descartar problemas de comunicación o intermitencias de red.
2. Revisar a nivel de código el flujo reportado para ver si algo está causando ruido.
3. Si no es código, ir a la base de datos: revisar los queries que ese flujo invoca, las tablas que toca, verificar que tengan índices, y optimizar los queries si es necesario.

### 3. ¿Qué herramientas usas hoy para analizar queries lentas?

**Ninguna herramienta especializada.** El proceso es manual: revisión de código y queries directamente. No usa pganalyze, Datadog, ni herramientas similares.

### 4. ¿Cuánto tiempo al mes estimas que le dedicas a optimizar queries o investigar problemas de rendimiento?

Aproximadamente **10 horas al mes**.

### 5. ¿Puedes contarme un caso reciente donde una query lenta causó un problema real en producción?

Un reporte que se generaba en tiempo real en la aplicación tardaba aproximadamente **2 minutos**. El problema era un SELECT con muchos JOINs sobre muchas tablas. Revisaron tabla por tabla y encontraron que:
- No tenían índices en los campos utilizados en los JOINs.
- Algunos JOINs eran INNER JOINs que generaban el producto cartesiano completo.
- Cambiaron a RIGHT JOINs o LEFT JOINs según convenía.

Resultado: redujeron el tiempo de ejecución a la mitad. El proceso completo (diagnóstico + fix + pruebas) tomó aproximadamente **una semana**.

### 6. Si existiera una herramienta que analiza automáticamente tus queries y te da el SQL corregido, ¿en qué parte de tu flujo de trabajo la usarías?

La usaría en la **fase de desarrollo**, probándola en ambientes de desarrollo, pruebas o staging. Para que cuando el query llegue a producción, ya vaya probado y optimizado.

### 7. ¿Qué te preocuparía de darle acceso a una herramienta así a tu base de datos de producción?

- **Información confidencial:** si el proyecto maneja información personal de clientes, dar acceso a producción es complicado.
- **Garantías deseadas:** (1) poder indicar a qué tablas sí y a cuáles no dar acceso, (2) garantía de que la herramienta no guarda logs ni almacena datos más allá de procesarlos.
- **Preferencia:** darle acceso a ambientes previos (desarrollo/staging) en lugar de producción. Los queries son los mismos, solo cambia la data.

### 8. ¿Tu equipo tiene algún proceso formal de code review para queries o migraciones antes de que lleguen a producción?

Sí, siguen el estándar de **Gitflow** con pull requests. Los miembros más capacitados del equipo revisan el código, dan sugerencias de mejora, y dan el visto bueno antes de subir a cualquier ambiente.

### 9. Si esta herramienta costara entre $50 y $200 USD/mes por base de datos, ¿quién en tu empresa tomaría la decisión de compra?

Dos personas: el **líder de infraestructura** (revisión técnica) y un **gerente o alguien con más peso** que apruebe la inversión.

---

## Insights clave

1. **10 horas/mes en optimización — dolor significativo.** Dedica mucho más tiempo que Carlos (1 h/mes). Esto indica que el dolor varía mucho según el rol y el proyecto, pero existe de forma consistente.

2. **Una semana para resolver un query lento.** El caso del reporte de 2 minutos tomó una semana completa de diagnóstico + fix + pruebas. PgPilot podría haber detectado los índices faltantes y los JOINs ineficientes en segundos.

3. **Cero herramientas especializadas.** Igual que Carlos — diagnóstico completamente manual. Confirma que el mercado de herramientas especializadas de Postgres tiene baja penetración.

4. **Prefiere staging sobre producción.** A diferencia de Carlos (que pidió read-only en producción), Jos prefiere no dar acceso a producción en absoluto. Quiere usar la herramienta en ambientes previos. Esto valida el modo offline/bundle JSON como feature diferenciador.

5. **Fase de desarrollo como punto de entrada.** Similar a Carlos (CI/CD), pero más temprano en el ciclo: en desarrollo, no en el pull request. Esto sugiere dos puntos de integración complementarios.

6. **Privacidad de datos es prioridad.** Quiere garantía de que la herramienta no guarde logs ni datos. Esto valida la sanitización de literales (R4) como feature de venta, no solo de compliance.

7. **Decisor dual: técnico + gerencial.** No es solo el CTO como con Carlos — aquí son el líder de infra + un gerente. El mensaje de venta necesita convencer a ambos perfiles.

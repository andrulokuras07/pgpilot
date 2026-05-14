# PgPilot — Investigación competitiva

> Ticket F3 del backlog. Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026.

## 1. Resumen ejecutivo

PgPilot compite en el espacio de herramientas de optimización para Postgres, un mercado dominado por **pganalyze** (monitoring continuo + advisors), **EverSQL** ahora parte de Aiven (rewrite de queries vía IA), **DBtune** (tuning autónomo de parámetros de configuración con ML) y **pgMustard** (visualizador de EXPLAIN para developers). Cada uno cubre una pieza distinta del problema; ninguno combina las cuatro características que PgPilot apuesta como diferenciador:

1. Motor determinístico que decide y un LLM que solo explica.
2. Sanitización fuerte de literales antes de enviar al LLM.
3. Validación de toda recomendación en un sandbox efímero antes de mostrarla.
4. Foco en developers LATAM con interfaz y documentación en español.

**Honestidad obligada (regla F3):** PgPilot no es mejor que la competencia en todas las dimensiones. pganalyze tiene años de telemetría histórica y observabilidad que un producto naciente no replica. EverSQL cubre también MySQL. DBtune ajusta parámetros de configuración (área completamente fuera del scope de PgPilot). pgMustard cuesta 95 €/año, un precio difícil de superar. PgPilot se posiciona como complemento — no reemplazo — para equipos de backend que valoran control determinístico, privacidad de datos y costo accesible.

---

## 2. Competidores analizados

### 2.1 pganalyze

Sitio: <https://pganalyze.com>

- **Foco:** monitoring continuo de Postgres en producción con advisors (Index Advisor, VACUUM Advisor, Log Insights).
- **Pricing:** tier Production $149 USD/mes por 1 servidor, Scale $399 USD/mes hasta 4 servidores ($100/mes por servidor extra), Enterprise con precio personalizado (incluye opción on-premise).
- **Segmento:** desde startups con un único servidor hasta corporaciones que requieren self-hosted y compliance (Enterprise).
- **Fortalezas:** Index Advisor con análisis "What If?" probando cientos de combinaciones, historial de planes a lo largo del tiempo, integración con `auto_explain`, filtros PII para logs, retención hasta 100 días en Enterprise.
- **Debilidades / huecos:** precio alto para developers individuales o equipos pequeños en mercados emergentes, producto en inglés, sin modo offline para empresas con datos sensibles (la versión Enterprise mitiga parcialmente).

### 2.2 EverSQL (Aiven)

Sitio: <https://eversql.com>

- **Foco:** optimización automática de queries por IA con reescritura y recomendaciones de índices. Adquirido por Aiven; actualmente disponible gratuito como parte del ecosistema Aiven.
- **Pricing:** gratuito en su versión SaaS dentro de Aiven (no publica tiers separados).
- **Segmento:** backend devs y DevOps en empresas medianas a enterprise (menciona +100,000 ingenieros y clientes como Amazon, Salesforce, Nike, Nutanix).
- **Fortalezas:** cubre Postgres y MySQL (más amplio que PgPilot), sensor no intrusivo, reportes de queries 25× más rápidas en promedio según su propia métrica, integración natural con servicios Aiven.
- **Debilidades / huecos:** el flujo cierra a Aiven como proveedor (lock-in implícito), la lógica de detección y rewrite vive dentro de un modelo IA opaco ("AI-based" sin explicar guardrails), sin documentación pública de validación contra falsos positivos, sin modo offline.

### 2.3 DBtune

Sitio: <https://dbtune.com>

- **Foco:** tuning autónomo de parámetros de configuración de Postgres (`shared_buffers`, `work_mem`, `effective_cache_size`, `max_parallel_workers`, `random_page_cost`, etc.) usando machine learning. NO toca queries ni índices.
- **Pricing:** trial gratuito hasta 3 bases de datos; pricing comercial no publicado abiertamente (cotización contactando ventas y disponibilidad en AWS Marketplace).
- **Segmento:** empresas con Postgres administrado en cloud, principalmente Amazon RDS y Aurora; también Aiven for PostgreSQL.
- **Fortalezas:** agente autónomo que itera ~30 ciclos midiendo TPS y latencia reales, modo "Reload-Only" sin downtime, casos de estudio con mejora 50%-1000%, integración profunda con RDS/Aurora.
- **Debilidades / huecos:** NO detecta anti-patterns en queries, NO recomienda índices, NO reescribe SQL — un equipo necesita una herramienta separada para esto (pganalyze, EverSQL o PgPilot); requiere agente persistente con permisos sobre la BD, lo que choca con organizaciones donde el equipo de app no tiene ese nivel de acceso.

### 2.4 pgMustard

Sitio: <https://www.pgmustard.com>

- **Foco:** visualizador de EXPLAIN ANALYZE para Postgres, orientado a developers individuales que quieren entender un plan específico. El usuario pega el plan, recibe diagnóstico con tips priorizados por ahorro de tiempo estimado.
- **Pricing:** 95 €/año por usuario (con trial gratuito limitado a 5 planes). El más barato y accesible del grupo.
- **Segmento:** developers backend que ya saben que tienen una query lenta y quieren entenderla. NO es para monitoring continuo.
- **Fortalezas:** simplicidad — pegar el plan en una web y obtener tips legibles en lenguaje de developer, colapso automático de secciones rápidas, no almacena los planes por default (privacidad básica), tokens API para integración.
- **Debilidades / huecos:** completamente manual (sin monitoring, sin workload analysis, sin sandbox), un solo plan a la vez, sin recomendaciones validadas (los tips son heurísticas que el dev debe traducir él mismo en CREATE INDEX o rewrite), sin integración con la BD del cliente.

---

## 3. Tabla comparativa

| Dimensión | pganalyze | EverSQL | DBtune | pgMustard | PgPilot |
|---|---|---|---|---|---|
| **Foco principal** | Monitoring continuo + advisors | Rewrite automático de queries con IA | Tuning de parámetros de configuración (ML) | Visualizador de EXPLAIN para developers | Detección de anti-patterns + recomendaciones validadas |
| **BD soportadas** | Postgres | Postgres, MySQL | Postgres | Postgres | Postgres |
| **Precio entrada** | $149 USD/mes/servidor | Gratis (vía Aiven) | Trial hasta 3 DB; comercial no público | 95 €/año/usuario | Por definir (sugerencia: $29 USD/dev/mes) |
| **Modelo de deployment** | SaaS y on-premise (Enterprise) | SaaS (Aiven) | SaaS + agente en BD | SaaS (paste manual) | Self-hosted Docker + SaaS planeado |
| **Mecanismo de detección** | Heurísticas + ML propietario | Modelo IA propietario opaco | ML sobre métricas de runtime | Reglas heurísticas sobre el plan | Motor determinístico (Python) + LLM solo para explicar |
| **Validación de recomendación** | Análisis "What If?" | No documentada públicamente | A/B real en producción | Ninguna (solo sugiere) | EXPLAIN antes/después en sandbox efímero |
| **Sanitización de datos** | Filtros PII en logs (tier alto) | Sensor declarado no intrusivo | Solo métricas agregadas | Planes opcionalmente no almacenados | Sanitización fuerte de literales antes de cualquier LLM |
| **Modo offline** | No (Enterprise on-prem disponible) | No | No (requiere agente conectado) | Parcial (pegar plan manual) | Sí (bundle JSON exportable sin conexión) |
| **Idioma de la UI / docs** | Inglés | Inglés | Inglés | Inglés | Español + Inglés (foco LATAM) |
| **Workload analysis** | Sí (continuo, vía agent) | Sí (sensor pasivo) | Sí (métricas internas) | No | Sí (parser de `pg_stat_statements` con score por tiempo total) |
| **Detección de anti-patterns explícita** | Sí (advisors) | Parcial (rewrite IA) | No | Sí (tips heurísticos) | Sí (catálogo público de 15 detectores documentados) |

---

## 4. Dónde PgPilot tiene ventaja

Ningún competidor combina motor determinístico transparente + sanitización fuerte + validación en sandbox + foco LATAM. Cada uno cubre un subconjunto:

- **Frente a pganalyze:** PgPilot es accesible para developers solos o equipos pequeños que no pueden pagar $149/mes/servidor. La sanitización de literales antes del LLM es defensiva por diseño (no es un filtro opcional). El motor es código abierto-leíble dentro del producto: el equipo del cliente puede auditar la regla de cada detector.
- **Frente a EverSQL:** el motor determinístico decide, el LLM explica. Si el LLM contradice al motor, gana el motor. Esto es el opuesto al modelo EverSQL donde la IA es la lógica de decisión.
- **Frente a DBtune:** PgPilot ataca el lado opuesto del problema (queries e índices, no parámetros de configuración). No compiten directamente; un equipo podría usar ambos en complemento.
- **Frente a pgMustard:** PgPilot ofrece workload analysis (`pg_stat_statements`) y comparativo before/after en sandbox, no solo un análisis de plan individual. La interfaz en español y la documentación local son diferenciadores para LATAM.
- **Diferenciador defendible transversal:** el modo offline (bundle JSON sin conexión a la BD productiva) es un argumento de venta concreto para fintech, healthtech y govtech LATAM que no pueden compartir credenciales con un SaaS extranjero.

---

## 5. Dónde la competencia tiene ventaja sobre PgPilot

Honestidad — la rúbrica del proyecto exige no afirmar superioridad en todas las dimensiones:

- **pganalyze** tiene años de telemetría histórica, integraciones maduras con cloud providers, retención de 100 días, y compliance enterprise. PgPilot es producto naciente sin track record en producción.
- **EverSQL** cubre Postgres y MySQL. PgPilot solo Postgres en v1.
- **DBtune** optimiza configuración del servidor (`shared_buffers`, `work_mem`) — área que PgPilot no toca y donde una mala configuración puede anular cualquier optimización de queries.
- **pgMustard** cuesta 95 €/año/usuario. Es muy difícil competir en precio contra eso para un developer individual.
- Ninguno de los competidores tiene mercado LATAM validado todavía, pero PgPilot tampoco aún a nivel comercial. Señal de las 3 entrevistas F6/F7/F8: los 3 entrevistados son LATAM y **ninguno** usa pganalyze, EverSQL ni DBtune (Carlos: Rapid7/CloudWatch; Jos: ninguna; Raúl: Grafana+Datadog+pgAdmin). La hipótesis del foco regional tiene señal cualitativa fuerte; falta validación comercial (paying customers post-Demo Day).

---

## 6. Conclusión

PgPilot no compite por ser "el más completo" ni "el más barato" — compite por ser el primero en ofrecer recomendaciones de queries e índices para Postgres con motor determinístico transparente, guardrails fuertes sobre el LLM, validación en sandbox antes de mostrar al usuario, y foco específico en developers LATAM con datos sensibles. La estrategia es coexistir con DBtune (parámetros) y complementar pganalyze para equipos que no pueden costear su tier Production, no reemplazar al líder del mercado.

---

## Fuentes

- pganalyze — <https://pganalyze.com> y <https://pganalyze.com/pricing>
- EverSQL (Aiven) — <https://www.eversql.com> y comunicado de adquisición de Aiven
- DBtune — <https://www.dbtune.com>, <https://docs.dbtune.com/aws-rds/>, posts del blog DBtune sobre Aiven y AWS RDS
- pgMustard — <https://www.pgmustard.com> y <https://www.pgmustard.com/pricing>
- Contexto adicional consultado: Datadog Database Monitoring ($70/host) para Postgres y MySQL (<https://www.datadoghq.com/product/database-monitoring/>), usado como referencia de mercado pero no incluido en la tabla por su scope más amplio (APM completo, no solo BD).

---

> **Nota de mantenimiento:** este archivo y `business/competencia.docx` contienen la misma investigación. Si actualizas el `.md`, refleja los cambios también en el `.docx` (o regenera el `.docx` desde el `.md`) para que no diverjan.

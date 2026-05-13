# PgPilot — Diferenciador defendible

> Ticket F14 del backlog. Proyecto final SIS2404 — Bases de Datos Avanzadas, Universidad Anáhuac Querétaro. Mayo 2026. Depende de [`competencia.md`](./competencia.md) y [`pricing.md`](./pricing.md).

## 1. La pregunta correcta

La pregunta que un evaluador o cliente potencial hace primero es: **"¿por qué un developer elegiría PgPilot sobre pegarle el query a ChatGPT?"**. Esa es la baseline real, no pganalyze ni EverSQL — el competidor verdadero es el LLM genérico gratis.

La respuesta tiene que ser defendible. Defendible quiere decir: el competidor sabe que existe y aun así no puede copiarlo en 90 días sin rehacer arquitectura. Los cuatro defensores reales de PgPilot son arquitectónicos, no de superficie:

1. Motor determinístico que decide, LLM que solo explica.
2. Sanitización fuerte de literales antes de cualquier llamada al LLM.
3. Validación en sandbox efímero antes de mostrar la recomendación.
4. Modo offline / bundle JSON sin conexión a la BD productiva.

A los que se suma un quinto, transversal y comercial:

5. Foco LATAM (idioma, soporte en horario hábil regional, mercado-específico).

---

## 2. Diferenciadores que NO contamos como defendibles

Honestidad obligada (espíritu de F3). Estos sonarían bien en una slide pero no aguantan presión:

- ❌ **"Más barato que pganalyze."** El precio se copia en una semana. Si pganalyze hoy decide cobrar $19 USD/dev/mes mañana, nuestra ventaja desaparece. El precio es **resultado** de la estructura per-seat, no la ventaja.
- ❌ **"Mejor UI."** Subjetivo, imitable, y cualquier ronda de inversión del competidor lo neutraliza contratando un diseñador senior.
- ❌ **"Usamos IA / LLMs."** Todo el mercado usa IA. Decir "usamos IA" en 2026 es decir "usamos internet" en 2002.
- ❌ **"Open source."** PgPilot no es open source todavía (decisión pendiente del equipo). Aunque lo fuera, open source per se no es defensa: pganalyze también podría liberar su engine. La defensa real está en la **arquitectura**, no en la licencia.
- ❌ **"Más detectores que la competencia."** Hoy tenemos 18 anti-patterns en el catálogo (D2-D22 + C1). Cualquiera puede sumar 50 detectores en 6 meses. La defensa no es la cantidad, es el **shape de cómo se detecta** — y eso sí está en el motor determinístico.

---

## 3. Los cuatro defensores arquitectónicos

### 3.1 Motor determinístico que decide, LLM que solo explica

**Qué es:** las decisiones de detección viven en código Python puro testeable (`/motor/detectors/`). El LLM se invoca **después** de que el motor ya tiene el resultado, y solo para generar prosa pedagógica. Si el LLM contradice al motor, gana el motor (regla R1 del proyecto, documentada en `RULES.md`).

**Por qué es difícil de copiar:**

- Cambiar a este shape requiere reescribir la pipeline central de un competidor que hoy delega decisión al LLM (EverSQL). Eso es un proyecto de 6-12 meses para una empresa establecida porque rompe contratos y métricas.
- Una vez que entrenaste a tus clientes en que "la herramienta puede alucinar", revertir esa percepción cuesta más caro que rehacer el producto.
- pganalyze ya hace algo parecido (heurísticas determinísticas + advisors), pero su producto NO tiene un LLM en el pipeline — la prosa la escriben humanos. Si quieren agregar LLM, tienen que pelearse con clientes Enterprise que pidieron "no LLM" por compliance.

**Defensa frente a "¿y si ChatGPT?":** ChatGPT alucina índices, alucina columnas, alucina sintaxis. PgPilot **no puede** alucinar índices porque la sugerencia viene del motor; el LLM solo puede explicar lo que ya existe. R3 lo formaliza: toda salida del LLM se valida estructuralmente antes de mostrarse.

### 3.2 Sanitización fuerte de literales antes del LLM

**Qué es:** la regla R4 del proyecto declara absoluta: ninguna query llega al LLM con sus literales originales. `ia/sanitizer.py` reemplaza strings, números, fechas, UUIDs y emails con placeholders **antes** de cualquier llamada. Tests B11 verifican con `grep` que ningún dato sensible aparece en el output del sanitizador (test agresivo: email real, RFC mexicano, número de tarjeta).

**Por qué es difícil de copiar:**

- ChatGPT y herramientas tipo Cursor mandan todo el texto del contexto a Anthropic / OpenAI. Para empresas con regulación (LGPD en Brasil, LFPDPPP en México, GDPR si tienen operación EU, HIPAA en healthtech), eso es bloqueador legal.
- Implementar sanitización seria requiere parser SQL (sqlglot), no regex sobre el SQL crudo. Y requiere mantenerlo para cada versión de Postgres porque nuevos tipos de literales aparecen.
- Anthropic / OpenAI publican guidelines de "data handling" pero el cliente legal no acepta "el proveedor promete que no usa tu data" cuando lo que necesita es "el dato nunca salió del perímetro." Esa diferencia es la que PgPilot sí cumple.

**Defensa frente a "¿y si ChatGPT?":** pegar la query con datos reales a ChatGPT viola compliance en muchas empresas. PgPilot ofrece un camino auditable: el sanitizer es código abierto-leíble del producto, no una promesa de proveedor.

### 3.3 Validación en sandbox efímero antes de mostrar

**Qué es:** cada recomendación pasa por un segundo Postgres efímero (`/sandbox`) donde se aplica el `CREATE INDEX` o rewrite propuesto y se compara `EXPLAIN` antes/después. Si el planner no usa el índice o el costo no baja, la recomendación se **descarta** silenciosamente (con log para debugging). R6 prohíbe copiar datos: el sandbox monta schema vacío con stats falseadas vía `pg_restore_relation_stats`.

**Por qué es difícil de copiar:**

- Requiere infra de sandbox con cleanup automático y timeouts (E5, E6 del backlog). pganalyze tiene "What If?" pero corre en producción del cliente (no sandbox aislado).
- Falsear stats sin copiar datos es una decisión arquitectónica fuerte: muchas herramientas DBA tradicionales necesitan datos reales para razonar, lo cual choca con privacidad.
- El cliente entiende intuitivamente que "antes de mostrarte la sugerencia, la probamos en una BD limpia" es más seguro que "te sugerimos esto, pruébalo tú."

**Defensa frente a "¿y si ChatGPT?":** ChatGPT no puede validar nada — su output es texto. PgPilot ejecuta el output y mide el costo del plan resultante. Esa es la diferencia entre "sugerencia plausible" y "sugerencia verificada."

### 3.4 Modo offline / bundle JSON

**Qué es:** el módulo `/conector` puede operar en modo offline: el cliente exporta un bundle JSON (schema + stats + sizes) corriendo `export_bundle()` en su entorno, y nos lo comparte. PgPilot trabaja contra ese bundle sin conexión a la BD productiva del cliente. R7 ya obliga read-only en modo online; el modo offline es la versión nuclear: **nunca tocamos su BD**.

**Por qué es difícil de copiar:**

- Requiere desacoplar el motor del extractor de stats. Si el competidor diseñó su producto asumiendo "siempre hay una conexión viva," refactorizar para offline es trabajo de meses.
- Es un argumento de venta literal con un sector que paga: fintech y healthtech LATAM no firman SOC2 con un SaaS extranjero que pide credenciales de su Postgres productivo. El modo offline elimina el bloqueador.
- El bundle JSON es portable, versionable y auditable: el cliente puede ver línea por línea qué se compartió. Otras herramientas piden "deploy nuestro agente persistente en tu cluster" lo cual no pasa los mismos filtros.

**Defensa frente a "¿y si ChatGPT?":** ChatGPT no tiene contexto de tu schema ni stats. PgPilot offline trabaja con tu metadata real sin que tu data se mueva. Para una fintech mexicana mediana es la diferencia entre "podemos usar la herramienta" y "no la podemos ni probar."

---

## 4. Foco LATAM (defensor comercial transversal)

No es arquitectónico — es de posicionamiento. Pero es real y difícil de copiar para un competidor extranjero porque:

- **Idioma:** producto, docs, catálogo de patterns, soporte y onboarding en español. pganalyze tiene exactamente 0 contenido en español. Cuando un dev en México busca "anti-patrón Postgres select estrella", aterriza en PgPilot, no en pganalyze.
- **Horario hábil de soporte:** PgPilot responde tickets en CST/CDT/BRT. pganalyze responde en EST/PST con delay 12-24 h para clientes LATAM por zona horaria.
- **Conocimiento del mercado:** los founders entienden el ciclo de procurement de una fintech mexicana, los topes de presupuesto, las restricciones cambiarias para pagar suscripciones en USD, y los stacks dominantes (Node + Postgres en fintech mexicana, Spring + Postgres en bancos brasileños). Eso no se compra, se vive.
- **Network LATAM:** acceso a la comunidad Postgres MX, devs de Nubank, Kavak, Rappi, MercadoLibre, Konfio, Clip. Una sales motion fría desde San Francisco no compite con un mensaje de WhatsApp de alguien conocido.

**Trade-off honesto:** este diferenciador es real pero **se erosiona si un competidor decide entrar a LATAM en serio**. pganalyze podría contratar un Country Manager LATAM en 2027 y replicar todo lo del idioma + horario en 6 meses. La defensa entonces baja a los cuatro arquitectónicos.

---

## 5. Combinación, no suma

Ninguno de los cuatro defensores arquitectónicos es único de PgPilot por separado:

- pganalyze tiene partes determinísticas (advisors).
- Algunas DBA tools tienen sanitización opcional.
- pganalyze tiene "What If?" (no sandbox aislado, pero relacionado).
- Ciertos productos enterprise tienen modo offline parcial.

Lo único que es difícil es **combinar los cuatro en un solo producto con el mismo shape arquitectónico**, porque cada uno restringe el diseño de los otros:

- Si quieres sanitización fuerte, no puedes pasarle el SQL crudo al LLM → eso te empuja al motor determinístico.
- Si quieres motor determinístico, necesitas validación porque el motor también puede equivocarse → eso te empuja al sandbox.
- Si quieres sandbox sin copiar datos, necesitas conector que extraiga stats sin copiar filas → eso te empuja al modo offline.

La integridad arquitectónica es la defensa. **Replicar una pieza es fácil; replicar el sistema entero exige rehacer el producto**, y un competidor establecido prefiere no romper su producto que ya funciona.

---

## 6. Por qué un dev elegiría PgPilot sobre ChatGPT (versión corta)

| Pregunta | ChatGPT | PgPilot |
|---|---|---|
| ¿Mis datos productivos salen del perímetro? | Sí, todo el texto se manda al proveedor | No, los literales se sanitizan antes y el modo offline elimina la conexión |
| ¿La sugerencia está validada? | No, es texto plausible | Sí, sandbox confirma que el planner usa el índice y el costo baja |
| ¿La sugerencia puede ser una alucinación? | Sí, regularmente | No, el motor decide, el LLM solo explica |
| ¿Tiene contexto de mi schema y stats reales? | No | Sí, vía conector o bundle JSON |
| ¿Habla mi idioma y entiende mi mercado? | Inglés genérico | Español + foco LATAM |

Esa tabla es el slide del minuto 4 del pitch.

---

## Fuentes y referencias internas

- Regla R1, R3, R4, R6, R7 — `RULES.md` raíz del proyecto
- Implementación de sanitizador — `ia/sanitizer.py` + tests `tests/ia/test_privacidad.py`
- Implementación de sandbox — `sandbox/` módulo (B15, B16, C3, E5, E6)
- Implementación de motor determinístico — `motor/detectors/` (C1, D2-D22, 18 detectores)
- Modo offline — `conector/offline.py` (B6)
- Investigación competitiva — [`competencia.md`](./competencia.md) §4
- Modelo de pricing — [`pricing.md`](./pricing.md) §1 (per-seat justification)

---

> **Nota de mantenimiento:** este archivo y `business/diferenciador.docx` contienen el mismo análisis. Si la arquitectura del producto cambia (por ejemplo, si el LLM gana más responsabilidad de decisión), este documento debe revisarse — el defensor #1 se debilitaría y habría que rearmar la narrativa.

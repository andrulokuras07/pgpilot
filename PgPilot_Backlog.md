# PgPilot — Backlog Secuencial de Actividades

**Cómo usar este documento:** las actividades están en orden de cascada. Cualquier persona puede tomar la siguiente actividad disponible que no tenga dependencias bloqueantes pendientes. Cada actividad incluye:
- **Qué hacer** (descripción concreta)
- **Depende de** (qué actividades previas deben estar terminadas)
- **Hecho cuando** (criterio objetivo de finalización)

Las actividades se agrupan en 6 fases. Dentro de cada fase, varias actividades pueden hacerse en paralelo si sus dependencias ya están cubiertas.

---

## FASE 0 — Setup del proyecto

### A1. Crear repositorio Git
- **Qué hacer:** crear repo en GitHub (privado o público), agregar a los 5 miembros como colaboradores, proteger rama `main` para que requiera Pull Request, agregar `.gitignore` con node_modules, __pycache__, .env, .venv, dist, build.
- **Depende de:** nada
- **Hecho cuando:** los 5 miembros pueden clonar el repo y la rama `main` rechaza push directo.

### A2. Definir estructura de carpetas
- **Qué hacer:** crear las carpetas `/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`, `/frontend`, `/docs`, `/docs/patterns`, `/business`, `/tests`, `/scripts`. Hacer commit inicial con un README.md vacío en cada una para que existan en Git.
- **Depende de:** A1
- **Hecho cuando:** las carpetas existen en `main`.

### A3. Configurar canal de comunicación del equipo
- **Qué hacer:** crear grupo dedicado en Discord/WhatsApp/Slack solo para el proyecto (no mezclar con conversación social). Agendar el horario fijo del standup diario de 15 minutos.
- **Depende de:** nada
- **Hecho cuando:** los 5 están en el grupo y tienen el horario del standup acordado.

### ~~A4. Configurar tablero de tareas~~ — ELIMINADA
- **Motivo:** el equipo se coordinará con `PgPilot_Backlog.md` + `PROGRESS.md` + GitHub Issues. No se usará tablero externo (Trello/Notion/Linear).
- **Sustituto:** la tabla "Actividades en curso" de `PROGRESS.md` cumple la función de visibilidad.

### A5. Levantar AppDB (la BD demo oficial)
- **Qué hacer:** descargar el repositorio Docker que entregue el profesor con AppDB. Correr `docker compose up -d` en la máquina de cada miembro. Conectarse con DBeaver/pgAdmin/psql al puerto 5432 y verificar que las tablas tengan datos. Ejecutar `SELECT count(*) FROM pg_stat_statements` y verificar que devuelve queries.
- **Depende de:** nada (no depende de Git)
- **Hecho cuando:** los 5 miembros tienen AppDB corriendo localmente y pueden hacer SELECT a sus tablas.

### A6. Crear documento de decisiones del equipo (MODIFICADA)
- **Qué hacer:** crear `docs/decisiones.md` dentro del repo con secciones: stack elegido, decisiones de arquitectura, trade-offs, log de bloqueos. Mantenerlo vivo durante el proyecto. Esto alimenta después F2 (documento de arquitectura).
- **Depende de:** A2
- **Hecho cuando:** el archivo existe en `main` con las 4 secciones inicializadas (aunque estén vacías de contenido).
- **Nota:** anteriormente era un Google Doc/Notion compartido; se movió al repo para tener todo versionado en Git.

### ~~A7. Asignar roles del equipo~~ — ELIMINADA
- **Motivo:** el equipo trabajará sin asignación rígida de roles. Cualquiera puede tomar cualquier actividad del backlog que no tenga dependencias bloqueantes.
- **Riesgo asumido:** distribución desigual de commits (visible en `git shortlog -sn` durante F29) y posible falta de dueño claro al responder Q&A del Demo Day. El equipo asume este riesgo conscientemente.

### A8. Definir stack técnico y documentarlo
- **Qué hacer:** decidir y escribir en el doc de A6: lenguaje del backend (Python recomendado), framework (FastAPI), driver de Postgres (psycopg vs asyncpg), parser SQL (sqlglot vs pglast), framework frontend (React + Vite), editor SQL (Monaco), proveedor de LLM (Anthropic Claude API u OpenAI). Justificar cada decisión con 1-2 líneas porque la rúbrica lo evalúa.
- **Depende de:** A6
- **Hecho cuando:** el stack está documentado con justificación de cada elemento.

### A9. Crear esqueleto de docker-compose
- **Qué hacer:** escribir `docker-compose.yml` raíz con tres servicios: `appdb` (Postgres con AppDB), `sandbox` (Postgres vacío para validación), `backend` (servicio Python que se arma después). Por ahora solo los Postgres, el backend va con un placeholder. Documentar puertos: AppDB en 5432, sandbox en 5433.
- **Depende de:** A2, A5
- **Hecho cuando:** `docker compose up` levanta dos contenedores Postgres sanos.

---

## FASE 1 — Cimientos técnicos (vertical slice mínimo)

### B1. Conector a Postgres con read-only forzado
- **Qué hacer:** crear módulo Python en `/conector` que reciba parámetros de conexión y devuelva un pool de conexiones psycopg. Forzar `SET TRANSACTION READ ONLY` en cada conexión. Agregar timeout de 5 segundos a las queries. Escribir test que intente un INSERT y verifique que falla.
- **Depende de:** A8, A9
- **Hecho cuando:** un script puede conectarse a AppDB, hacer SELECT, y un test confirma que INSERT lanza error.

### B2. Extractor de schema básico
- **Qué hacer:** función `get_schema(db_name)` que devuelve para cada tabla: nombre, lista de columnas con tipo, lista de índices con columnas y método (btree/gin/etc.), foreign keys. Usar `information_schema` y `pg_indexes`. NO incluir todavía pg_stats ni tamaños.
- **Depende de:** B1
- **Hecho cuando:** la función devuelve un dict estructurado para AppDB con todas sus tablas.

### B3. Extractor de tamaños de tabla
- **Qué hacer:** ampliar el extractor para incluir tamaño en filas (`reltuples` de `pg_class`) y bytes (`pg_total_relation_size`). Decidir si las tablas son "pequeñas" (<100k filas), "medianas" (100k-1M) o "grandes" (>1M). El detector de seq scan necesita saber esto.
- **Depende de:** B2
- **Hecho cuando:** la función devuelve tamaño y categoría para cada tabla.

### B4. Extractor de pg_stats
- **Qué hacer:** ampliar el extractor para incluir, por columna: `n_distinct`, `null_frac`, `most_common_vals`, `correlation`. Estos datos son críticos para calcular selectividad y recomendar índices que valgan la pena. Manejar el caso donde una tabla nunca ha tenido `ANALYZE` (pg_stats vacío).
- **Depende de:** B2
- **Hecho cuando:** para cada columna de cada tabla, la función devuelve sus estadísticas o un valor explícito de "sin estadísticas".

### B5. Cache de metadata por hash de schema
- **Qué hacer:** después de extraer schema completo, calcular un hash del resultado (md5 sobre el JSON serializado) y guardar en archivo local `cache/{hash}.json`. La siguiente extracción del mismo schema lee del cache. Botón explícito de "invalidar cache" para forzar re-extracción.
- **Depende de:** B2, B3, B4
- **Hecho cuando:** la segunda extracción consecutiva tarda menos de 100ms.

### B6. Modo offline del conector
- **Qué hacer:** aceptar como input un archivo (output de `pg_dump --schema-only` más un export de `pg_stats` en CSV) en lugar de una conexión viva. El producto debe funcionar sin conexión a producción. Esto es feature de venta para empresas con datos sensibles.
- **Depende de:** B5
- **Hecho cuando:** el extractor produce el mismo dict de metadata desde un dump que desde conexión viva.

### B7. Parser de EXPLAIN JSON — estructura básica
- **Qué hacer:** crear módulo en `/motor` que reciba el output de `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` y lo convierta en un árbol de nodos propios. Cada nodo con: tipo (Seq Scan, Index Scan, Nested Loop, Hash Join, Sort, etc.), tabla, costo total, filas estimadas, filas reales, tiempo, y referencia a hijos. NO basta con guardar el JSON crudo, la rúbrica lo dice explícito.
- **Depende de:** A8 (no depende del conector)
- **Hecho cuando:** un test parsea 5 planes de EXPLAIN distintos y la estructura tiene la forma correcta.

### B8. Parser de EXPLAIN — todos los tipos de nodo
- **Qué hacer:** ampliar el parser para soportar todos los tipos de nodo que aparecen en AppDB: Seq Scan, Index Scan, Index Only Scan, Bitmap Heap Scan, Bitmap Index Scan, Nested Loop, Hash Join, Merge Join, Sort, Hash, Aggregate, Limit, Subquery Scan, CTE Scan, Materialize. Cada uno con sus campos relevantes.
- **Depende de:** B7
- **Hecho cuando:** los 16 tipos de nodo se parsean y tienen sus campos accesibles.

### B9. Helper "buscar nodo por tipo en el árbol"
- **Qué hacer:** función `find_nodes(tree, node_type)` que recorre recursivamente el árbol y devuelve todos los nodos del tipo pedido. Esto es la base para que los detectores trabajen sobre estructura, no sobre strings.
- **Depende de:** B8
- **Hecho cuando:** un test verifica que encuentra todos los Seq Scan en un plan complejo con joins anidados.

### B10. Sanitizador de literales
- **Qué hacer:** función en `/ia` que recibe SQL crudo y devuelve SQL con placeholders. Reemplaza: strings entre comillas → `$LITERAL_1`, números → `$LITERAL_2`, fechas (formato ISO o tipo) → `$LITERAL_3`, UUIDs → `$LITERAL_4`, emails (regex) → `$LITERAL_5`. Devolver también un mapa para reconstruir si hace falta.
- **Depende de:** A8 (no depende de nada técnico previo)
- **Hecho cuando:** un test mete un query con email y RFC reales y verifica que el output no los contiene.

### B11. Test de privacidad del sanitizador
- **Qué hacer:** test específico que sanitiza un query con datos sensibles reales (email tipo `juan@empresa.com`, RFC, número de tarjeta), guarda el output en un archivo, y verifica con grep que ninguno de los datos originales aparece. Esto es prueba para Q&A: "¿cómo garantizan privacidad?".
- **Depende de:** B10
- **Hecho cuando:** el test pasa.

### B12. Setup del frontend con Vite + React + Monaco
- **Qué hacer:** crear proyecto en `/frontend` con `npm create vite@latest -- --template react`. Instalar `@monaco-editor/react`. Hacer página principal con un editor que muestre SQL con syntax highlight. Tema oscuro estilo VS Code. Botón "Analizar" sin funcionalidad por ahora.
- **Depende de:** A8
- **Hecho cuando:** `npm run dev` levanta el editor en localhost:5173 y se puede escribir SQL con colores.

### B13. Backend con un endpoint vacío
- **Qué hacer:** crear servidor FastAPI en `/backend` (o donde decidan que viva el orquestador). Endpoint `POST /analyze` que recibe `{query: string}` y devuelve por ahora `{detections: [], recommendations: []}`. Habilitar CORS para localhost:5173.
- **Depende de:** A8
- **Hecho cuando:** el endpoint responde con el JSON dummy desde curl o el frontend.

### B14. Frontend conectado al backend
- **Qué hacer:** al hacer clic en "Analizar" en el editor, el frontend hace POST al backend con la query y muestra el JSON crudo de respuesta en un panel lateral. Feo está bien.
- **Depende de:** B12, B13
- **Hecho cuando:** escribes "SELECT 1", clic, y aparece el JSON dummy en pantalla.

### B15. Sandbox Postgres efímero
- **Qué hacer:** segundo contenedor Postgres en docker-compose configurado como sandbox. Script Python que dado un schema (de B6) crea un schema temporal en sandbox con las tablas vacías pero las stats falseadas usando `ALTER TABLE ... SET STATISTICS` y `pg_set_*_stats`. NO se copian datos.
- **Depende de:** B6, A9
- **Hecho cuando:** un test crea un schema temporal con 3 tablas y stats falseadas, ejecuta `EXPLAIN SELECT...`, recibe un plan razonable.

### B16. Función "ejecutar EXPLAIN en sandbox"
- **Qué hacer:** función que recibe un schema setup y una query, monta el schema temporal, corre `EXPLAIN` (sin ANALYZE, no necesita filas reales), devuelve el plan, y limpia el schema temporal. Timeout duro de 5 segundos.
- **Depende de:** B15
- **Hecho cuando:** la función corre `EXPLAIN` sobre AppDB schema y devuelve un plan en menos de 5 segundos.

---

## FASE 2 — Primer flujo end-to-end (vertical slice completo)

### C1. Detector #1: Seq Scan en tabla grande con índice disponible
- **Qué hacer:** función pura que recibe el árbol del plan + metadata del schema y devuelve `Detection(found, confidence, evidence)`. Lógica: encuentra todos los nodos Seq Scan, para cada uno verifica si la tabla tiene >100k filas, y si existe un índice btree sobre la columna del filtro `WHERE`. La detección debe ser sobre la estructura del plan, NO sobre el texto del SQL. Esto es lo que dará el bonus de AppDB v2.
- **Depende de:** B4, B9
- **Hecho cuando:** test verde con un plan de seq scan sobre tabla grande con índice disponible (devuelve found=true) y otro con seq scan sobre tabla pequeña (devuelve found=false).

### C2. Recomendador de índice básico
- **Qué hacer:** función que recibe una detección de C1 y genera una recomendación con: SQL del CREATE INDEX, justificación (qué columna, por qué btree, etc.), impacto esperado en costo. La justificación viene de los datos de selectividad: `n_distinct / row_count` da la selectividad estimada.
- **Depende de:** C1
- **Hecho cuando:** dada una detección de seq scan, devuelve un objeto con SQL CREATE INDEX válido y justificación textual.

### C3. Validación del recomendador con sandbox
- **Qué hacer:** antes de mostrar la recomendación, ejecutar EXPLAIN en sandbox aplicando el CREATE INDEX y comparar costo. Si el planner sigue ignorando el índice o el costo no baja, descartar la recomendación. Devolver veredicto: "validada" / "descartada con razón".
- **Depende de:** C2, B16
- **Hecho cuando:** una recomendación válida pasa la validación con costo reducido confirmado.

### C4. Prompt estructurado al LLM v1
- **Qué hacer:** módulo en `/ia` que recibe `{detección, plan_árbol, recomendación_motor, query_sanitizada}` y construye un prompt al LLM pidiendo: explicación pedagógica del problema, propuesta de rewrite alternativo (si aplica), output estricto en JSON con schema definido. El LLM nunca recibe la query cruda.
- **Depende de:** C2, B10
- **Hecho cuando:** el LLM responde con un JSON válido para una detección de seq scan.

### C5. Validación de respuesta del LLM con Pydantic
- **Qué hacer:** definir modelo Pydantic con campos esperados (explanation: str, suggested_rewrite: str | None, confidence: float). Si el LLM devuelve algo mal formado, reintentar una vez. Si vuelve a fallar, descartar la respuesta del LLM y usar plantilla del motor.
- **Depende de:** C4
- **Hecho cuando:** un test mete una respuesta JSON malformada y el sistema cae al modo plantilla sin crashear.

### C6. Validación cruzada de sugerencias del LLM
- **Qué hacer:** cuando el LLM propone un índice o rewrite, validar antes de mostrar al usuario: las columnas existen en el schema (consulta a B2), el índice no existe ya (consulta a B2), la sintaxis SQL es válida (parsear con sqlglot), el sandbox confirma que el planner usaría el índice (consulta a B16). Si cualquiera falla, descarte y caída a output del motor determinístico.
- **Depende de:** C5, B16, B2
- **Hecho cuando:** test plantando una respuesta del LLM con un índice que ya existe verifica que se descarta.

### C7. Modo "LLM apagado" con plantillas
- **Qué hacer:** toggle global que desactiva el LLM. En ese modo, las explicaciones se generan con plantillas string formateadas con datos de la detección. Demuestra resiliencia y es defensa en pitch ("nuestro producto funciona sin IA").
- **Depende de:** C2
- **Hecho cuando:** con el toggle apagado, el sistema devuelve recomendación con explicación legible (aunque más seca) sin llamar al LLM.

### C8. Logs estructurados de interacciones con LLM
- **Qué hacer:** cada llamada al LLM se loggea en archivo JSON estructurado con: prompt enviado (sanitizado), respuesta recibida, validaciones que pasaron, validaciones que fallaron, sugerencia final mostrada. Sirve para debugging y para Q&A.
- **Depende de:** C6
- **Hecho cuando:** después de un análisis, existe un log JSON con todos los campos.

### C9. Endpoint /analyze conectando todo
- **Qué hacer:** el endpoint que era dummy ahora orquesta: recibe query → sanitiza → conecta a AppDB → extrae plan con EXPLAIN → parsea → corre detector C1 → si hay detección, genera recomendación → valida con sandbox → llama al LLM → valida respuesta → devuelve JSON estructurado al frontend.
- **Depende de:** B14, C1, C3, C6, C8
- **Hecho cuando:** POST a /analyze con una query con seq scan devuelve un objeto con detección, recomendación validada, y explicación del LLM.

### C10. Frontend muestra detecciones en tarjetas
- **Qué hacer:** el panel lateral del frontend deja de mostrar JSON crudo. Renderea cada detección como una "tarjeta" con: título del problema, explicación, recomendación (con botón "copiar SQL"), nivel de confianza. Estilo VS Code/DBeaver con tema oscuro.
- **Depende de:** C9
- **Hecho cuando:** pegar una query con seq scan en el editor muestra una tarjeta limpia con la recomendación copiable.

### C11. Comparativo before/after en frontend
- **Qué hacer:** debajo de cada tarjeta de recomendación, mostrar dos paneles lado a lado: plan original y plan modificado (con el índice aplicado en sandbox). Resaltar costos: "antes 45,231 → después 287 (158x mejora)". Esto es la prueba viva de la rúbrica.
- **Depende de:** C10, C3
- **Hecho cuando:** la tarjeta muestra el comparativo numérico con el plan en formato legible.

### C12. PRUEBA INTEGRAL DEL SLICE
- **Qué hacer:** los 5 miembros, cada uno en su máquina, levantan el producto con `docker compose up`, abren el frontend, pegan una query plantada de AppDB con seq scan, y verifican que ven la detección, recomendación, comparativo, y explicación. Si falla en una sola máquina, debugging colectivo hasta que corra en las 5.
- **Depende de:** C11
- **Hecho cuando:** las 5 máquinas pueden ejecutar el flujo end-to-end exitosamente.

---

## FASE 3 — Ancho de detectores

### D1. Catálogo de patterns documentado (esqueleto)
- **Qué hacer:** crear archivo `/docs/patterns/README.md` con plantilla para cada anti-pattern: nombre, descripción del problema, regla de detección, recomendación, ejemplo de query, ejemplo de plan donde aparece. La rúbrica pide explícitamente este catálogo.
- **Depende de:** C1
- **Hecho cuando:** el archivo existe con la plantilla y el primer pattern (seq scan) documentado completo.

### D2. Detector #2: Mismatch entre rows estimated y rows actual
- **Qué hacer:** detector que recorre el plan buscando nodos donde `rows_estimated` difiere de `rows_actual` en más de 10x. Evidencia: estadísticas obsoletas en la tabla. Recomendación: ejecutar `ANALYZE`. Documentar en /docs/patterns.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test sobre plan plantado, documentado en patterns.

### D3. Detector #3: Sort en disco
- **Qué hacer:** detector que busca nodos `Sort` con `Sort Method: external merge Disk`. Recomendación: aumentar `work_mem` o agregar índice que evite el sort. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D4. Detector #4: LIKE con wildcard al inicio
- **Qué hacer:** detector que busca nodos con filtro tipo `column LIKE '%texto'`. La detección requiere parsear el filtro del nodo (no el SQL crudo). Recomendación: índice de trigrams (pg_trgm) o búsqueda full-text. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D5. Detector #5: Función no-immutable en WHERE
- **Qué hacer:** detector que busca expresiones tipo `WHERE LOWER(column) = ...` o funciones VOLATILE/STABLE en filtros. Estas funciones impiden el uso de índices regulares. Recomendación: índice funcional sobre la expresión. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D6. Detector #6: OR sobre columnas de tablas distintas
- **Qué hacer:** detector que identifica patrones `WHERE t1.col = X OR t2.col = Y` en queries con joins. Recomendación: reescribir como `UNION` (o `UNION ALL` si aplica). Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D7. Detector #7: Subquery correlacionada
- **Qué hacer:** detector que busca `Subquery Scan` o `SubPlan` con dependencia de la query externa. Recomendación: reescribir como `JOIN` o `EXISTS`. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D8. Detector #8: Nested Loop con tabla externa grande
- **Qué hacer:** detector que busca nodos `Nested Loop` donde la tabla del lado externo tiene >10k filas. Cuando esto pasa, debería ser `Hash Join`. Recomendación: revisar work_mem o forzar plan con hint. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D9. Detector #9: SELECT * con pocas columnas usadas
- **Qué hacer:** detector que parsea el SQL (con sqlglot) y verifica si usa `SELECT *` cuando la query solo necesita algunas columnas. Cruzar con el plan: si hay un `Index Scan` y solo se usan columnas indexadas, hay oportunidad de `Index Only Scan`. Recomendación: especificar columnas + índice cubriente. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D10. Detector #10: Falta de índice cubriente
- **Qué hacer:** detector que busca queries de solo lectura (sin UPDATE/DELETE) que hacen `Index Scan` seguido de `Heap Fetch`. Si todas las columnas usadas en SELECT/WHERE pueden caber en el índice, recomendar índice cubriente con `INCLUDE`. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D11. Detector #11: Índice no usado por mismatch de tipo
- **Qué hacer:** detector que busca nodos con cast implícito en filtro (ej: `WHERE id = '5'` cuando id es int). Postgres no usa el índice cuando hay cast. Detectable porque el plan muestra Seq Scan a pesar de existir índice. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D12. Detector #12: CTE materializada innecesariamente
- **Qué hacer:** detector que busca `CTE Scan` en queries de solo lectura sobre Postgres 12+. Antes de PG12 las CTE siempre se materializaban; ahora pueden ser inline. Si la CTE se llama una sola vez y no es recursiva, recomendar `WITH ... AS NOT MATERIALIZED`. Documentar.
- **Depende de:** B9
- **Hecho cuando:** detector pasa test, documentado.

### D13. Recomendador de índices con selectividad real
- **Qué hacer:** ampliar C2 para considerar todos los detectores. Calcular selectividad de cada filtro usando `n_distinct` y `null_frac` de B4. Si la columna tiene 3 valores distintos en una tabla de 10M filas, NO recomendar índice (ruido). Para índices compuestos, ordenar columnas por selectividad descendente (más selectiva primero). Considerar índices parciales para filtros con WHERE constante repetido.
- **Depende de:** D2-D12, B4
- **Hecho cuando:** dado un plan con seq scan, el recomendador descarta la recomendación si la selectividad es baja, y propone orden correcto en compuestos.

### D14. Tests de cobertura sobre AppDB
- **Qué hacer:** identificar las 20 queries plantadas de AppDB (vienen documentadas en el repo del profe). Para cada una, escribir test que verifica que el detector correcto la identifica con la recomendación esperada. Llevar el número visible: "X de 20 detectadas" en un README de tests.
- **Depende de:** D2-D12
- **Hecho cuando:** existen 20 tests, mínimo 16 pasan (80% es la línea segura para el Criterio 2.1).

### D15. Sistema anti-falsos-positivos
- **Qué hacer:** correr el producto sobre 10 queries "sanas" (queries que no tienen anti-pattern) de AppDB y verificar que NO devuelve detecciones. Cada falso positivo cuesta -0.5 pts en la rúbrica hasta -3. Ajustar umbrales (ej: tabla "grande" >100k → >500k) si hace falta.
- **Depende de:** D14
- **Hecho cuando:** menos de 3 falsos positivos sobre 10 queries sanas.

---

## FASE 4 — Workload, sandbox completo y pulido

### E1. Parser de pg_stat_statements
- **Qué hacer:** módulo en `/workload` que recibe un export en CSV o JSON de la vista `pg_stat_statements` y parsea: query normalizada, calls, total_exec_time, mean_exec_time, rows.
- **Depende de:** A8
- **Hecho cuando:** dado un CSV de prueba con 50 queries, devuelve estructura con todos los campos.

### E2. Score de impacto por tiempo total
- **Qué hacer:** calcular score de cada query con `total_exec_time` (no por frecuencia). Una query que corre 10 veces y tarda 5s cada una (50s totales) duele más que una que corre 10,000 veces y tarda 1ms (10s totales). La rúbrica menciona esto explícito.
- **Depende de:** E1
- **Hecho cuando:** función devuelve top 10 por impacto y el orden es por total_exec_time descendente.

### E3. Endpoint /workload
- **Qué hacer:** endpoint POST que recibe el archivo de pg_stat_statements y devuelve top 10 con score, tiempo total, tiempo promedio, frecuencia, y query normalizada.
- **Depende de:** E2, B13
- **Hecho cuando:** endpoint responde con el top 10 estructurado.

### E4. Vista de workload en frontend
- **Qué hacer:** pestaña nueva en el frontend "Workload Analysis". Botón para subir el CSV de pg_stat_statements. Tabla clickeable con top 10 queries: columnas score, total time, avg time, calls, query preview. Click en una fila → abre el flujo individual de C9 con esa query precargada.
- **Depende de:** E3, C10
- **Hecho cuando:** subir el CSV demo carga la tabla y click en una fila analiza esa query.

### E5. Sandbox con cleanup automático
- **Qué hacer:** ampliar B16 para que cada análisis use un schema temporal único (ej: `analysis_{uuid}`), y al terminar haga `DROP SCHEMA ... CASCADE`. Garantizar que un crash a la mitad no deja schemas zombies (cleanup al startup).
- **Depende de:** B16
- **Hecho cuando:** correr 100 análisis seguidos no deja schemas residuales en el sandbox.

### E6. Sandbox con timeouts duros
- **Qué hacer:** cada operación contra sandbox (CREATE INDEX en sandbox, EXPLAIN, DROP) tiene timeout duro de 5 segundos. Si excede, abortar y devolver "validación inconclusa". No bloquear el thread principal.
- **Depende de:** E5
- **Hecho cuando:** un test que monta un schema lento confirma que aborta en 5s sin colgar.

### E7. Generador de comparativos before/after enriquecido
- **Qué hacer:** ampliar C11 para mostrar más detalle: tipo de nodos antes vs después (¿pasó de Seq Scan a Index Scan?), filas estimadas antes vs después, costo, tiempo si se midió. Resumen ejecutivo automático: "redujo costo estimado de X a Y (Zx mejora)".
- **Depende de:** C11
- **Hecho cuando:** las recomendaciones validadas muestran el comparativo enriquecido.

### E8. Aislamiento de errores en endpoint /analyze
- **Qué hacer:** envolver cada etapa del orquestador (extracción, parser, detector, validación, LLM) en try/except. Si una etapa falla, las demás siguen y el endpoint devuelve resultados parciales con flag de error. Nunca crashear el endpoint.
- **Depende de:** C9
- **Hecho cuando:** un test que rompe a propósito el LLM verifica que /analyze sigue devolviendo detecciones y recomendaciones determinísticas.

### E9. Frontend muestra estado de validaciones
- **Qué hacer:** cada tarjeta de recomendación muestra qué validaciones pasó (icono verde) o falló (icono rojo): "schema OK", "no duplica índice", "sintaxis válida", "sandbox confirma mejora". Esto es la respuesta visual a "¿cómo evitan alucinaciones?".
- **Depende de:** C10, C6, E7
- **Hecho cuando:** cada tarjeta tiene los 4 indicadores de validación.

### E10. Documentación API del conector
- **Qué hacer:** archivo `/docs/conector.md` con: cómo usar el módulo, qué funciones expone, formato del modo offline, cómo invalidar cache. Incluir snippets de código.
- **Depende de:** B6
- **Hecho cuando:** alguien externo al equipo podría usar el módulo siguiendo el doc.

### E11. Documentación del motor determinístico
- **Qué hacer:** archivo `/docs/motor.md` con arquitectura del parser, lista de detectores con sus reglas, cómo agregar un detector nuevo. Cruzado con `/docs/patterns/`.
- **Depende de:** D14
- **Hecho cuando:** doc completo y enlazado desde README principal.

### E12. Documentación de la capa de IA
- **Qué hacer:** archivo `/docs/ia.md` con: qué se sanitiza y cómo, formato del prompt, schema de respuesta esperado, validaciones cruzadas aplicadas. Crítico para defensa.
- **Depende de:** C8
- **Hecho cuando:** doc completo.

### E13. Documentación del sandbox
- **Qué hacer:** archivo `/docs/sandbox.md` con: por qué no se copian datos, cómo se falsean stats, qué timeouts aplican, qué cleanup hace.
- **Depende de:** E6
- **Hecho cuando:** doc completo.

---

## FASE 5 — Documentación, negocio, presentación

### F1. README principal del repo
- **Qué hacer:** README.md raíz con: qué es PgPilot (3 líneas), cómo instalar (`docker compose up`), cómo correr el primer análisis, link a docs detalladas. Incluir badge de tests si hay CI. Asumir que quien lee NUNCA vio el repo.
- **Depende de:** E10, E11, E12, E13
- **Hecho cuando:** un compañero que clone fresco puede correr el producto siguiendo solo el README.

### F2. Documento de arquitectura
- **Qué hacer:** documento de 3-5 páginas en `/docs/arquitectura.md` (o usar la plantilla de entrega) con: diagrama de componentes (los 5 módulos y cómo se hablan), flujo de datos para análisis individual, flujo de datos para workload, decisiones técnicas con alternativas consideradas (psycopg vs asyncpg, sqlglot vs pglast, etc.), trade-offs identificados, limitaciones reconocidas, sección "Uso de IA en el desarrollo" (la rúbrica penaliza no declararlo con -5 pts).
- **Depende de:** A6, F1
- **Hecho cuando:** las 4 secciones de la rúbrica 1.2 están completas y el diagrama existe.

### F3. Investigación competitiva
- **Qué hacer:** investigar pganalyze (https://pganalyze.com), EverSQL (https://eversql.com), Dbtune (https://dbtune.com) y al menos uno más por su cuenta. Tabla comparativa con: precio, segmento de cliente, qué hacen bien, qué les falta, dónde PgPilot tiene ventaja. Honestidad: no decir que PgPilot es mejor en todo.
- **Depende de:** nada
- **Hecho cuando:** tabla con 4 competidores reales documentada en `/business/competencia.md`.

### F4. Lista de personas para entrevistar
- **Qué hacer:** identificar mínimo 5 candidatos a entrevistar (backend devs, tech leads, data engineers con Postgres en producción). Conocidos personales, LinkedIn, grupos de Discord de devs mexicanos. Apuntar nombre, rol, empresa, contacto. La meta es agendar 3 entrevistas; sobreplaneear da margen.
- **Depende de:** nada
- **Hecho cuando:** lista de 5 candidatos con contacto, agenda propuesta para 3 entrevistas.

### F5. Guion de entrevista
- **Qué hacer:** 8-10 preguntas concretas tipo: "¿cómo optimizas queries lentas hoy?", "¿qué herramientas usas?", "¿cuánto tiempo le dedicas al mes a esto?", "¿pagarías $X por una herramienta que lo automatice?", "¿qué te frenaría?". NO preguntar "¿usarías nuestro producto?" (la gente miente para no decepcionar). Preguntar sobre comportamiento pasado, no intenciones futuras.
- **Depende de:** nada
- **Hecho cuando:** guion documentado en `/business/guion-entrevistas.md`.

### F6. Entrevista 1 ejecutada y documentada
- **Qué hacer:** hacer la primera entrevista de 30 min, video o presencial. Documentar: nombre y rol del entrevistado, fecha, preguntas literales, respuestas resumidas, insights principales (no parafrasear todo, sí los puntos clave).
- **Depende de:** F4, F5
- **Hecho cuando:** documento `/business/entrevista-1.md` completo.

### F7. Entrevista 2 ejecutada y documentada
- **Qué hacer:** segunda entrevista, mismo formato.
- **Depende de:** F5
- **Hecho cuando:** documento `/business/entrevista-2.md` completo.

### F8. Entrevista 3 ejecutada y documentada
- **Qué hacer:** tercera entrevista, mismo formato.
- **Depende de:** F5
- **Hecho cuando:** documento `/business/entrevista-3.md` completo.

### F9. Definición de problema con datos
- **Qué hacer:** sección del documento de negocio que describa el problema con datos cuantitativos (no "las empresas tienen problemas con BDs"): "Carlos Méndez, CTO de fintech mexicana de 30 personas, dedica 4h semanales a revisar logs porque no tiene DBA, último incidente le costó 6h downtime y $50K". Apoyarse en hallazgos de las entrevistas.
- **Depende de:** F6, F7, F8
- **Hecho cuando:** problema descrito con frecuencia y severidad cuantificadas.

### F10. User persona detallado
- **Qué hacer:** user persona de "backend senior o tech lead de equipo 5-50 devs con Postgres en producción". Incluir: rol, contexto (tamaño empresa, industria), pain points específicos, herramientas que usa hoy, qué busca al evaluar una solución. Nombre ficticio realista.
- **Depende de:** F9
- **Hecho cuando:** user persona en `/business/persona.md`.

### F11. Modelo de pricing
- **Qué hacer:** definir tiers (Free, Pro, Team, Enterprise). Justificar cada precio con razonamiento ("cobramos $29/dev/mes porque pganalyze cobra equivalente a $40+ y nos posicionamos como alternativa LATAM"). Modelo per-seat ($20-50/dev/mes) recomendado siguiendo a Cursor/Copilot.
- **Depende de:** F3
- **Hecho cuando:** tabla de tiers con precio, comprador, features incluidas, justificación.

### F12. TAM/SAM/SOM
- **Qué hacer:** TAM (mercado global de DB tools, fuente Gartner o blog de inversión), SAM (porción atendible: empresas con Postgres en LATAM), SOM (1-5% del SAM en 3-5 años). No exacto, sí razonado y con fuentes citadas.
- **Depende de:** F3
- **Hecho cuando:** tres números con fuente y razonamiento documentado.

### F13. Go-to-market plan
- **Qué hacer:** plan concreto de cómo conseguir los primeros 10 clientes. NO "marketing en redes". Sí: "asistir a evento Fintech Mexico, agendar 30 demos, cerrar 5 pilotos gratis 90 días, convertir 3 a clientes pagados". Costo estimado del plan, timeline.
- **Depende de:** F11
- **Hecho cuando:** plan con canal de adquisición específico, paso a paso para los primeros 10 clientes con timeline, estrategia posterior.

### F14. Diferenciador defendible
- **Qué hacer:** identificar qué hace que un dev elija PgPilot sobre pegarle el query a ChatGPT. Defendibles: enfoque LATAM, sanitización fuerte (privacidad), modo offline para empresas con datos sensibles, validación con sandbox. NO defendibles: "más barato", "mejor UI", "usamos IA". Documentar.
- **Depende de:** F3, F11
- **Hecho cuando:** sección del doc de negocio con diferenciador y por qué es difícil de copiar.

### F15. Documento de negocio consolidado
- **Qué hacer:** integrar F3, F9, F10, F11, F12, F13, F14 en un solo documento (8-12 páginas) con índice. Usar la plantilla de entrega que les entregaron. Esto se entrega en PDF al final.
- **Depende de:** F3, F9, F10, F11, F12, F13, F14
- **Hecho cuando:** doc compilado y revisado.

### F16. Tests automatizados con coverage decente
- **Qué hacer:** asegurar que tests existentes (de detectores, sanitizador, parser, validaciones) cubren al menos 50% del código backend. Correr `pytest --cov` y documentar el número en README. Esto es bonus +3 pts.
- **Depende de:** D14, B11, C5, C6
- **Hecho cuando:** coverage reporta >50%.

### F17. Catálogo de patterns final
- **Qué hacer:** revisar `/docs/patterns/` para que los 12 (o los implementados) estén completos y coherentes. Cada uno con: nombre, problema, regla de detección, recomendación, ejemplo de query, ejemplo de plan donde aparece. Esto se entrega y la rúbrica lo pide explícito.
- **Depende de:** D1, D2-D12
- **Hecho cuando:** catálogo completo y consistente.

### F18. Probar producto en BD propia (caso de uso de sector)
- **Qué hacer:** levantar una segunda BD con un caso de uso distinto a AppDB (ej: e-commerce con productos/órdenes/clientes). Sembrar 3 queries problemáticas. Demostrar en la demo que el producto las detecta. Esto da 1 pt en Criterio 2.3 ("BD demo propia").
- **Depende de:** D14
- **Hecho cuando:** segunda BD documentada y queries detectadas.

### F19. Lista de 15 preguntas duras de Q&A
- **Qué hacer:** brainstorming en equipo de las preguntas más duras que pueden hacer otros equipos o el profe. Mínimo 15. Para cada una, redactar respuesta modelo trabajada con quien sabe del tema. Ejemplos imprescindibles: "¿cómo evitan alucinaciones?", "¿qué pasa si su LLM se cae?", "¿por qué un dev pagaría esto en vez de usar ChatGPT?".
- **Depende de:** F2, F15
- **Hecho cuando:** doc `/business/qa-prep.md` con 15 preguntas y respuestas.

### F20. Lista de 5 preguntas para atacar otros equipos
- **Qué hacer:** leer briefs de PgGuardian y PgVault. Preparar 5 preguntas técnicas inteligentes para cada equipo rival. Ejemplos: "¿cómo evitan falsos positivos en su detector de PII?", "si la BD del cliente tiene 100M filas, ¿su sampling sigue siendo válido?". Las preguntas dan +0.5 a +1 pt cada una si el rival no responde bien.
- **Depende de:** nada (pueden hacerlo desde día 1)
- **Hecho cuando:** lista de 10 preguntas (5 para cada otro proyecto) en `/business/qa-attack.md`.

### F21. Sesión de "abogado del diablo" del equipo
- **Qué hacer:** sesión de 1 hora donde cada miembro intenta romper el proyecto haciendo las preguntas más duras posibles a los demás. Las respuestas que se den ahí son las del Demo Day. Si alguien se queda en blanco con una pregunta básica, anotar y estudiar.
- **Depende de:** F19
- **Hecho cuando:** sesión completada, se identificaron al menos 3 puntos débiles que requieren refuerzo.

### F22. Slides del pitch
- **Qué hacer:** crear slides (Keynote, PPT, Google Slides). Estructura sugerida: hook (1 min), problema y por qué opciones actuales fallan (1 min), arquitectura del motor determinístico (1.5 min), demo en vivo (2 min), cómo evitamos alucinaciones (1 min), modelo de negocio y diferenciador (1 min), roadmap y cierre (0.5 min). Mínimo de texto, máximo de imagen.
- **Depende de:** F2, F15
- **Hecho cuando:** slides existen y la estructura cubre los 8 minutos.

### F23. Guion del pitch minuto por minuto
- **Qué hacer:** redactar guion con quién habla en qué minuto, qué dice (no palabra por palabra, sí ideas clave), cómo es la transición al siguiente. Asegurar que los 5 hablan al menos una vez (Criterio 5.3 lo exige).
- **Depende de:** F22, A7
- **Hecho cuando:** guion escrito con minutaje y asignación.

### F24. Ensayo 1 del pitch (sin cronómetro)
- **Qué hacer:** los 5 hacen el pitch entero una vez. Identificar dónde se traban las transiciones, qué slides necesitan ajuste, qué partes son confusas. Notas de mejoras.
- **Depende de:** F23
- **Hecho cuando:** ensayo completado y notas escritas.

### F25. Ensayo 2 del pitch (con cronómetro)
- **Qué hacer:** segundo ensayo cronometrado. Probablemente quedan en 10-11 min. Identificar qué cortar para llegar a 8.
- **Depende de:** F24
- **Hecho cuando:** ensayo cronometrado y plan de cortes definido.

### F26. Ensayo 3 con audiencia externa
- **Qué hacer:** tercer ensayo frente a un amigo, familiar u otro equipo. Cronometrado. Si pasan 8:30, recortar más. Si bajan de 7:30, ampliar demo o cierre. Capturar feedback de la audiencia externa.
- **Depende de:** F25
- **Hecho cuando:** pitch en rango 7:30-8:30, feedback externo capturado.

### F27. Video demo de 3-5 minutos
- **Qué hacer:** grabar video que muestre el producto en acción: pegar query en AppDB → análisis aparece → before/after → workload analysis. Editar con narración clara. Subir a YouTube unlisted o Drive. Linkar desde README. Sirve también como plan B si la demo en vivo falla.
- **Depende de:** C12, E4
- **Hecho cuando:** video subido y linkeado desde README.

### F28. Plan B con BD demo en 2 laptops
- **Qué hacer:** asegurar que AppDB + producto corre en mínimo 2 laptops del equipo (no solo en una). Probar conexión a internet, acceso al LLM, y modo offline. Si falla la principal el día del Demo Day, conmutar a la backup.
- **Depende de:** C12
- **Hecho cuando:** las 2 laptops ejecutan demo sin internet (modo plantillas) y con internet (modo LLM).

### F29. Verificar entregables del repo
- **Qué hacer:** checklist final del brief: README claro, docker-compose funcional, /docs con arquitectura, /business con documento de negocio, /docs/patterns con catálogo, sistema de prompts documentado, video linkeado, commits distribuidos entre los 5 (revisar `git shortlog -sn`).
- **Depende de:** F1, F2, F15, F17, F27
- **Hecho cuando:** los 7 elementos del checklist están en el repo.

### F30. Generar PDF de plantillas de entrega
- **Qué hacer:** llenar las 3 plantillas que entregó el profesor (carátula, arquitectura, negocio), exportar a PDF, subir como entrega final en la asignación.
- **Depende de:** F2, F15
- **Hecho cuando:** PDF subido a la plataforma del profe.

---

## Reglas operativas durante todas las fases

Estas no son tareas, son reglas que aplican en paralelo a todo el backlog:

- **Standup diario de 15 minutos** a la misma hora. Cada uno responde: qué hice, qué voy a hacer, qué me bloquea.
- **Pull Requests con review** entre miembros antes de mergear a main. No push directo.
- **Tests verdes antes de mergear.** Quien rompa main paga café.
- **Documentar decisiones en el doc compartido** apenas se toman (no esperar al final).
- **Llevar visible el número de cobertura** ("X de 20 detectadas") en el README del repo.
- **Cada commit con mensaje descriptivo** (no "fix" ni "cambios").

---

## Resumen de cobertura del proyecto

Cumpliendo todas las actividades del backlog, el equipo cubre:

- **Criterio 1 — Dominio técnico (25 pts):** A8, B1-B16, C1-C12, D1-D15, E1-E13, F2, F17.
- **Criterio 2 — Funcionalidad MVP (20 pts):** D14, D15, F18, C12, E4, F27, F28.
- **Criterio 3 — Producto y negocio (20 pts):** F3-F15.
- **Criterio 4 — Calidad de ingeniería (10 pts):** A1-A3, A5, A6, A8, A9, F16, regla de PRs, regla de commits.
- **Criterio 5 — Presentación (10 pts):** F22-F26, F23.
- **Criterio 6 — Documentación (10 pts):** F1, F2, F27, E10-E13, F17.
- **Q&A Battle (-10 a +5 pts):** F19, F20, F21.
- **Bonus (hasta +10 pts):** F16 (tests +3), opcionalmente CI/deploy si sobra tiempo.

Total alcanzable cumpliendo el backlog: **95-100 pts + bonus**.

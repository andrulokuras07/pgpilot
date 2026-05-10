# PROGRESS — Bitácora del proyecto

Este archivo es el log cronológico del proyecto. Cada vez que un agente cierra una actividad del backlog, debe agregar una entrada aquí. Cada vez que el equipo toma una decisión técnica importante, debe registrarse aquí.

**Cómo se usa este archivo:**

- Las entradas más recientes van **arriba** (orden cronológico inverso)
- Cada día tiene su sección con fecha en formato `YYYY-MM-DD`
- Dentro de cada día hay dos subsecciones: "Avances" y "Decisiones" (si aplica)
- Cada avance lista: actividad cerrada, autor, archivos modificados, notas
- Las decisiones tienen autor, contexto, alternativas consideradas, qué se eligió y por qué

**Cómo lo usan los agentes de Claude Code:**

Antes de empezar a trabajar, leen las últimas 2-3 entradas de `PROGRESS.md` para conocer el estado actual del proyecto y detectar decisiones recientes que pueden afectar su trabajo.

**Recordatorio de regla R15 (en `RULES.md`):** antes de hacer `git push` de una rama que cierra una actividad del backlog, hay que agregar entrada en este archivo Y, si aplica, actualizar el `CLAUDE.md` del módulo afectado. Si el módulo no tiene `CLAUDE.md` todavía, hay que crearlo (ver convención en `CLAUDE.md` raíz).

---

## Estado actual del proyecto

### Cobertura de detección
- **AppDB v1:** 0 / 20 queries detectadas (objetivo: ≥16)
- **Falsos positivos:** sin medir todavía (objetivo: <3)
- **AppDB v2:** sin probar (objetivo: ≥4 de 5 queries nuevas)

### Hitos
- ⬜ Hito 1 (kickoff y arquitectura) — fecha por confirmar
- ⬜ Hito 2 (demo parcial) — fecha por confirmar
- ⬜ Hito 3 (Demo Day) — 14 de mayo de 2026

### Asignación de roles
*El equipo decidió no asignar roles fijos. Cualquier miembro puede tomar cualquier actividad del backlog. Ver decisión del 2026-05-08 en este archivo.*

### Actividades en curso
*(Esta sección la actualiza cada miembro al tomar/cerrar tareas. Una actividad nunca debe estar "in progress" más de 3 días sin moverse.)*

| Código | Actividad | Responsable | Estado | Notas |
|--------|-----------|-------------|--------|-------|
| — | — | — | — | — |

### Bloqueos activos
*(Cualquier impedimento que requiera ayuda del equipo o de fuera. Si no hay bloqueos, déjalo vacío.)*

- Ninguno reportado.

---

## Plantilla para nuevas entradas

Copia esta plantilla cuando agregues un día nuevo. Borra los placeholders.

```markdown
## YYYY-MM-DD

### Avances

#### [CODIGO_ACTIVIDAD] — Título corto
- **Autor:** Nombre
- **Archivos:** `archivo1.py`, `archivo2.py`
- **Notas:** Resumen de 1-2 líneas. Qué cambió, qué quedó pendiente, qué hay que vigilar.
- **Tests:** ✅ Verde | ⚠️ Pendiente | ❌ Falló (con razón)

### Decisiones

#### Título de la decisión
- **Autor:** Nombre (o "Equipo" si fue en standup)
- **Contexto:** Qué problema se estaba resolviendo
- **Alternativas consideradas:** A, B, C
- **Decisión:** Se eligió A
- **Razón:** Por qué A le ganó a B y C
- **Trade-offs:** Qué se sacrifica con esta decisión

### Bloqueos detectados

- Bloqueo X afectando a Persona Y. Acción para destrabar: ...
```

---

## Bitácora

*(Las entradas reales del proyecto van debajo de esta línea. Las más recientes arriba.)*

---

## 2026-05-09

### Avances

#### B11 — Test de privacidad del sanitizador
- **Autor:** Regina Valenzuela
- **Archivos:** `tests/ia/test_privacidad.py`, `ia/CLAUDE.md`.
- **Notas:** Test específico que sanitiza una query con datos sensibles reales (email `juan.perez@empresa.com.mx`, RFC mexicano `GODE561231GR8`, número de tarjeta `4532015112830366`), escribe el output a un archivo temporal con `tmp_path` y verifica con `subprocess.run(["grep", ...])` que ninguno aparece. Segundo test confirma que los datos sí siguen disponibles en el mapa de literales para que `restore()` pueda reconstruir localmente. Es la prueba defensiva para el Q&A del Demo Day sobre privacidad.
- **Tests:** ✅ 2/2 verde. Suite total del proyecto: 105/105.

#### B10 — Sanitizador de literales SQL
- **Autor:** Regina Valenzuela
- **Archivos:** `ia/__init__.py`, `ia/sanitizer.py`, `ia/CLAUDE.md`, `ia/README.md` (eliminado, reemplazado por CLAUDE.md, mismo patrón que `motor/`), `tests/ia/conftest.py`, `tests/ia/test_sanitizer.py`.
- **Notas:** `sanitize(sql)` devuelve `SanitizedQuery(sql, literals)` con placeholders por tipo según backlog: `$LITERAL_1_<i>` strings, `$LITERAL_2_<i>` números, `$LITERAL_3_<i>` fechas ISO, `$LITERAL_4_<i>` UUIDs, `$LITERAL_5_<i>` emails. El sufijo numérico interno permite múltiples literales del mismo tipo en una query. Implementación con regex puro y un ordenamiento por `(start, -length)` que descarta matches solapados (ej: número o email dentro de un string ya consumido). `restore()` reconstruye el SQL original; docstring advierte que jamás debe usarse hacia el LLM. API documentada en `ia/CLAUDE.md` (creado, primer toque al módulo).
- **Tests:** ✅ 18/18 verde. Criterio de "hecho cuando" cumplido: el test con email real (`juan@empresa.com`) y RFC mexicano (`GODE561231GR8`) verifica que ninguno aparece en el output. Suite total del proyecto: 103/103.

#### B7 + B8 + B9 — Parser de EXPLAIN JSON y helper find_nodes
- **Autor:** Andrés Angulo
- **Archivos:** `motor/__init__.py`, `motor/parser.py`, `motor/nodes.py`, `motor/CLAUDE.md`, `motor/README.md` (eliminado, reemplazado por CLAUDE.md), `tests/motor/conftest.py`, `tests/motor/test_parser.py`, `tests/motor/test_parser_node_types.py`, `tests/motor/test_find_nodes.py`, `tests/motor/fixtures/*.json` (12 planes reales de AppDB + 1 sintético), `tests/motor/fixtures/README.md`.
- **Notas:** Tres tickets empaquetados porque B8 y B9 son extensiones naturales de B7 sobre el mismo `PlanNode`. **B7:** `parse_explain(raw)` acepta `str` (JSON crudo), `list[dict]` (forma típica de `cur.fetchone()[0]`) o `Mapping` (entry suelto), devuelve `ExplainResult(root, planning_time_ms, execution_time_ms)`. `PlanNode` es un `dataclass(frozen=True)` con campos comunes y específicos por tipo de nodo, todos opcionales para tolerar EXPLAIN sin ANALYZE y diferencias entre versiones de Postgres. Children es `tuple[PlanNode, ...]` para preservar inmutabilidad. **B8:** `PlanNode` cubre los 16 tipos requeridos por el backlog (Seq Scan, Index Scan, Index Only Scan, Bitmap Heap/Index Scan, Nested Loop, Hash/Merge Join, Sort, Hash, Aggregate, Limit, Subquery Scan, CTE Scan, Materialize, Gather) más Gather Merge (que aparece naturalmente en planes paralelos de AppDB). Cada tipo expone sus campos relevantes (Index Cond, Hash Cond, Sort Key, Group Key, etc.). **B9:** `find_nodes(tree, node_type)` recorre DFS pre-order, acepta `PlanNode` o `ExplainResult` y `str` o iterable de tipos, devuelve lista vacía si no hay matches. Es la primitiva sobre la que escribirán los detectores (R2: estructura, no strings). API completa documentada en `motor/CLAUDE.md` (creado, primer toque al módulo).
- **Tests:** ✅ 42/42 verde (10 de `find_nodes`, 13 de `parser`, 19 de `node_types`). Suite total del proyecto: 85/85 (43 conector + 42 motor). Tests son unit (no requieren AppDB); los fixtures JSON están versionados en `tests/motor/fixtures/`. `black` e `isort` aplicados.

#### B4 + B5 + B6 — Stats por columna, cache de metadata, modo offline
- **Autor:** Alexander
- **Archivos:** `conector/stats.py`, `conector/types.py`, `conector/cache.py`, `conector/offline.py`, `conector/__init__.py`, `conector/CLAUDE.md`, `tests/conector/test_stats.py`, `tests/conector/test_cache.py`, `tests/conector/test_offline.py`, `.gitignore`
- **Notas:** Tres tickets empaquetados en una rama porque comparten el contrato `SchemaSnapshot` (combinado schema+sizes+stats). **B4:** `get_column_stats(pool, schemas)` devuelve `dict["schema.tabla"][columna] -> ColumnStats` con `n_distinct`, `null_frac`, `most_common_vals` (lista de strings), `correlation`, y un flag `has_stats` que distingue "tabla sin ANALYZE" de "stats que reportan 0". Query con LEFT JOIN entre `pg_attribute` y `pg_stats`, filtrando `inherited=false`. **B5:** `extract_snapshot()` combina B2+B3+B4; `get_snapshot()` orquesta cache local en `cache/{fingerprint}.json` (fingerprint = md5 de host:port:db:schemas). `compute_content_hash` se guarda dentro del JSON para detectar drift. `invalidate_cache` borra por fingerprint o todo el directorio. `cache/` agregado a `.gitignore`. **B6:** `export_bundle()` y `load_bundle()` con el mismo formato que el cache; `validate_bundle()` recalcula y compara hash. El bundle es portable: el cliente lo genera en su entorno y nos lo comparte sin abrir conexión. API pública completa documentada en `conector/CLAUDE.md`.
- **Tests:** ✅ 25/25 nuevos verde (7 stats integration, 14 cache mezcla unit+integration, 4 offline integration). Suite completa del módulo: 43/43 contra AppDB en `localhost:5434`. Cache hit medido en <100ms (criterio de B5). Tests de integración marcados con `@pytest.mark.integration`.

#### B2 + B3 — Extractor de schema y de tamaños de tabla
- **Autor:** Andrés Angulo
- **Archivos:** `conector/schema.py`, `conector/sizes.py`, `conector/__init__.py`, `conector/CLAUDE.md`, `tests/conector/test_schema.py`, `tests/conector/test_sizes.py`
- **Notas:** `get_schema(pool, schemas)` devuelve dict `"<schema>.<tabla>" → TableSchema` con columnas, índices (en orden, con método y flags `is_unique`/`is_primary`) y FKs. `get_table_sizes(pool, schemas)` devuelve `reltuples`, `pg_total_relation_size` y categoría `small`/`medium`/`large`/`unknown` (esta última cuando la tabla no tuvo ANALYZE). Queries van contra `pg_catalog`, no `information_schema`, para preservar orden de columnas en índices y manejar FKs compuestos. Empaquetadas como B2+B3 en una sola rama porque B3 es ampliación natural del extractor y comparten contrato de claves. API completa documentada en `conector/CLAUDE.md`.
- **Tests:** ✅ 14/14 nuevos verde contra AppDB v1 en `localhost:5434` (7 integration de `get_schema`, 4 unit de `categorize`, 3 integration de `get_table_sizes`). Suite completa del módulo: 18/18. Los integration tests están marcados con `@pytest.mark.integration`.

#### B1 — Conector a Postgres con read-only forzado
- **Autor:** Andrés Angulo
- **Archivos:** `conector/__init__.py`, `conector/config.py`, `conector/pool.py`, `conector/CLAUDE.md`, `conector/README.md`, `tests/conector/conftest.py`, `tests/conector/test_pool.py`, `requirements.txt`, `pyproject.toml`, `.env.example`
- **Notas:** Pool `psycopg_pool.ConnectionPool` que aplica `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` y `SET statement_timeout = 5000` por conexión vía `configure` callback. Cumple R7 (read-only forzado en BD del cliente). Detalles de API y decisiones internas del módulo en `conector/CLAUDE.md`.
- **Tests:** ✅ 4/4 verde contra AppDB en `localhost:5434` (SELECT funciona, INSERT rechazado con SQLSTATE 25006, DDL rechazado, `pg_sleep(10)` cancelado por timeout). Marcados con `@pytest.mark.integration`.

### Decisiones

#### `PlanNode` con campos planos vs dict de extras (B7)
- **Autor:** Andrés Angulo
- **Contexto:** el JSON de EXPLAIN tiene ~30 campos opcionales según el tipo de nodo (Index Cond solo en Index Scan, Hash Cond solo en Hash Join, etc.). Dos opciones para representarlos en `PlanNode`.
- **Alternativas:** (a) un atributo nombrado por cada campo posible, todos `Optional`; (b) un `extras: dict[str, Any]` con los campos específicos del tipo.
- **Decisión:** opción (a) — un atributo por campo.
- **Razón:** los detectores van a leer estos campos a montones (`node.index_name`, `node.sort_key`, etc.); con `extras["Index Name"]` perdemos type checking y autocomplete, y normalizar nombres "Title Case" → snake_case en cada call site es ruido. La explosión de atributos `Optional` se contiene a un solo dataclass que rara vez cambia.
- **Trade-off:** si Postgres agrega un campo nuevo en una versión futura y no lo agregamos al dataclass, el parser lo ignora silenciosamente. Mitigación: pinneamos Postgres 16 vía docker-compose y agregar un campo es trivial.

#### Subclases por tipo de nodo descartadas (B7+B8)
- **Autor:** Andrés Angulo
- **Contexto:** evaluamos si modelar cada tipo de nodo como una subclase de `PlanNode` para tener type checking más estricto.
- **Decisión:** un solo `PlanNode` con todos los campos opcionales.
- **Razón:** 16+ subclases es una explosión de boilerplate por marginal ganancia en seguridad. Los detectores filtran por `node.node_type == "X"` antes de leer campos específicos, lo que es legible y se valida con tests. Si en el futuro un detector se vuelve complejo, puede definirse un type guard local.

#### Tests de `motor` son unit, sin marker `integration`
- **Autor:** Andrés Angulo
- **Contexto:** `tests/conector/` usa `@pytest.mark.integration` para los tests que necesitan AppDB. ¿Aplicamos la misma convención en `motor`?
- **Decisión:** no. Los tests de `motor` parten de fixtures JSON versionados en `tests/motor/fixtures/`.
- **Razón:** el parser y `find_nodes` son funciones puras; necesitar Docker para correr sus tests es ruido innecesario. Los fixtures se regeneran a mano cuando hace falta y se documentan en `tests/motor/fixtures/README.md`.

#### Cache nombrado por `fingerprint`, no por `content_hash` (B5)
- **Autor:** Alexander
- **Contexto:** el backlog literal pide `cache/{hash}.json` con hash del contenido del schema. Implementarlo así es circular: para saber qué archivo leer en una segunda extracción, hay que re-extraer y recalcular el hash, lo que defeats el propósito del cache (criterio "<100ms en segunda llamada").
- **Alternativas:** (a) nombre del archivo = content hash + un índice separado mapeando connection params → hash; (b) nombre del archivo = fingerprint determinístico de la BD, content_hash guardado dentro del JSON.
- **Decisión:** opción (b). `fingerprint = md5(host:port:dbname:schemas_ordenados)`. Cache path = `cache/{fingerprint}.json`. Dentro del archivo se guarda `content_hash` para detectar drift en una futura comparación.
- **Razón:** lookup directo sin re-extracción, ergonomía limpia, mismo objetivo del backlog. La detección de drift sigue disponible vía el campo `content_hash` cuando alguien lo necesite.
- **Trade-off:** el nombre del archivo no garantiza que dos archivos con el mismo nombre tengan el mismo contenido. Mitigación: `content_hash` interno + tests que validan el roundtrip.

#### Modo offline: bundle JSON en lugar de `pg_dump` + `pg_stats` CSV (B6)
- **Autor:** Alexander
- **Contexto:** el backlog original sugiere parsear `pg_dump --schema-only` + un export CSV de `pg_stats`. Parsear pg_dump con sqlglot es frágil: emite SQL específico de Postgres (ALTER OWNER, SET, COMMENT, extensions) que sqlglot no parsea fielmente. Y `pg_stats.most_common_vals` es `anyarray`, parsearlo desde CSV requiere lógica por tipo.
- **Alternativas:** (a) parser SQL completo de pg_dump + CSV reader de pg_stats; (b) bundle JSON que el cliente genera con `export_bundle()` corriendo PgPilot en su entorno; (c) ambos.
- **Decisión:** opción (b) por ahora. Mismo formato que el cache (B5).
- **Razón:** cumple el criterio del backlog ("el extractor produce el mismo dict de metadata desde un dump que desde conexión viva") y la motivación de venta ("empresas con datos sensibles no quieren dar acceso a la BD productiva"). El cliente nunca conecta a nuestra infra; nos da un archivo. Implementación limpia, testeable, en menos de 100 líneas.
- **Trade-off:** asume que el cliente puede correr el binario de `export_bundle` (Python + psycopg en su entorno). Si en el futuro un cliente solo nos puede dar `pg_dump` SQL crudo, queda como ticket separado un parser pg_dump → SchemaSnapshot. Documentado en `conector/CLAUDE.md` como vía de extensión.

#### Layout Python: dependencias y tooling en la raíz del repo
- **Autor:** Andrés Angulo
- **Contexto:** primer módulo Python del proyecto (B1). Había que decidir si cada módulo (`/conector`, `/motor`, `/ia`, `/workload`, `/backend`) tiene su propio venv y `requirements.txt`, o si comparten uno solo en la raíz.
- **Alternativas:** (a) un venv y `requirements.txt` por módulo, (b) un solo venv compartido en raíz para todo el monorepo Python.
- **Decisión:** opción (b). `requirements.txt` y `pyproject.toml` viven en la raíz. `pyproject.toml` configura `pythonpath = ["."]` para que pytest pueda importar módulos sin instalarlos como paquete.
- **Razón:** simplifica setup (`pip install -r requirements.txt` y listo), el backend va a importar de todos los módulos así que comparten dependencias por diseño, y match con el patrón del `docker-compose.yml` donde el backend es un solo servicio.
- **Trade-off:** si algún módulo en el futuro necesita una versión incompatible de una dependencia, hay que romper este layout. Improbable en el alcance del proyecto.

---

## 2026-05-08

### Decisiones

#### Modificación del backlog: eliminación de A4 y A7, reformulación de A6
- **Autor:** Andrés Angulo
- **Contexto:** revisión inicial del backlog antes de arrancar Fase 0. Se identificaron tres actividades que no encajan con la forma de trabajo decidida por el equipo.
- **Cambios:**
  - **A4 (tablero de tareas):** eliminada. El equipo se coordina con el backlog en Markdown, `PROGRESS.md` y GitHub Issues. No se usará tablero externo.
  - **A6 (decisiones del equipo):** reformulada. Pasa de Google Doc/Notion a `docs/decisiones.md` dentro del repo. Razón: tener todo versionado en Git y evitar herramientas paralelas.
  - **A7 (asignar roles):** eliminada. El equipo trabajará sin roles fijos; cualquiera puede tomar cualquier actividad disponible.

## 2026-05-06 — Día 1 del proyecto

### Avances

#### A1 — Crear repositorio Git
- **Autor:** Andrés Angulo
- **Archivos:** `.gitignore`, `README.md`
- **Notas:** Repo `pgpilot` creado en GitHub. Los 4 compañeros agregados como colaboradores. Protección de rama `main` por ahora NO activada (ver decisión abajo).
- **Tests:** N/A

#### A2 — Definir estructura de carpetas
- **Autor:** Andrés Angulo
- **Archivos:** carpetas `/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`, `/backend`, `/frontend`, `/docs`, `/docs/patterns`, `/docs/briefs`, `/business`, `/tests`, `/scripts` con README placeholder en cada una.
- **Notas:** Estructura alineada con la documentada en `CLAUDE.md`. Agregada carpeta `/backend` para FastAPI y `/docs/briefs` para los PDFs originales del proyecto.
- **Tests:** N/A

#### Setup inicial — Archivos de contexto base
- **Autor:** Andrés Angulo
- **Archivos:** `CLAUDE.md`, `RULES.md`, `PROGRESS.md` en raíz
- **Notas:** Tres archivos de contexto agregados antes de que el equipo arranque cualquier código, para que Claude Code de cada miembro tenga las reglas y arquitectura desde la primera sesión.

### Decisiones

#### Documentación obligatoria al hacer push, no al hacer PR
- **Autor:** Andrés Angulo
- **Contexto:** La regla R15 original exigía actualizar `PROGRESS.md` y los `CLAUDE.md` de módulos antes de mergear el PR. Esto solo funciona si la rama `main` está protegida y bloquea push directos. Como el equipo no domina Git todavía, activar la protección agregaría fricción de aprendizaje.
- **Alternativas consideradas:** (a) activar protección de rama y mantener regla atada al PR, (b) posponer protección y atar la regla al `git push` en lugar del PR
- **Decisión:** Opción b — la regla se cumple antes de cada push. 
- **Razón:** Permite que el equipo aprenda el flujo de Git con menos fricción mientras mantiene viva la regla de documentación obligatoria. La regla deja de depender de la herramienta y pasa a depender de disciplina del equipo, lo cual es viable porque cada agente Claude Code va a leer `RULES.md` antes de hacer push.
- **Trade-offs:** Si alguien hace push directo a `main` por accidente, no hay red de seguridad técnica. Mitigación: comunicación clara en el grupo de WhatsApp y recordatorio en standups.

### Bloqueos detectados

- Ninguno.

## 2026-05-08

### Avances

#### A6 — Documento de decisiones del equipo
- **Autor:** Andrés Angulo
- **Archivos:** `docs/decisiones.md`
- **Notas:** Archivo creado con las 4 secciones inicializadas (Stack, Arquitectura, Trade-offs, Bloqueos). Contenido se llena progresivamente; sección Stack se completa en A8.
- **Tests:** N/A

#### A8 — Stack técnico documentado
- **Autor:** Andrés Angulo
- **Archivos:** `docs/decisiones.md`
- **Notas:** Sección "Stack elegido" llenada con justificación de cada decisión (Python+FastAPI, psycopg v3, sqlglot, Pydantic, React+Vite+Monaco+Tailwind, Claude API, Postgres 16, Docker Compose, pytest, black+isort). Cubre Criterio 1.2 de la rúbrica.
- **Tests:** N/A

#### A9 — Esqueleto de docker-compose
- **Autor:** Andrés Angulo
- **Archivos:** `docker-compose.yml`, `infra/appdb/init/*`, `infra/appdb/postgresql.conf`, `infra/appdb/README.md`, `docs/decisiones.md`
- **Notas:** Compose raíz con servicios `appdb` (5434) y `sandbox` (5435). Backend y frontend quedan como placeholders comentados, se activan en fases posteriores. Init files de AppDB copiados del repo del profesor a `/infra/appdb/`. Dos decisiones registradas en `docs/decisiones.md`.
- **Tests:** ✅ `docker compose up` levanta ambos contenedores con healthcheck en estado `healthy`.

#### A1 — Protección de main activada
- **Autor:** Andrés Angulo
- **Archivos:** N/A (configuración en GitHub)
- **Notas:** Activada protección de rama `main` con ruleset: requiere PR antes de merge, bloquea force push, bloquea deletions. Required approvals = 0 (decisión registrada abajo). Verificado con push directo a main rechazado.
- **Tests:** ✅ Push directo a main rechazado por GitHub.

#### A5 — AppDB corriendo localmente
- **Autor:** Andrés Angulo
- **Archivos:** N/A (verificación local)
- **Notas:** AppDB v1.0 corriendo en localhost:5434. Verificación: `SELECT count(*) FROM pg_stat_statements` devuelve 34 (las 20 queries plantadas + variantes). Pendiente confirmar que los otros 4 miembros lo levanten en sus máquinas.
- **Tests:** ✅ Conexión y query verificadas.

### Decisiones

#### Protección de main
- **Autor:** Andrés Angulo
- **Contexto:** R17 del equipo establece "PRs con review entre miembros". GitHub permite forzarlo con `Required approvals ≥ 1`. Se evaluó si activarlo.
- **Alternativas:** (a) Required approvals = 1, forzando review técnico antes de merge. (b) Required approvals = 0, dejando review como norma social.
- **Decisión:** opción (b).
- **Razón:** quedan 9 días al Demo Day. Bloquear merges esperando review de un compañero introduce latencia que no nos podemos permitir. La regla R17 sigue viva como norma social: nadie hace push directo, todo va por PR, pero el merge no espera approval formal.
- **Trade-off:** riesgo de mergear código roto a `main`. Mitigación parcial: tests verdes obligatorios antes de mergear (R operativa del backlog), commits descriptivos para revertir rápido si algo se rompe.

#### Cierre de Fase 0
- **Autor:** Andrés Angulo
- **Estado:** todas las actividades de Fase 0 cerradas (A1, A2, A3, A5, A6, A8, A9). A4 y A7 eliminadas previamente. Equipo listo para arrancar Fase 1.

---

## Histórico de hitos

### Hito 1 — [Por completar]
- **Fecha real:** —
- **Qué se entregó:** —
- **Feedback del profesor:** —
- **Acciones derivadas:** —

### Hito 2 — [Por completar]
- **Fecha real:** —
- **Qué se entregó:** —
- **Feedback del profesor:** —
- **Acciones derivadas:** —

### Hito 3 (Demo Day) — [Por completar]
- **Fecha real:** —
- **Cobertura final v1:** —
- **Cobertura final v2:** —
- **Falsos positivos:** —
- **Resultado del Q&A Battle:** —
- **Nota recibida:** —

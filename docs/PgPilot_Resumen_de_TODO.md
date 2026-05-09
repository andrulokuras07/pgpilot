## **PgPilot — Onboarding del equipo**

Este documento explica cómo levantar el ambiente de trabajo, cómo trabajamos en equipo, y qué reglas hay que respetar. 

Si algo no queda claro, pregunta en el grupo de WhatsApp. Es mejor preguntar 2 minutos que perder 2 horas.

---

### **1\. Qué estamos construyendo**

**PgPilot** es un analizador inteligente de queries de Postgres. El usuario pega una query SQL lenta, y nuestro producto:

1. Detecta qué problema tiene (índice faltante, query mal escrita, etc.) usando reglas de código.  
2. Le pide a un LLM (Claude API) que explique el problema en lenguaje humano y proponga una solución.  
3. Valida que la solución del LLM funcione antes de mostrarla al usuario.

**La regla \#1 del proyecto:** el código detecta y decide; el LLM explica y propone; el código valida lo que el LLM propone. **Nunca** dejamos que el LLM tenga la última palabra. Si rompemos esto, perdemos 25 puntos de la rúbrica.

Tienen detalle completo en `CLAUDE.md` y `RULES.md` en la raíz del repo.

---

### **2\. Qué hay que instalar (una sola vez)**

Antes de tocar el repo, asegúrense de tener instalado:

* **Git** — viene en Mac y Linux. En Windows: instalar Git for Windows desde [https://git-scm.com/download/win](https://git-scm.com/download/win)  
* **Docker Desktop** — descargar de [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/). Esencial: sin Docker no se levanta la base de datos.  
* **Node.js 20+** — descargar LTS de [https://nodejs.org/](https://nodejs.org/). Se necesita para el frontend.  
* **Python 3.11+** — descargar de [https://www.python.org/downloads/](https://www.python.org/downloads/). Se necesita para el backend.  
* **VS Code** (recomendado) — el editor que usa la mayoría del equipo.  
* **DBeaver** o **pgAdmin** — cliente para conectarse a la base de datos visualmente. DBeaver es gratuito y multiplataforma.  
* **Claude Code** — todos lo tenemos con el plan Pro. Si alguien no lo tiene instalado, ver instrucciones en [https://docs.claude.com/en/docs/claude-code](https://docs.claude.com/en/docs/claude-code)

**Verificación:** abran una terminal y corran:

git \--version  
docker \--version  
node \--version  
python \--version

Cada uno debe responder con un número de versión. Si alguno falla, instálenlo antes de seguir.

---

### **3\. Levantar el proyecto local (paso a paso)**

#### **3.1 Clonar el repo**

En la terminal, en la carpeta donde quieran tener el proyecto:

git clone https://github.com/\[USUARIO\]/pgpilot.git  
cd pgpilot

Andrés les pasa el link exacto en WhatsApp.

#### **3.2 Levantar las bases de datos**

Desde la raíz del repo:

docker compose up \-d

La primera vez tarda **3-4 minutos** porque Docker descarga la imagen de Postgres y la base de datos (AppDB) carga 5 millones de filas. Verán mucho texto pasar; es normal.

**Verificar que todo esté arriba:**

docker compose ps

Deben aparecer dos contenedores en estado `Up` y `healthy`:

* `appdb` (la base de datos demo del profesor)  
* `sandbox` (base de datos vacía para validar sugerencias)

**Probar conexión a AppDB:**

docker exec \-it appdb psql \-U app\_user \-d appdb \-c "SELECT count(\*) FROM pg\_stat\_statements;"

Debe devolver un número (≥20). Si lo hace, tu setup funciona.

#### **3.4 Apagar todo cuando terminen**

docker compose down

Los datos no se borran. Cuando vuelvas a hacer `docker compose up -d`, todo está como lo dejaste.

---

### **4\. Estructura del repo**

pgpilot/  
├── CLAUDE.md            **← arquitectura general (LEER ANTES DE PROGRAMAR)**  
├── RULES.md             **← reglas del proyecto (LEER ANTES DE PROGRAMAR)**  
├── PROGRESS.md          **← bitácora del proyecto (LEER ANTES DE TOMAR TAREA)**  
├── PgPilot\_Backlog.md   ← lista de las 80 actividades del proyecto  
├── docker-compose.yml   ← levanta las bases de datos  
│  
├── backend/             ← código del servidor (Python \+ FastAPI)  
├── frontend/            ← código de la interfaz (React \+ Vite)  
├── conector/            ← conexión a Postgres  
├── motor/               ← detectores de problemas en queries  
├── ia/                  ← integración con Claude API  
├── workload/            ← análisis de queries del histórico  
├── sandbox/             ← validación de sugerencias  
├── tests/               ← tests automáticos  
├── docs/                ← documentación (este archivo está aquí)  
├── business/            ← documento de negocio, pitch  
├── infra/appdb/         ← archivos para levantar AppDB  
└── scripts/             ← scripts auxiliares

Cada carpeta de código tiene (o tendrá) su propio archivo `CLAUDE.md` con detalles internos del módulo.

---

### **5\. LO MÁS IMPORTANTE**

#### **5.1 Tres archivos que rigen el desarrollo**

1. **`PgPilot_Backlog.md`** — lista de tareas (las llamamos "actividades"). Cada actividad tiene un código (A1, B7, F12...), descripción, qué tiene que estar listo antes de tomarla, y qué significa "hecha".  
2. **`PROGRESS.md`** — bitácora del proyecto. Las entradas más recientes están arriba. Lean las últimas 2-3 entradas para enterarse de qué se hizo y qué decisiones se tomaron desde ayer.  
3. **`RULES.md`** — reglas del proyecto. Léanlo el primer día completo, después solo cuando tengan duda.

#### **5.2 Cómo tomar una actividad**

1. Abre `PgPilot_Backlog.md` y busca una actividad que:  
   * Tenga sus dependencias listas (el campo "Depende de" apunta a actividades ya cerradas).  
   * Nadie más esté trabajando en ella (revisar la tabla "Actividades en curso" en `PROGRESS.md`).  
2. Avisa en el grupo de WhatsApp: *"Voy con B7"*. Esto evita que dos personas tomen la misma actividad.  
3. Sigue el flujo de Git de la siguiente sección.

#### **5.3 Conceptos básicos: branch y Pull Request**

Antes del flujo, dos conceptos clave para los que no los conocen:

* **Branch (rama):** una copia paralela del proyecto donde tú haces cambios sin afectar a los demás. Mientras tu rama existe, `main` (la rama principal del proyecto) sigue intacta. Cuando terminas, "fusionas" tu rama a `main`.  
* **Pull Request (PR):** la solicitud formal a GitHub para fusionar tu rama a `main`. Es el momento donde el código se revisa antes de entrar al proyecto oficial.

**Por qué hacemos esto y no editar `main` directo:** porque si rompes algo y ya está en `main`, lo rompes para todos. La rama es tu zona de pruebas; cuando funciona, la integras. **ADEMÁS VIENE EN LAS INSTRUCCIONES**

#### **5.4 Flujo de Git (paso a paso, primera vez)**

⚠️ **NUNCA hagan cambios directo en la rama `main`.** GitHub no se los va a permitir, pero igual: siempre crean una rama nueva.

##### **Paso 1 — Asegurarse de tener lo último de main**

git checkout main  
git pull

Esto te trae los cambios que tus compañeros hayan mergeado mientras dormías.

##### **Paso 2 — Crear una rama para tu actividad**

Convención de nombres: `tipo/codigo-descripcion-corta`. Ejemplos:

* `feat/B7-parser-explain` (feature nueva)  
* `fix/B10-sanitizador-emails` (corrigiendo un bug)  
* `docs/F2-arquitectura` (cambios de documentación)

git checkout \-b feat/B7-parser-explain

##### **Paso 3 — Trabajar y hacer commits**

Hacen sus cambios (con Claude Code, ver sección 6). Cada vez que terminen un pedazo lógico:

git add .  
git commit \-m "feat: parser básico de EXPLAIN JSON"

**Mensajes de commit descriptivos.** Nada de `"fix"`, `"cambios"`, `"wip"`. Si Claude Code les genera el commit, suele estar bien — solo revisen que diga algo útil.

##### **Paso 4 — Antes de hacer push: actualizar PROGRESS.md**

Cuando una actividad queda **terminada**, antes de subir el código, agreguen una entrada en `PROGRESS.md` bajo el día actual. Plantilla al final del propio `PROGRESS.md`. Esto es **obligatorio**, no se puede saltar (regla R15).

git add PROGRESS.md  
git commit \-m "docs: actualiza PROGRESS con cierre de B7"

##### **Paso 5 — Subir la rama a GitHub**

git push origin feat/B7-parser-explain

##### **Paso 6 — Abrir Pull Request (PR) en GitHub**

1. Vas al repo en el navegador.  
2. Aparece un banner amarillo: *"feat/B7-parser-explain had recent pushes. Compare & pull request"*. Le das clic.  
3. Llenas el título y descripción cortos: *"B7 — parser básico de EXPLAIN JSON"*.  
4. Le das *"Create pull request"*.  
5. Como decidimos no exigir review formal por velocidad, después de crear el PR le dan ustedes mismos *"Merge pull request"* → *"Confirm merge"*.

##### **Paso 7 — Limpieza**

Después del merge:

git checkout main  
git pull  
git branch \-d feat/B7-parser-explain

¡Listo\! Tu actividad está cerrada. Avisa en WhatsApp: *"B7 mergeado, sigue B8 disponible"*.

#### **5.5 ¿Qué pasa si dos personas modifican lo mismo?**

GitHub avisa con un *"merge conflict"* al abrir el PR. **No entren en pánico.** Avisan en WhatsApp y entre dos lo resolvemos. Es normal.

---

### **6\. Cómo programamos: con Claude Code**

El proyecto se está construyendo con asistencia de **Claude Code**. Es un agente de IA que vive en tu terminal y edita el código por ti, con tu supervisión.

#### **6.1 Reglas básicas con Claude Code**

1. **Antes de pedirle código, dale contexto.** Cárgale los archivos relevantes:  
   * `CLAUDE.md` (raíz)  
   * `RULES.md`  
   * `PROGRESS.md` (últimas entradas)  
   * El `CLAUDE.md` del módulo donde vas a trabajar (si existe)  
   * La sección del backlog con la actividad que vas a hacer  
2. **Dile qué actividad estás haciendo.** Algo así:

    "Voy a trabajar en B7 del backlog. Léete las dependencias y haz solo lo que pida el criterio de hecho. No metas nada extra."

3. **Revisa lo que escribe.** No le des `Aceptar` a ciegas. Lee el código. Si algo no entiendes, pregúntale: *"¿por qué hiciste X?"*. Si suena raro, pídele que lo cambie.  
4. **No le dejes tomar decisiones de arquitectura.** Si tu actividad implica una decisión que afecta a otros módulos, **detente y pregunta en WhatsApp** antes de seguir. Las decisiones de arquitectura se toman en equipo, no las decide el agente.  
5. **No metas datos sensibles.** Nunca le pegues credenciales reales, API keys, ni datos de usuarios reales. La AppDB tiene datos sintéticos, así que está OK trabajar con ella.

#### **6.2 Patrón típico de una sesión de Claude Code**

1. Abres terminal, vas a la raíz del repo, corres `claude` (o el comando que tengas configurado).  
2. Le dices: *"Carga `CLAUDE.md`, `RULES.md`, las últimas 3 entradas de `PROGRESS.md`, y la sección del backlog de la actividad B7."*  
3. Le explicas qué quieres y le pides un plan antes de codear: *"Antes de escribir código, hazme un plan de los archivos que vas a tocar y qué va en cada uno."*  
4. Revisas el plan. Si tiene sentido, le dices que avance.  
5. Mientras escribe, vas leyendo y pidiéndole ajustes.  
6. Cuando termine, le pides correr los tests: *"Corre los tests y dime si pasan."*  
7. Le pides que actualice PROGRESS.md: *"Antes de hacer push, actualiza PROGRESS.md con la entrada del cierre de B7. Recuérdame R15."*  
8. Tú haces el push y abres el PR (esto sí lo haces tú, no el agente).

---

### **7\. Reglas del equipo (resumen)**

Detalle completo en `RULES.md`. Las más importantes:

* **Nunca push directo a main.** Siempre PR.  
* **Tests verdes antes de mergear.** Quien rompa main paga la peda  
* **Una rama por actividad.** No metan dos actividades en la misma rama.  
* **Actualizar PROGRESS.md antes de cada push de cierre de actividad.** Sin excepción.  
* **Commits descriptivos.** Nada de "fix" o "cambios".  
* **Documentar decisiones técnicas el mismo día** que se toman, en `PROGRESS.md`.

#### **Anti-patterns prohibidos**

* ❌ Detectar problemas en SQL con regex sobre la query cruda (hay que parsearla bien).  
* ❌ Hardcodear nombres de tablas o columnas de AppDB ("users", "posts"...). El producto debe ser genérico.  
* ❌ Mergear sin que pasen los tests.  
* ❌ Que el LLM decida si algo es un anti-pattern. Eso lo decide el código.

Lista completa en `RULES.md`.

---

### **8\. Qué hago si...**

**...no puedo levantar Docker.** Avisa en WhatsApp con captura del error. Asegúrate de tener Docker Desktop **abierto** antes de correr `docker compose up`.

**...se rompe `main`.** Avisa en WhatsApp inmediatamente. No traten de arreglarlo solos.

**...no entiendo una actividad del backlog.** Pregunta en el grupo. Mejor 5 minutos preguntando que 3 horas equivocados.

**...Claude Code me genera código raro o que no entiendo.** No lo aceptes. Pídele explicación. Si sigue sin convencerte, pega el snippet en el grupo y lo vemos.

**...ya terminé mi actividad y no sé cuál sigue.** Revisa el backlog buscando una actividad con dependencias listas y nadie asignada. Si todas las disponibles dependen de otras en curso, ayuda a quien va más atrás (pair programming, no programando por el otro: regla R18).

**...siento que voy retrasado.** Avisa temprano. Es mejor pedir ayuda el día 2 que admitir que estás trabado el día 8\.

---

### **9\. Fechas críticas**

* **Hoy (2026-05-08):** arrancamos Fase 1\.  
* **Demo Day:** 14 de mayo de 2026\. **6 días efectivos de trabajo.**  
* Tiempo apretado. Disciplina con commits diarios.

---

### **10\. ¿Algo no está claro?**

Pregunta en WhatsApp. Mejor preguntar mil veces que asumir mal una vez.

¡A darle\!


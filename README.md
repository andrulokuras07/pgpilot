# PgPilot

> Analizador inteligente de queries Postgres que **detecta** anti-patterns con un motor determinístico, los **explica** con una capa de IA con guardrails, y **valida** cada recomendación en un sandbox aislado antes de mostrarla.

PgPilot toma una query SQL (o un export de `pg_stat_statements` completo) y devuelve detecciones, recomendaciones de índices, reescrituras y un comparativo *before/after* del plan de ejecución. Está pensado para equipos backend con Postgres en producción y para empresas con datos sensibles que no pueden compartir su BD productiva: tiene **modo offline por bundle JSON** y **sanitización fuerte de literales** antes de cualquier llamada al LLM.

Proyecto final de **SIS2404 — Bases de Datos Avanzadas**, Universidad Anáhuac Querétaro. Demo Day: 14 de mayo de 2026.

---

## Índice

- [Qué hace PgPilot en 30 segundos](#qué-hace-pgpilot-en-30-segundos)
- [Arquitectura, en una imagen](#arquitectura-en-una-imagen)
- [Antes de empezar — Prerequisitos](#antes-de-empezar--prerequisitos)
  - [macOS](#macos)
  - [Windows](#windows)
- [Instalación paso a paso](#instalación-paso-a-paso)
  - [1. Clonar el repo](#1-clonar-el-repo)
  - [2. Levantar las bases de datos con Docker](#2-levantar-las-bases-de-datos-con-docker)
  - [3. Crear el entorno de Python e instalar dependencias](#3-crear-el-entorno-de-python-e-instalar-dependencias)
  - [4. Configurar variables de entorno](#4-configurar-variables-de-entorno)
  - [5. Instalar el frontend](#5-instalar-el-frontend)
- [Tu primer análisis](#tu-primer-análisis)
  - [Vía la interfaz web (recomendado)](#vía-la-interfaz-web-recomendado)
  - [Vía la API HTTP directamente](#vía-la-api-http-directamente)
  - [Vía un export de pg_stat_statements (modo workload)](#vía-un-export-de-pg_stat_statements-modo-workload)
- [Apagar y reiniciar](#apagar-y-reiniciar)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Documentación detallada](#documentación-detallada)
- [Tests y calidad](#tests-y-calidad)
- [Problemas comunes (troubleshooting)](#problemas-comunes-troubleshooting)
- [Uso de IA en el desarrollo](#uso-de-ia-en-el-desarrollo)
- [Licencia y créditos](#licencia-y-créditos)

---

## Qué hace PgPilot en 30 segundos

Pegas una query lenta. PgPilot:

1. **Conecta read-only** a tu base Postgres y le pide su plan con `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.
2. **Parsea el plan** a un árbol tipado y corre **19 detectores deterministas** (sequential scan sobre tabla grande, `OR` en lugar de `UNION`, `LIKE` con wildcard al inicio, función no-immutable en `WHERE`, sort en disco, falta de índice cubriente, subquery correlacionada, CTE materializada innecesaria, etc.).
3. **Sanitiza los literales** (strings, números, fechas, UUIDs, emails) antes de mandar nada al LLM. Tu BD nunca filtra valores reales a Anthropic.
4. **Llama a Claude** para que explique en lenguaje humano la detección y proponga una reescritura. Si el LLM contradice al motor, **gana el motor**.
5. **Valida cada recomendación** montando un schema efímero en un segundo Postgres (el *sandbox*), aplicando el `CREATE INDEX` propuesto, y comparando `EXPLAIN` antes/después con `pg_set_relation_stats` falseado. Si el planner no usa el índice, la recomendación se **descarta**.
6. **Te muestra** detecciones, recomendaciones con su SQL copiable, los 4 indicadores de validación (schema OK · no duplica índice · sintaxis válida · sandbox confirma mejora), y el comparativo *before/after* del plan.

Todo eso ocurre en menos de 5 segundos sobre una BD de 5 millones de filas.

---

## Arquitectura, en una imagen

```
                          ┌─────────────────────┐
                          │   Tu BD Postgres    │   (read-only forzado, timeout 5s)
                          │       AppDB         │
                          └──────────┬──────────┘
                                     │ EXPLAIN
                                     ▼
   ┌───────────┐   ┌────────────────────────┐   ┌─────────────────┐
   │ /conector ├──▶│  /motor (19 detectores)│──▶│   /backend       │
   │  schema   │   │  parser + recomendador │   │ FastAPI orquesta │
   │  stats    │   └────────────┬───────────┘   └────────┬────────┘
   │  sizes    │                │                        │
   └───────────┘                │ Detection +            │
                                │ Recommendation         │
                                ▼                        ▼
                       ┌────────────────┐      ┌─────────────────┐
                       │  /sandbox      │      │  /ia            │
                       │  Postgres 18   │      │  sanitizador    │
                       │  efímero       │      │  prompts        │
                       │  EXPLAIN diff  │      │  Claude API     │
                       └────────┬───────┘      │  validación     │
                                │              │  cruzada        │
                                │              └────────┬────────┘
                                ▼                       ▼
                       sandbox_verdict        explanation + rewrite
                                │                       │
                                └────────────┬──────────┘
                                             ▼
                                    ┌────────────────┐
                                    │   /frontend    │
                                    │  React + Vite  │
                                    │  Monaco editor │
                                    │  tarjetas +    │
                                    │  before/after  │
                                    └────────────────┘
```

La **regla #1** del producto: el motor determinístico decide, el LLM explica. Si chocan, gana el motor. Documentado a fondo en [`docs/decisiones.md`](docs/decisiones.md) y [`docs/motor.md`](docs/motor.md).

---

## Antes de empezar — Prerequisitos

Necesitas tres cosas instaladas en tu computadora: **Git**, **Docker Desktop**, **Python 3.11+** y **Node.js 20+**. Sigue la ruta de tu sistema operativo. Si todo esto ya está instalado y verificado, salta a [Instalación paso a paso](#instalación-paso-a-paso).

> Calcula **30-45 min** la primera vez si nunca instalaste nada de esto, y unos **15 min** la primera vez que levantes el proyecto (Docker descarga las imágenes y AppDB siembra 5 millones de filas en la primera corrida).

### macOS

Funciona desde macOS 12 (Monterey). Apple Silicon (M1/M2/M3/M4) e Intel ambos soportados.

#### 1. Herramientas de línea de comandos de Xcode

Las necesitas para Git, compiladores básicos y muchas otras cosas. Abre Terminal y corre:

```bash
xcode-select --install
```

Si te dice `command line tools are already installed`, perfecto, sigue.

#### 2. Homebrew

Es el gestor de paquetes estándar de macOS. Instálalo desde [brew.sh](https://brew.sh) o pegando esto en Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Al terminar, sigue las instrucciones que imprime al final (algo como `Add Homebrew to your PATH`). En Apple Silicon serán dos comandos `echo` con `eval`; córrelos tal cual te lo dice. Verifica:

```bash
brew --version    # debe imprimir "Homebrew 4.x.x"
```

#### 3. Git

Si ya tienes Xcode CLI, Git viene incluido. Si no:

```bash
brew install git
git --version    # debe imprimir 2.30+
```

#### 4. Docker Desktop

Descarga el instalador desde [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop). Elige **Apple Silicon** o **Intel** según tu Mac (Menú Apple → Acerca de este Mac).

1. Abre el `.dmg` y arrastra Docker a `Applications`.
2. Abre Docker Desktop. Acepta los términos. Te puede pedir password para instalar el helper.
3. Espera el ícono de ballena verde en la barra superior — significa que Docker está corriendo.
4. Verifica:

```bash
docker --version           # Docker version 24+
docker compose version     # Docker Compose version v2+
```

> **Memoria recomendada:** en Docker Desktop → Settings → Resources, sube la RAM a **al menos 4 GB** (ideal 6 GB). AppDB necesita ~2 GB en disco y unos cuantos cientos de MB en RAM mientras siembra los 5 millones de filas.

#### 5. Python 3.11 o superior

macOS trae Python 3, pero la versión es vieja. Instala una versión moderna con Homebrew:

```bash
brew install python@3.12
python3.12 --version    # debe imprimir Python 3.12.x
```

> Para los comandos del resto del README puedes usar `python3` si tu PATH ya apunta a 3.11+. Verifica con `python3 --version`. Si imprime 3.9 o menos, usa `python3.12` explícitamente en cada paso.

#### 6. Node.js 20 LTS o superior (para el frontend)

```bash
brew install node@20
node --version    # v20.x.x o superior
npm --version     # 10.x.x o superior
```

Si `node` no es reconocido después, corre `brew link --overwrite node@20` y reabre Terminal.

---

### Windows

Funciona en Windows 10 (build 19044+) y Windows 11. **Recomendado**: usar **WSL2** (Windows Subsystem for Linux) para que la experiencia con Docker, Python y Git sea idéntica a la de macOS/Linux. Si prefieres Windows nativo con PowerShell, también funciona pero requiere algunos ajustes; los marco en cada paso.

#### Ruta A: Con WSL2 (recomendado)

##### A.1 Habilitar WSL2

Abre **PowerShell como administrador** (botón derecho → Ejecutar como administrador) y corre:

```powershell
wsl --install
```

Esto instala Ubuntu por defecto, habilita la característica de Windows necesaria y configura WSL2 como la versión por defecto. **Reinicia** la PC cuando te lo pida.

Después del reinicio, Ubuntu se abrirá automáticamente. Te pedirá crear un usuario y password — son credenciales internas de tu Ubuntu, anótalas. Cuando termine, verifica desde PowerShell:

```powershell
wsl --status         # debe decir "Versión predeterminada: 2"
wsl -l -v            # debe listar Ubuntu con VERSION 2
```

A partir de aquí, **todos los comandos** de instalación del proyecto los corres dentro de la terminal de Ubuntu (puedes abrirla buscando "Ubuntu" en el menú Inicio).

##### A.2 Git, Python y Node dentro de Ubuntu/WSL2

Dentro de Ubuntu:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl build-essential python3 python3-pip python3-venv
python3 --version    # debe ser 3.11+; si imprime 3.10 o menos, ver nota abajo
git --version
```

> **Si tu Ubuntu trae Python 3.10 o menor** (Ubuntu 22.04), instala 3.12 explícitamente:
> ```bash
> sudo apt install -y software-properties-common
> sudo add-apt-repository -y ppa:deadsnakes/ppa
> sudo apt update
> sudo apt install -y python3.12 python3.12-venv python3.12-dev
> python3.12 --version
> ```
> En el resto del README, usa `python3.12` en lugar de `python3`.

Instala Node 20 LTS:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version    # v20.x.x
npm --version
```

##### A.3 Docker Desktop con backend WSL2

Descarga **Docker Desktop para Windows** desde [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop) e instálalo.

Al primer arranque, en el wizard:

1. Acepta los términos.
2. **Activa la opción "Use the WSL 2 based engine"** (suele venir activada por defecto).
3. En `Settings → Resources → WSL Integration`, **activa la integración con tu distro Ubuntu**.
4. Aplica y reinicia Docker Desktop.

Verifica desde **dentro de Ubuntu**:

```bash
docker --version
docker compose version
docker run hello-world    # debe imprimir un mensaje de éxito
```

> **Sube la memoria de Docker** en Settings → Resources → Advanced a al menos 4 GB (ideal 6 GB).

##### A.4 Clonar el repo dentro del filesystem de WSL

Esto es **crítico para el rendimiento**: clona el repo dentro del filesystem nativo de Ubuntu (`~/projects`, `~/code`, etc.), **no** dentro de `/mnt/c/Users/...`. Los archivos en `/mnt/c` se acceden vía un puente NTFS y son 5-10× más lentos para Docker y para `npm install`.

```bash
mkdir -p ~/code
cd ~/code
# (clonar más adelante, en el paso 1 de instalación)
```

#### Ruta B: Windows nativo (sin WSL2)

Es viable pero algunos detalles cambian. Si tu equipo de trabajo prefiere PowerShell:

##### B.1 Git para Windows

Descarga e instala desde [git-scm.com/download/win](https://git-scm.com/download/win). En el instalador:

- "Use Git from the command line and also from 3rd-party software" → seleccionado.
- "Checkout as-is, commit as-is" o "Checkout Windows-style, commit Unix-style" → ambos funcionan; recomendamos **"Checkout as-is, commit Unix-style"** para evitar problemas de CRLF en `.env` (ver troubleshooting).
- El resto, defaults.

Verifica desde PowerShell:

```powershell
git --version
```

##### B.2 Python 3.11 o superior

Descarga el instalador desde [python.org/downloads](https://www.python.org/downloads/). En el instalador:

- ✅ **"Add Python to PATH"** (CRÍTICO; sin esto el resto del README falla).
- ✅ "Install pip".

Verifica:

```powershell
python --version    # Python 3.11+ o 3.12+
pip --version
```

##### B.3 Node.js 20 LTS

Descarga el instalador LTS desde [nodejs.org](https://nodejs.org/). Acepta los defaults; al final también ofrecerá instalar herramientas de compilación adicionales para módulos nativos — **acepta** (es Chocolatey + build tools; tarda ~10 min pero te evita problemas después).

```powershell
node --version
npm --version
```

##### B.4 Docker Desktop (modo Hyper-V o WSL2)

Mismo instalador que la ruta A. Si tu Windows soporta WSL2, Docker te recomienda usarlo; acéptalo. Si no, usa el backend Hyper-V (requiere Windows Pro/Enterprise/Education).

##### B.5 Configurar finales de línea para evitar el bug de CRLF en `.env`

Este es el **problema más común** de Windows nativo con este proyecto. Si editas el archivo `.env` con el Bloc de notas o algunas versiones de VS Code sin configuración, Windows guarda los saltos de línea como `\r\n` (CRLF). Cuando el backend lee `ANTHROPIC_API_KEY`, el `\r` se pega al final del valor y la librería HTTP rechaza el header.

Para minimizar el riesgo, configura Git globalmente:

```powershell
git config --global core.autocrlf input
```

Y al editar `.env` más adelante, **usa VS Code** con el indicador inferior derecho cambiado a `LF` (no `CRLF`), o un editor de código moderno (Notepad++, Sublime, etc.). El código del backend además aplica `.strip()` defensivo a la API key — ver `ia/llm.py` —, pero la práctica recomendada es no introducir `\r` en primer lugar.

---

## Instalación paso a paso

Asumimos que ya tienes Git, Docker, Python y Node instalados según la sección anterior.

### 1. Clonar el repo

**macOS / Linux / WSL2:**

```bash
cd ~/code               # o donde quieras tener el proyecto
git clone https://github.com/andrulokuras07/pgpilot.git
cd pgpilot
```

**Windows nativo (PowerShell):**

```powershell
cd C:\Users\<TuUsuario>\code   # o donde quieras
git clone https://github.com/andrulokuras07/pgpilot.git
cd pgpilot
```

> Repo creado y mantenido por Andrés Angulo. Si el username de GitHub difiere, Andrés pasa el link exacto en el grupo de WhatsApp del equipo.

### 2. Levantar las bases de datos con Docker

Desde la raíz del repo:

```bash
docker compose up -d
```

Esto levanta dos contenedores Postgres:

| Contenedor | Versión | Puerto host | Para qué sirve |
|---|---|---|---|
| `appdb` | Postgres 16 | `localhost:5434` | La BD del cliente que PgPilot analiza. Incluye 5 millones de filas y 20 queries problemáticas plantadas. |
| `sandbox` | Postgres 18 | `localhost:5435` | Segundo Postgres efímero donde se validan las recomendaciones de índice con `EXPLAIN` antes/después. Sin datos reales. |

> **La primera vez tarda 3-4 minutos** porque Docker descarga las imágenes y AppDB ejecuta el seed completo de 5M filas y planta las 20 queries problemáticas en `pg_stat_statements`. Para ver el progreso:
>
> ```bash
> docker compose logs -f appdb
> ```
>
> Cuando veas `AppDB v1.0 ready with 20 planted problematic queries`, está lista. Ctrl-C para salir del `logs -f` (no apaga el contenedor).

Verifica que los dos contenedores estén `Up` y `healthy`:

```bash
docker compose ps
```

Salida esperada (resumida):

```
NAME      STATUS                   PORTS
appdb     Up X minutes (healthy)   0.0.0.0:5434->5432/tcp
sandbox   Up X minutes (healthy)   0.0.0.0:5435->5432/tcp
```

Prueba la conexión a AppDB:

```bash
docker exec -it appdb psql -U app_user -d appdb -c "SELECT count(*) FROM pg_stat_statements;"
```

Debe devolver un número **≥ 20**. Si lo hace, tu setup de Docker funciona. Si no, salta a [Troubleshooting](#problemas-comunes-troubleshooting).

### 3. Crear el entorno de Python e instalar dependencias

Todo el backend y los módulos (`/conector`, `/motor`, `/ia`, `/workload`, `/sandbox`) comparten un único entorno virtual en la raíz del repo. Esta decisión está documentada en [`docs/decisiones.md`](docs/decisiones.md).

**macOS / Linux / WSL2:**

```bash
# Desde la raíz del repo
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Windows nativo (PowerShell):**

```powershell
# Desde la raíz del repo
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

> Si PowerShell se queja con `running scripts is disabled on this system`, corre una sola vez (como tu usuario, no como admin):
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

Verifica que las dependencias se instalaron:

```bash
pip list | grep -E "fastapi|psycopg|sqlglot|pydantic"
```

Debes ver las cuatro con sus versiones.

> **Mantén el venv activado** durante toda esta sesión. Cada vez que abras una terminal nueva para correr el backend o pytest, tienes que volver a activar el venv con el comando correspondiente arriba.

### 4. Configurar variables de entorno

El backend lee credenciales y opciones desde un archivo `.env` en la raíz del repo. El proyecto incluye un `.env.example` con valores que coinciden con `docker-compose.yml`. Cópialo:

**macOS / Linux / WSL2:**

```bash
cp .env.example .env
```

**Windows nativo (PowerShell):**

```powershell
Copy-Item .env.example .env
```

Abre `.env` en tu editor y verifica que se ve así (los valores ya están listos para usar con los contenedores que acabas de levantar):

```dotenv
# Conexión a AppDB (BD del cliente que PgPilot analiza)
APPDB_HOST=localhost
APPDB_PORT=5434
APPDB_DB=appdb
APPDB_USER=app_user
APPDB_PASSWORD=app_pass

# Conexión al sandbox Postgres efímero
SANDBOX_HOST=localhost
SANDBOX_PORT=5435
SANDBOX_DB=sandbox
SANDBOX_USER=sandbox_user
SANDBOX_PASSWORD=sandbox_pass
```

Agrega también tu API key de Anthropic al final del archivo (si la tienes; el producto funciona sin ella con plantillas locales, ver más abajo):

```dotenv
# Clave de la API de Anthropic. Si no la tienes o no la quieres usar,
# pon LLM_ENABLED=false y el producto opera con plantillas locales (R5).
ANTHROPIC_API_KEY=sk-ant-tu-key-aqui
LLM_ENABLED=true
```

Cómo obtener una API key: ve a [console.anthropic.com](https://console.anthropic.com), crea cuenta, ve a **API Keys** y genera una. Tiene crédito gratuito inicial; nuestro caso de uso de demo consume centavos.

> **Windows nativo**: al guardar `.env`, asegúrate de que el editor use saltos de línea **LF** (no CRLF). En VS Code, mira la esquina inferior derecha — si dice `CRLF`, haz click y cámbialo a `LF`. Si esto se te olvida, el backend hará `.strip()` defensivo a la key, pero es buena práctica guardarlo bien desde el inicio.

### 5. Instalar el frontend

El frontend es una SPA en React + Vite con editor Monaco. Vive en `/frontend` y tiene su propio `package.json` y su propio `node_modules`.

```bash
cd frontend
npm install
cd ..
```

> La primera vez `npm install` tarda **1-3 minutos** (descarga unos 300 MB de dependencias). Verás muchos warnings de `deprecated`; son normales en el ecosistema npm y no afectan al producto.

Listo. Si llegaste hasta aquí sin errores, tienes el producto instalado completo. Si algo falló, salta a [Troubleshooting](#problemas-comunes-troubleshooting).

---

## Tu primer análisis

Hay tres formas equivalentes de correr tu primer análisis: por la UI web (lo más visual), por la API HTTP (lo más rápido para verificar que todo funciona), o subiendo un export de `pg_stat_statements` (el caso de uso de workload analysis).

### Vía la interfaz web (recomendado)

Necesitas **dos terminales abiertas en simultáneo**: una para el backend y otra para el frontend. Y los contenedores de Docker deben estar arriba (verifica con `docker compose ps`).

#### Terminal 1 — Backend

**macOS / Linux / WSL2:**

```bash
# Desde la raíz del repo, con el venv activado
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

**Windows nativo (PowerShell):**

```powershell
# Desde la raíz del repo, con el venv activado
.venv\Scripts\Activate.ps1
uvicorn backend.main:app --reload --port 8000
```

Espera ver algo así:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [...]
INFO:     Started server process [...]
INFO:     Application startup complete.
```

Si en los logs ves `AppDB conectada y snapshot extraído (8 tablas).` y `Sandbox pool conectado.`, todo está enchufado correctamente. Verifica el healthcheck en otra ventana:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

#### Terminal 2 — Frontend

```bash
cd frontend
npm run dev
```

Salida esperada:

```
  VITE v6.4.2  ready in XXX ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

Abre [http://localhost:5173](http://localhost:5173) en tu navegador. Verás el editor Monaco con una query de ejemplo pre-cargada y un botón **Analizar**.

#### Correr el análisis

1. En el editor, deja la query de ejemplo o pega una propia. Una query buena para empezar (es Q01 de las 20 problemáticas que AppDB tiene plantadas):

   ```sql
   SELECT * FROM posts WHERE author_id = 12345;
   ```

2. Click en **Analizar**. En 2-3 segundos verás:
   - Una tarjeta de **detección** indicando *Sequential Scan sobre tabla grande con índice disponible* (detector C1) con su nivel de confianza.
   - Una tarjeta de **recomendación** con el `CREATE INDEX` propuesto, la explicación del LLM y los **4 indicadores de validación** R3 (verdes ✓ todos).
   - Un panel **before/after** que muestra cómo cambia el plan de `Seq Scan` a `Index Scan` después de aplicar el índice.

Felicidades — corriste tu primer análisis. Pega otras queries problemáticas para ver el resto de detectores en acción. Tienes 20 plantadas en AppDB; algunas de las queries representativas:

```sql
-- D8: LIKE con wildcard al inicio
SELECT * FROM posts WHERE content LIKE '%urgent%';

-- D6: función no-immutable en WHERE
SELECT * FROM posts WHERE LOWER(content) = 'hello world';

-- D2: OR sobre columnas distintas
SELECT * FROM posts WHERE author_id = 123 OR view_count > 1000;
```

### Vía la API HTTP directamente

Útil para verificar que el backend responde sin pasar por el frontend. El backend debe estar corriendo (Terminal 1 del paso anterior).

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM posts WHERE author_id = 12345;"}'
```

La respuesta es un JSON con la forma:

```json
{
  "detections": [
    { "code": "C1", "type": "seq_scan_on_large_table", "confidence": 1.0, "evidence": { "...": "..." } }
  ],
  "recommendations": [
    {
      "kind": "create_index",
      "table": "public.posts",
      "create_index_sql": "CREATE INDEX idx_posts_author_id ON public.posts (author_id);",
      "explanation": { "text": "...", "source": "llm" },
      "sandbox_verdict": "validated",
      "sandbox_plan_comparison": { "...": "..." },
      "validations": {
        "schema_ok": true,
        "no_duplicate_index": true,
        "syntax_valid": true,
        "sandbox_improves": true
      }
    }
  ],
  "errors": [],
  "partial": false
}
```

El contrato completo del endpoint está documentado en [`backend/CLAUDE.md`](backend/CLAUDE.md).

### Vía un export de pg_stat_statements (modo workload)

Si en lugar de analizar una query individual quieres analizar el conjunto de queries más pesadas de tu producción:

1. En tu Postgres productivo (no en AppDB), exporta `pg_stat_statements`:

   ```sql
   COPY (
     SELECT query, calls, total_exec_time, mean_exec_time, rows
     FROM pg_stat_statements
     ORDER BY total_exec_time DESC
     LIMIT 100
   ) TO '/tmp/stat_statements.csv' WITH CSV HEADER;
   ```

2. Sube el CSV a PgPilot por la pestaña **Workload Analysis** del frontend, o vía API:

   ```bash
   curl -X POST http://localhost:8000/workload \
     -F "file=@/ruta/a/stat_statements.csv"
   ```

3. PgPilot calcula el ranking por `total_exec_time` (no por frecuencia: una query lenta que corre 10 veces duele más que una rápida que corre 10.000) y devuelve el **top 10**. En el frontend, click en cualquier fila → abre esa query en el flujo `/analyze` para optimizarla.

---

## Apagar y reiniciar

Para apagar todo cuando terminas tu sesión:

- En Terminal 2 (frontend): `Ctrl-C`.
- En Terminal 1 (backend): `Ctrl-C`.
- Para apagar los contenedores Docker (los datos se preservan):

  ```bash
  docker compose down
  ```

La próxima vez que regreses al proyecto:

```bash
docker compose up -d           # arranca AppDB + sandbox (rápido; ya están sembrados)
source .venv/bin/activate      # o .venv\Scripts\Activate.ps1 en Windows
uvicorn backend.main:app --reload --port 8000
# en otra terminal:
cd frontend && npm run dev
```

Para **destruir todo el estado de las BDs** (raro; útil si quieres reseed limpio o cambias init scripts):

```bash
docker compose down -v
docker compose up -d           # vuelve a tardar 3-4 min sembrando AppDB
```

---

## Estructura del repositorio

```
pgpilot/
├── CLAUDE.md              Arquitectura general (regla #1, stack, convenciones).
├── RULES.md               Reglas del proyecto (R1..R15).
├── PROGRESS.md            Bitácora cronológica (entradas nuevas arriba).
├── PgPilot_Backlog.md     80 actividades del proyecto agrupadas por fase.
├── README.md              Este archivo.
├── docker-compose.yml     Define AppDB y sandbox.
├── .env.example           Plantilla de variables de entorno.
├── requirements.txt       Dependencias Python (raíz del monorepo).
├── pyproject.toml         Config de pytest, black, isort.
│
├── conector/              Conexión a Postgres (read-only forzado), schema, sizes, stats, cache, modo offline.
├── motor/                 Parser de EXPLAIN + 19 detectores deterministas + recomendador.
├── ia/                    Sanitizador de literales, prompts a Claude, validación Pydantic + cruzada, plantillas locales.
├── workload/              Parser de pg_stat_statements + scoring por total_exec_time.
├── sandbox/               Postgres efímero con stats falseadas, EXPLAIN before/after, cleanup automático.
├── backend/               FastAPI que orquesta: /analyze, /workload, /health.
├── frontend/              React + Vite + Monaco editor + tarjetas + before/after.
│
├── docs/
│   ├── README.md          Índice de la documentación.
│   ├── decisiones.md      Stack y decisiones de arquitectura razonadas.
│   ├── conector.md        Doc externo del módulo de conexión.
│   ├── motor.md           Doc externo del motor (catálogo de los 19 detectores).
│   ├── ia.md              Doc externo de la capa de IA (crítico para Q&A de Demo Day).
│   ├── sandbox.md         Doc externo del sandbox.
│   ├── patterns/          Catálogo de anti-patterns (uno por archivo .md).
│   └── briefs/            PDFs originales del proyecto.
│
├── business/              Investigación competitiva, persona, pricing, GTM, pitch.
├── infra/appdb/           Init scripts + postgresql.conf de AppDB.
├── tests/                 Tests automatizados, mismo árbol que los módulos.
└── scripts/               Scripts auxiliares (medición de cobertura, etc.).
```

Cada módulo de código tiene un `CLAUDE.md` interno con detalles para devs/agentes que trabajan dentro del repo. La documentación de cara a usuarios externos vive en `/docs`.

---

## Documentación detallada

| Documento | Para qué |
|---|---|
| [`docs/README.md`](docs/README.md) | Índice maestro de toda la documentación. |
| [`docs/conector.md`](docs/conector.md) | API del conector: cómo conectar a tu Postgres, extraer schema, usar el modo offline con bundle JSON. |
| [`docs/motor.md`](docs/motor.md) | Arquitectura del motor determinístico, catálogo de los 19 detectores con sus reglas, cómo agregar un detector nuevo. |
| [`docs/ia.md`](docs/ia.md) | Qué se sanitiza y cómo, schema del prompt, validaciones cruzadas, garantías para el usuario (sección crítica para la defensa). |
| [`docs/sandbox.md`](docs/sandbox.md) | Por qué no se copian datos del cliente, cómo se falsean stats con `pg_set_relation_stats`, qué timeouts aplican, cleanup. |
| [`docs/patterns/`](docs/patterns/) | Catálogo de anti-patterns, uno por archivo, con regla de detección, recomendación y ejemplos. |
| [`docs/decisiones.md`](docs/decisiones.md) | Stack elegido y decisiones de arquitectura con sus alternativas descartadas y trade-offs. |
| [`CLAUDE.md`](CLAUDE.md) | Arquitectura general — leer antes de tocar código. |
| [`RULES.md`](RULES.md) | Reglas del proyecto (R1..R15). |
| [`PROGRESS.md`](PROGRESS.md) | Bitácora cronológica de avances y decisiones. |

---

## Tests y calidad

El proyecto usa `pytest` para todo el backend y los módulos. Algunos tests requieren los contenedores Docker arriba (`@pytest.mark.integration`).

```bash
# Con el venv activado, desde la raíz del repo:

# Todos los tests (incluyendo integration; requiere docker compose up)
pytest

# Solo unit tests (no requieren Docker, mucho más rápido)
pytest -m "not integration and not llm"

# Tests con LLM real (requieren ANTHROPIC_API_KEY válida)
pytest -m llm

# Coverage del backend (config en pyproject.toml [tool.coverage])
pytest -m "not integration and not llm" --cov --cov-report=term-missing
```

### Cobertura actual del backend (F16)

| Métrica | Valor |
|---|---|
| **Cobertura total** | **85.3%** |
| Líneas cubiertas | 2 119 / 2 420 |
| Branches cubiertos | 642 / 816 |
| Suite ejecutada | `pytest -m "not integration and not llm"` (403 unit tests, ~8 s) |
| Mínimo exigido (F16 / `fail_under`) | 50% |
| Bonus rúbrica | **+3 pts** desbloqueados |

> El número se mide sobre los módulos del backend (`backend/`, `conector/`, `ia/`, `motor/`, `sandbox/`, `workload/`). Tests, scripts auxiliares y el frontend quedan excluidos vía `[tool.coverage.run]` en `pyproject.toml`. Los tests `integration` y `llm` se omiten porque dependen de Docker / API key viva; al ejecutarlos en CI sumarían cobertura adicional sobre `sandbox/explain.py`, `sandbox/setup.py` y `conector/schema.py`, que hoy son los archivos con mayor superficie sin cubrir.

Para regenerar el número desde cero:

```bash
pytest -m "not integration and not llm" --cov --cov-report=term-missing
```

El comando falla si la cobertura cae bajo el 50% (`fail_under = 50` en `pyproject.toml`), lo que protege contra regresiones futuras.

Linter y formato (corre antes de cada commit):

```bash
black .
isort .
```

El frontend usa Vite. Para chequear que compila limpio:

```bash
cd frontend
npm run build
```

---

## Problemas comunes (troubleshooting)

### `docker compose up` falla con "port already in use"

Otro Postgres está ocupando 5434 o 5435. Identifícalo y detenlo, o cambia los puertos en `docker-compose.yml` (y reflejalo en `.env`).

**macOS / Linux / WSL2:**

```bash
sudo lsof -i :5434
sudo lsof -i :5435
```

**Windows nativo (PowerShell):**

```powershell
netstat -ano | findstr :5434
netstat -ano | findstr :5435
```

### `docker compose up` se queda colgado en el seed de AppDB más de 5 minutos

Sube la RAM asignada a Docker Desktop a **al menos 4 GB** (Settings → Resources → Memory). El seed de 5M filas requiere unos 800 MB activos. Después:

```bash
docker compose down -v
docker compose up -d
```

### El contenedor `appdb` está en estado `unhealthy`

Mira los logs:

```bash
docker compose logs appdb
```

Si ves errores de espacio en disco, libera espacio (AppDB necesita ~700 MB) o cambia el directorio raíz de Docker. Si ves errores de permisos en Windows nativo, probablemente WSL2 no tiene acceso al directorio del proyecto; mueve el repo a tu home de Ubuntu (`~/code/pgpilot`).

### `pip install -r requirements.txt` falla en Windows con error de compilación de `psycopg`

`psycopg[binary]` viene con wheels precompilados; si igual te falla, asegúrate de tener Microsoft Visual C++ Build Tools instalado, o cambia a WSL2 (ruta A) donde esto no aplica.

### El backend arranca pero `/analyze` responde 503

Significa que el backend no pudo conectar a AppDB. Verifica:

1. Los contenedores están arriba: `docker compose ps` muestra `appdb` como `healthy`.
2. Tu `.env` tiene `APPDB_HOST=localhost` (no `appdb`, que es el nombre del contenedor para uso interno de Docker).
3. Probaste la conexión manualmente: `psql -h localhost -p 5434 -U app_user -d appdb` (te pide password: `app_pass`).

### El backend arranca pero `/analyze` ignora el LLM y cae a plantillas locales

El backend lo loggea como `LLMDisabledError`. Causas:

1. **No hay `ANTHROPIC_API_KEY`** en `.env`. Agrégala.
2. **Tienes `LLM_ENABLED=false`** en `.env`. Quítalo o ponlo en `true`.
3. **La key tiene CRLF al final** (típico de Windows nativo cuando editas `.env` con Bloc de notas). Reabre `.env` en VS Code, cambia el indicador de la esquina a `LF`, guarda. El código del backend además aplica `.strip()` defensivo, pero la práctica recomendada es no introducir `\r` desde el editor.

### `npm install` en el frontend falla con errores de permisos en macOS

```bash
sudo chown -R $(whoami) ~/.npm
```

Luego reintenta.

### `npm run dev` arranca el frontend pero el botón "Analizar" devuelve "Error de red"

El frontend espera que el backend esté en `http://localhost:8000`. Asegúrate de que el backend está corriendo en Terminal 1 y que `curl http://localhost:8000/health` responde `{"status":"ok"}`. Si CORS bloquea la request en consola del navegador, verifica que estás abriendo el frontend en `http://localhost:5173` y no en `http://127.0.0.1:5173` (el backend permite explícitamente el primero por R12).

### Quiero correr el producto sin AppDB del profesor, contra mi propia BD

Edita `.env` apuntando `APPDB_HOST/PORT/DB/USER/PASSWORD` a tu BD productiva. Asegúrate de que el usuario tenga `pg_read_all_stats` y permisos sobre las tablas que quieres analizar. El conector fuerza read-only (R7); no puede modificar tu BD ni accidentalmente.

Si tu BD productiva tiene datos sensibles y no quieres abrir conexión, usa el **modo offline**: corre PgPilot en tu entorno, genera el bundle con `export_bundle()` (documentado en [`docs/conector.md`](docs/conector.md)), y carga ese bundle en una instancia de PgPilot aislada.

---

## Uso de IA en el desarrollo

> **Declaración explícita conforme al Criterio 1.2 de la rúbrica del curso.** La rúbrica penaliza -5 puntos no declarar el uso de IA; esta sección lo declara de forma transparente.

PgPilot fue construido con asistencia activa de modelos de IA generativa, principalmente **Claude (Anthropic)** a través de la interfaz de **Claude Code**. El equipo de 5 personas usó la IA como par programador, no como autor único, manteniendo siempre el control sobre las decisiones arquitectónicas, el código mergeado a `main` y la responsabilidad sobre los tests.

**Cómo se usó la IA:**

- **Generación inicial de código** para módulos con contrato claro (parser de EXPLAIN, sanitizador de literales, plantillas locales). Cada commit fue revisado y testeado por una persona del equipo antes de mergear.
- **Refactorización y documentación** de módulos existentes. Los `CLAUDE.md` internos de cada módulo y los docs externos (`docs/conector.md`, `docs/motor.md`, `docs/ia.md`, `docs/sandbox.md`) se redactaron con asistencia de Claude a partir del código real, verificando que cada firma y cada constante coincidieran con el código mergeado.
- **Tests automatizados**: muchos casos de prueba (especialmente los que cubren ramas de error y casos límite) fueron sugeridos por la IA y refinados a mano.
- **Bitácora del proyecto** (`PROGRESS.md`) — las entradas se redactaron con asistencia de IA a partir de los cambios reales del commit.

**Cómo NO se usó la IA dentro del producto final:**

- **El motor determinístico es código humano** revisado línea por línea. Los detectores de anti-patterns no usan IA en runtime — siguen la **regla #1** del proyecto: el motor decide, el LLM solo explica. Si el LLM contradice al motor, gana el motor.
- **La capa de IA del producto** (la que llama a Claude en runtime para explicar detecciones al usuario) está **encapsulada en `/ia`** con sanitización fuerte (R4), validación cruzada contra el snapshot del schema (R3+R14), y caída a plantillas locales (R5) si la API falla, está apagada, o si la respuesta no pasa validación. Detalles completos en [`docs/ia.md`](docs/ia.md).
- **Las decisiones de arquitectura** fueron tomadas por el equipo y están registradas con sus alternativas descartadas en [`docs/decisiones.md`](docs/decisiones.md).

**Marcadores en el código:**

Los archivos generados con asistencia significativa de Claude llevan el comentario `# HECHO CON CLAUDE` en su cabecera (ver `.gitignore`, `docker-compose.yml`, etc.). Esto permite a un revisor identificar de un vistazo qué partes del repo fueron asistidas por IA.

**Modelos usados:**

- **Claude Sonnet 4.5/4.6** (en Claude Code) — generación y refactorización de código, redacción de documentación.
- **Claude Sonnet 4.6** (vía Anthropic API) — capa de IA en runtime del producto, sirviendo explicaciones al usuario final.

---

## Licencia y créditos

Proyecto académico — Universidad Anáhuac Querétaro, materia **SIS2404 (Bases de Datos Avanzadas)**, ciclo Primavera 2026. Equipo: Andrés Angulo, Alexander, Diego, Emilio, Regina.

**Stack:** Python 3.11+ · FastAPI · psycopg 3 · sqlglot · Pydantic 2 · React 18 · Vite 6 · Monaco · Anthropic Claude API · Postgres 16/18 · Docker Compose.

Reportes de bugs o preguntas: abre un issue en el repo o pinguea al equipo en el grupo de WhatsApp.
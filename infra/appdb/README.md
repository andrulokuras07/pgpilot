# AppDB — archivos de inicialización

Esta carpeta contiene los archivos necesarios para levantar **AppDB**, la base de datos demo oficial entregada por el profesor de SIS2404 sobre la cual se evalúa PgPilot.

## Origen
Archivos copiados del repositorio Docker entregado por el profesor al inicio del proyecto. La documentación original del profesor (esquema, queries plantadas, troubleshooting) está en [`README_PROFESOR.md`](./README_PROFESOR.md).

## Contenido
- `init/` — scripts SQL ejecutados al crear el contenedor por primera vez (orden alfabético). Incluyen creación de schema, seed de ~5M filas, y plantado de las 20 queries problemáticas en `pg_stat_statements`.
- `postgresql.conf` — configuración custom con `work_mem` bajo a propósito para forzar spill a disco en algunas queries problemáticas.
- `README_PROFESOR.md` — documentación original entregada por el profesor.

## Cómo se levanta AppDB en este repo
Desde la raíz del repo:
```bash
docker compose up -d appdb
```
Puerto: `5434`. Credenciales: `app_user` / `app_pass`. Base: `appdb`.

La primera vez tarda 3-4 minutos mientras se siembra. Ver progreso con:
```bash
docker compose logs -f appdb
```
Listo cuando aparece `AppDB v1.0 ready with 20 planted problematic queries`.

## Si el profesor actualiza AppDB (v2 para Demo Day)
1. Sustituir `init/` y `postgresql.conf` por la versión nueva.
2. `docker compose down -v` para borrar el volumen viejo.
3. `docker compose up -d appdb` para recrear con seed nuevo.
4. Registrar la actualización en `PROGRESS.md`.
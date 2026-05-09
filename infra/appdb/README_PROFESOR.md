# AppDB — Base de datos demo para PgPilot

Base de datos de demostración para el proyecto **PgPilot** (SIS2404).
Contiene una red social ficticia (tipo Twitter/X simplificado) con 5
millones de filas y 20 queries problemáticas plantadas que tu producto
debe analizar y para las cuales debe recomendar mejoras.

> ⚠️ **Esta BD es grande (~700 MB).**
> Se necesita ese tamaño para que los planes de ejecución (`EXPLAIN`)
> sean realistas y los anti-patterns se distingan claramente. Asegúrate
> de tener al menos 2 GB de espacio libre antes de levantarla.

---

## Cómo levantarla

```bash
docker compose up -d
```

La primera vez tarda **3-4 minutos** mientras se crea el schema, se siembran
los datos y se ejecutan las queries problemáticas. Para ver el progreso:

```bash
docker compose logs -f db
```

Cuando veas `AppDB v1.0 ready with 20 planted problematic queries`,
está lista.

---

## Cómo conectarte

| Parámetro | Valor |
|---|---|
| Host | `localhost` |
| Puerto | `5434` (no 5432, para coexistir con TiendaDB y FintechDB) |
| Base de datos | `appdb` |
| Usuario | `app_user` |
| Contraseña | `app_pass` |

Desde la línea de comandos:

```bash
docker exec -it appdb psql -U app_user -d appdb
```

O desde un cliente externo (DBeaver, pgAdmin, psql local):

```bash
psql -h localhost -p 5434 -U app_user -d appdb
```

---

## Esquema

8 tablas que simulan una red social:

| Tabla | Descripción | Filas (modo base) |
|---|---|---|
| `users` | Usuarios de la plataforma | 50,000 |
| `posts` | Publicaciones | 500,000 |
| `comments` | Comentarios sobre posts | 1,000,000 |
| `likes` | Likes a posts | 1,000,000 |
| `follows` | Relaciones de seguidores | 200,000 |
| `notifications` | Notificaciones (95% read=true) | 800,000 |
| `tags` | Hashtags / temas | 6,000 |
| `post_tags` | Relación N:M posts-tags | 1,500,000 |

Total: **~5 millones de filas**, ~700 MB en disco.

---

## Modo grande (opcional)

Si quieres probar tu producto contra un volumen aún mayor (~80M filas,
~10 GB), puedes escalar:

```bash
docker exec -i appdb psql -U app_user -d appdb < scripts/scale_to_large.sql
```

Tarda 15-30 minutos. Las queries problemáticas siguen activas.

⚠️ Para el Demo Day usa el **modo base**. El modo grande es para validar
que tu producto escala con BDs reales de empresas grandes.

---

## ¿Qué queries plantamos?

No te lo voy a decir. **Esa es la chamba de tu producto: detectarlas
analizando `pg_stat_statements`, sus planes de ejecución, y recomendando
mejoras.**

Lo que sí te puedo decir:

- Hay **20 queries problemáticas** plantadas, cada una ejecutada varias
  veces para que aparezcan en `pg_stat_statements`.
- Los anti-patterns cubiertos incluyen (entre otros):
  sequential scan en tabla grande, OR vs UNION, LIKE con wildcard al
  inicio, función no-immutable en WHERE, sort en disco, nested loop
  ineficiente, falta de índice cubriente, subquery correlacionada,
  estadísticas obsoletas, falta de índice parcial, COUNT(*) lento,
  CTE materializada innecesaria, etc.
- Tu producto debe identificar correctamente al menos **15 de 20** para
  sacar puntaje básico en el Criterio 2.1 de la rúbrica.
- Para sacar 12/12 debes acertar 18-20 (≥90%).
- Cada recomendación incorrecta o que no se valide con el motor
  determinístico te resta 0.5 pts (tope -3).
- En el Demo Day el profesor entregará una **versión 2** con queries
  disfrazadas y algunas nuevas. Si tu producto las analiza correctamente
  sin haberlas visto, ganas hasta +3 pts de bonus.

---

## Cómo evitar hardcodear

Tu producto NO debe asumir cosas como:

- "La query problemática siempre tiene la palabra `bitcoin`."
- "El antipatrón está en la tabla `posts` específicamente."
- "El `LIMIT 50` con `ORDER BY created_at` siempre es de comments."

Tu producto SÍ debe pensar de forma genérica:

- "Para cada query en `pg_stat_statements`, parseo su `EXPLAIN
  (ANALYZE, BUFFERS, FORMAT JSON)` y busco patrones genéricos."
- "Si veo un `Seq Scan` sobre tabla con > 100K filas Y la query filtra
  por una columna específica, sugiero crear índice."
- "Si veo `Sort Method: external merge Disk`, sugiero aumentar
  work_mem o reescribir la query con `LIMIT`."
- "Si veo mismatch grande entre `rows estimated` y `rows actual` (>5x),
  sugiero `ANALYZE` sobre las tablas involucradas."

Esto te protegerá cuando llegue la BD demo v2 el día del Demo Day.

---

## Acceso a los planes de ejecución

Tu producto necesita poder ejecutar `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`
sobre cualquier query. El usuario `app_user` tiene los permisos necesarios.

Para queries con costos altos (Q20: `SELECT count(*) FROM posts`), considera:
- Usar `EXPLAIN` sin `ANALYZE` para no ejecutar de verdad
- Limitar tiempo con `SET statement_timeout`
- Ejecutar en una réplica si tu producto lo soporta

---

## Combinación determinístico + IA

Recordatorio del brief: tu producto NO debe depender 100% del LLM. Para
cada anti-pattern detectado:

1. **Detección determinística** (parser de plan, reglas estáticas) =
   identifica QUE hay un problema.
2. **IA con guardrails** = genera la EXPLICACIÓN pedagógica y la
   sugerencia de rewrite.
3. **Validación determinística post-IA** = verifica que la sugerencia
   del LLM sea sintácticamente válida y mejore métricas reales (con
   `EXPLAIN` antes/después en sandbox).

Si en el Q&A defienden "el LLM lo hizo todo", pierden Criterio 1.

---

## Privacidad de datos

Las queries en `pg_stat_statements` aparecen normalizadas (los literales
se reemplazan por `$1`, `$2`...). Aún así, tu producto debe tener una
capa de **sanitización** antes de enviar queries al LLM, por si algún
literal se cuela. Esto es feature de venta importante para empresas con
datos sensibles.

---

## Reset

Si necesitas reiniciar la BD desde cero:

```bash
docker compose down -v
docker compose up -d
```

⚠️ El comando `down -v` borra todos los datos. Vuelve a tardar 3-4 min
en sembrar.

---

## Problemas comunes

**Espacio en disco insuficiente:** AppDB ocupa ~700 MB. Verifica con
`docker system df`.

**El seed tarda más de 5 minutos:** revisa que tu Docker tenga al menos
2 GB de RAM asignada. En Docker Desktop puedes ajustarlo en Settings.

**Puerto 5434 ocupado:** otro Postgres está usando 5434. Edita el
`docker-compose.yml` o detén el otro servicio.

**`pg_stat_statements` está vacío:** el archivo `03_plant_problems.sql`
hace `pg_stat_statements_reset()` al inicio. Después de ejecutarlo se
llena con las 20 queries plantadas.

---

## Una última cosa

Esta BD está diseñada para **enseñarte** sobre análisis de queries
en bases de datos reales. Cada anti-pattern plantado es uno que aparece
en producciones reales y ha causado caídas de servicios y multas
contractuales. Cuando tu producto los detecte y recomiende correctamente,
no solo estarás sacando buena nota: estarás construyendo algo que cualquier
empresa con Postgres y desarrolladores backend pagaría por usar.

Mucha suerte.

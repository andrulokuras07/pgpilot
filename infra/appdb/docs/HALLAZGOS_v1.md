# AppDB v1.0 — Lista Maestra de Hallazgos

⚠️ **DOCUMENTO CONFIDENCIAL — SOLO PROFESOR** ⚠️

No compartir con alumnos. Este documento es la verdad de fondo para
evaluar el Criterio 2.1 (Cobertura) del proyecto PgPilot.

---

## Resumen ejecutivo

- **Total de queries problemáticas plantadas: 20** (Q01-Q20)
- Distribución: cada query exhibe un anti-pattern específico que el
  producto debe detectar al analizar `pg_stat_statements` + `EXPLAIN`.
- Para 12/12 pts en cobertura: detectar 18-20 (≥90%)
- Para 10/12 pts: detectar 15-17 (75-89%)
- Para 8/12 pts: detectar 12-14 (60-74%)

---

## Cómo se evalúa correctamente cada query

Para cada query, el producto debe:
1. **Identificarla** en `pg_stat_statements` como problemática.
2. **Detectar el anti-pattern** específico (ver lista abajo).
3. **Recomendar una solución concreta** (índice, rewrite, etc.).
4. **Validar la solución** con `EXPLAIN` antes/después en sandbox (idealmente).

Si solo identifica la query como "lenta" sin diagnosticar el anti-pattern,
cuenta como **detección parcial** (0.5 pts en lugar de 1).

---

## Catálogo de queries plantadas

### Q01 — Sequential scan sobre posts (sin índice en author_id)
- **Patrón en pg_stat_statements:** `SELECT * FROM posts WHERE author_id = $1`
- **Anti-pattern:** falta de índice causa Seq Scan sobre 500K filas
- **Detección esperada:** EXPLAIN muestra `Seq Scan on posts` con `Filter: (author_id = ...)` y `Rows Removed by Filter` muy alto
- **Recomendación esperada:** `CREATE INDEX idx_posts_author_id ON posts(author_id);`
- **Severidad:** ALTA

### Q02 — OR sobre dos columnas (debería ser UNION)
- **Patrón:** `SELECT id FROM posts WHERE author_id = $1 OR mentioned_user_id = $2`
- **Anti-pattern:** OR no permite usar dos índices simultáneamente; UNION sí
- **Detección esperada:** plan con `BitmapOr` o `Seq Scan` cuando ambas columnas están indexadas
- **Recomendación esperada:** reescribir como `UNION` de dos SELECT separados, o crear índice compuesto
- **Severidad:** MEDIA

### Q03 — LIKE con wildcard al inicio
- **Patrón:** `SELECT id FROM posts WHERE content LIKE $1` (donde $1 = `%texto%`)
- **Anti-pattern:** wildcard al inicio impide uso de índice B-tree
- **Detección esperada:** Seq Scan sobre tabla grande con filter por LIKE
- **Recomendación esperada:** usar `pg_trgm` con índice GIN, full-text search con `tsvector`, o cambiar a búsqueda por prefijo
- **Severidad:** MEDIA

### Q04 — Función no-immutable en WHERE
- **Patrón:** `SELECT count(*) FROM posts WHERE EXTRACT($1 FROM created_at) = $2`
- **Anti-pattern:** EXTRACT no es immutable y rompe uso de índice en `created_at`
- **Detección esperada:** Seq Scan donde podría usarse el índice de `created_at`
- **Recomendación esperada:** reescribir como rango `created_at >= 'YYYY-01-01' AND created_at < 'YYYY+1-01-01'`
- **Severidad:** MEDIA

### Q05 — Sort spill to disk
- **Patrón:** `SELECT u.username, count(l.id) FROM users u JOIN likes l ON ... GROUP BY u.username ORDER BY count(...) DESC`
- **Anti-pattern:** `work_mem` insuficiente causa que el sort/hash escriba a disco
- **Detección esperada:** EXPLAIN muestra `Sort Method: external merge Disk: NkB` o `temp_blks_written > 0` en pg_stat_statements
- **Recomendación esperada:** aumentar `work_mem` para esta query (`SET work_mem` por sesión), o reescribir con `LIMIT`
- **Severidad:** MEDIA-ALTA

### Q06 — Nested loop ineficiente sobre tabla grande
- **Patrón:** `SELECT p.id, c.content FROM posts p, comments c WHERE p.id = c.post_id AND p.author_id BETWEEN $1 AND $2`
- **Anti-pattern:** sintaxis JOIN implícita + estimación pesimista del planner produce nested loop costoso
- **Detección esperada:** EXPLAIN con `Nested Loop` sobre miles de filas
- **Recomendación esperada:** reescribir con `JOIN` explícito, agregar índice en `posts.author_id` (overlapped con Q01)
- **Severidad:** ALTA

### Q07 — SELECT * cuando solo se necesitan pocas columnas
- **Patrón:** `SELECT * FROM posts WHERE created_at > NOW() - INTERVAL $1`
- **Anti-pattern:** trae todas las columnas (incluyendo `content`, `media_url`) cuando podría hacerse index-only scan
- **Detección esperada:** comparación entre lo seleccionado y lo realmente usado por el caller (esto es difícil sin contexto adicional, aceptable que solo flag el SELECT *)
- **Recomendación esperada:** seleccionar columnas explícitas + índice cubriente
- **Severidad:** BAJA-MEDIA

### Q08 — Falta de índice cubriente
- **Patrón:** `SELECT id, created_at FROM posts WHERE author_id = $1 ORDER BY created_at DESC LIMIT $2`
- **Anti-pattern:** sin índice cubriente, Postgres tiene que ir al heap por cada fila
- **Detección esperada:** EXPLAIN muestra `Index Scan` + `Heap Fetches > 0`, o Seq Scan si Q01 no está resuelto
- **Recomendación esperada:** `CREATE INDEX ON posts(author_id, created_at DESC) INCLUDE (id);`
- **Severidad:** MEDIA

### Q09 — Subquery correlacionada (debería ser JOIN/LATERAL)
- **Patrón:** `SELECT id, (SELECT count(*) FROM comments WHERE post_id = posts.id) FROM posts WHERE author_id = $1`
- **Anti-pattern:** subquery se ejecuta una vez por cada fila del outer
- **Detección esperada:** EXPLAIN con `SubPlan` o `InitPlan` repetido
- **Recomendación esperada:** reescribir con `LEFT JOIN ... GROUP BY` o `LATERAL`
- **Severidad:** ALTA

### Q10 — Estadísticas obsoletas en tags
- **Patrón:** `SELECT count(*) FROM tags WHERE use_count > $1`
- **Anti-pattern:** después de un INSERT masivo sin ANALYZE, `pg_class.reltuples` está desactualizado
- **Evidencia:** `reltuples=1000` mientras `count(*)=6000` (ratio 6x)
- **Detección esperada:** comparación entre `rows estimated` y `rows actual` en EXPLAIN ANALYZE da diferencia >5x
- **Recomendación esperada:** `ANALYZE tags;` y reactivar autovacuum (`ALTER TABLE tags RESET (autovacuum_enabled);`)
- **Severidad:** ALTA

### Q11 — Falta de índice parcial
- **Patrón:** `SELECT id FROM notifications WHERE user_id = $1 AND read = $2` (con $2 = false)
- **Anti-pattern:** 95% de notifications tienen read=true, pero queries filtran por read=false. Un índice parcial sería mucho más pequeño y rápido.
- **Detección esperada:** índice estándar trae muchas filas que luego filtra; selectividad de read=false es ~5%
- **Recomendación esperada:** `CREATE INDEX idx_notifications_unread ON notifications(user_id) WHERE read = false;`
- **Severidad:** MEDIA

### Q12 — Cast implícito en columna indexada
- **Patrón:** `SELECT * FROM users WHERE username::text = $1`
- **Anti-pattern:** el cast en la columna impide uso del índice de `username`
- **Detección esperada:** Seq Scan donde podría usarse el índice
- **Recomendación esperada:** mover el cast al lado derecho (`WHERE username = $1::varchar`) o evitar comparar tipos distintos
- **Severidad:** MEDIA

### Q13 — Cardinality estimation error en JOIN multi-condición
- **Patrón:** `SELECT p.id, u.username FROM posts p JOIN users u ON ... WHERE u.is_verified = $1 AND u.is_active = $2 AND p.is_deleted = $3`
- **Anti-pattern:** planner asume independencia entre condiciones cuando hay correlación, subestima rows
- **Detección esperada:** ratio `rows actual / rows estimated` > 5 después del JOIN
- **Recomendación esperada:** crear `CREATE STATISTICS` multi-columna sobre `(is_verified, is_active)` o reescribir con CTEs intermedios
- **Severidad:** MEDIA

### Q14 — CTE materializada innecesariamente
- **Patrón:** `WITH active_users AS MATERIALIZED (...) SELECT count(*) FROM active_users JOIN posts ...`
- **Anti-pattern:** `MATERIALIZED` previene predicate push-down; sin él, Postgres 12+ puede inlinear
- **Detección esperada:** EXPLAIN muestra `CTE Scan` con muchas más filas de las que necesita el JOIN
- **Recomendación esperada:** quitar `MATERIALIZED` (default ahora es NOT MATERIALIZED en CTEs simples)
- **Severidad:** MEDIA

### Q15 — Index scan con alta selectividad de filtro
- **Patrón:** `SELECT id FROM posts WHERE created_at > $1 AND likes_count > $2`
- **Anti-pattern:** usa el índice de `created_at` pero filtra muchas filas en Recheck por `likes_count`
- **Detección esperada:** ratio entre filas escaneadas por el índice vs filas finales > 100
- **Recomendación esperada:** índice compuesto `(created_at, likes_count)` o índice expression `WHERE likes_count > 950`
- **Severidad:** BAJA-MEDIA

### Q16 — HAVING que debería ser WHERE
- **Patrón:** `SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = $1`
- **Anti-pattern:** filtrar por `author_id` después del GROUP BY es ineficiente; debería filtrarse antes
- **Detección esperada:** EXPLAIN muestra agregación sobre toda la tabla, luego filter post-aggregation
- **Recomendación esperada:** mover el filtro a `WHERE`: `WHERE author_id = $1 GROUP BY author_id`
- **Severidad:** MEDIA

### Q17 — IN con subquery (debería ser EXISTS)
- **Patrón:** `SELECT id FROM users WHERE id IN (SELECT author_id FROM posts WHERE created_at > $1)`
- **Anti-pattern:** IN con subquery materializa el conjunto; EXISTS hace short-circuit
- **Detección esperada:** EXPLAIN muestra `Hash Semi Join` o `Materialize` sobre subquery completa
- **Recomendación esperada:** reescribir como `WHERE EXISTS (SELECT 1 FROM posts WHERE ... AND author_id = users.id)`
- **Severidad:** BAJA-MEDIA

### Q18 — ORDER BY + LIMIT sin índice
- **Patrón:** `SELECT * FROM comments ORDER BY created_at DESC LIMIT $1`
- **Anti-pattern:** sin índice en `created_at`, Postgres debe sortear las 1M filas para sacar las top N
- **Detección esperada:** EXPLAIN muestra `Sort` sobre toda la tabla con costo enorme
- **Recomendación esperada:** `CREATE INDEX idx_comments_created_at ON comments(created_at DESC);`
- **Severidad:** ALTA

### Q19 — NOT IN con subquery posiblemente NULL
- **Patrón:** `SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts)`
- **Anti-pattern:** semántica peligrosa con NULL (si la subquery devuelve un NULL, el resultado es vacío) + lento
- **Detección esperada:** detector debe identificar el patrón `NOT IN (subquery)` y advertir
- **Recomendación esperada:** reescribir como `WHERE NOT EXISTS (SELECT 1 FROM posts WHERE author_id = users.id)`
- **Severidad:** ALTA (porque la trampa de NULL es bug silencioso)

### Q20 — COUNT(*) sobre tabla grande
- **Patrón:** `SELECT count(*) FROM posts;` (también en comments, likes, notifications)
- **Anti-pattern:** Postgres tiene que hacer visibility check de cada fila debido al MVCC
- **Detección esperada:** EXPLAIN muestra Seq Scan con costo proporcional a filas
- **Recomendación esperada:** usar estimación de `pg_stat_user_tables.n_live_tup` o mantener un contador denormalizado
- **Severidad:** BAJA (es trade-off conocido de Postgres)

---

## Cómo verificar manualmente

Antes del Demo Day, ejecuta estas queries para confirmar que todo está plantado:

```sql
-- Q01 verificación: posts.author_id sin índice
SELECT count(*) FROM pg_indexes WHERE tablename='posts' AND indexdef LIKE '%author_id%';
-- Esperado: 0

-- Q05 verificación: spillea con work_mem=1MB
SET work_mem = '1MB';
EXPLAIN (ANALYZE) SELECT u.username, count(l.id)
  FROM users u JOIN likes l ON l.user_id = u.id
  GROUP BY u.username ORDER BY count(l.id) DESC;
-- Buscar "Sort Method: external merge Disk"

-- Q10 verificación: stats obsoletas en tags
SELECT
  reltuples::bigint AS estimated,
  (SELECT count(*) FROM tags) AS actual
FROM pg_class WHERE relname = 'tags';
-- Esperado: estimated=1000, actual=6000

-- Q11 verificación: notifications con 95% read=true
SELECT read, count(*) FROM notifications GROUP BY read;
-- Esperado: ~760K true, ~40K false

-- Q18 verificación: comments.created_at sin índice
SELECT count(*) FROM pg_indexes WHERE tablename='comments' AND indexdef LIKE '%created_at%';
-- Esperado: 0

-- Verificación general: queries en pg_stat_statements
SELECT count(DISTINCT query) FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat%' AND query NOT LIKE 'BEGIN%';
-- Esperado: ~26 (las 20 plantadas + algunas variantes)
```

---

## Niveles de dificultad esperada

- **Fáciles (deberían detectar todos):** Q01, Q03, Q05, Q11, Q18, Q20
- **Medios:** Q02, Q04, Q07, Q08, Q09, Q10, Q12, Q14, Q16, Q17, Q19
- **Difíciles (separan al excelente):** Q06, Q13, Q15

Si la mayoría detecta menos del 50%, considerar bajar el umbral del
Criterio 2.1 o aclarar mejor la documentación pública sobre análisis
de planes.

---

## Observaciones para el Demo Day

Algunos detectores van a reportar "queries lentas" sin diagnosticar el
anti-pattern específico. Criterios para evaluar:

- **Detección completa (1 pt):** identifica la query Y diagnostica el
  anti-pattern Y propone una recomendación específica.
- **Detección parcial (0.5 pts):** identifica la query pero solo dice
  "es lenta" o "considera optimizar".
- **No detectada (0 pts):** la query no aparece en el reporte del producto.

Si el producto reporta una query como problemática que en realidad no
lo es (ej: una query con `Index Scan` rápido y bajo costo), cuenta como
**falso positivo (-0.5 pt, tope -3)**.

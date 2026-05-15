-- =====================================================================
-- AppDB v2 — PLANTACIÓN DE QUERIES PROBLEMÁTICAS
-- =====================================================================
-- Planta 24 queries problemáticas para el proyecto PgPilot. Cada una
-- exhibe un anti-pattern específico que el producto debe detectar a
-- partir de pg_stat_statements + análisis de EXPLAIN.
--
-- Cada query se ejecuta varias veces con literales distintos para que:
--   1. Registre en pg_stat_statements con calls > 5
--   2. El detector pueda normalizarla (literales -> $1, $2, ...)
--
-- Q01-Q20 corresponden a los mismos anti-patterns de la v1 (disfrazados).
-- Q21-Q24 son NUEVOS, no anunciados.
--
-- NO repartir este archivo a los alumnos. La lista maestra está en el
-- documento Word "AppDB_v2_Lista_Maestra_Hallazgos.docx".
-- =====================================================================

\set ON_ERROR_STOP on

-- Reiniciar stats para un snapshot limpio
SELECT pg_stat_statements_reset();

-- =====================================================================
-- Q01 — Sequential scan en tabla grande por columna sin índice
-- hilos.autor_id no tiene índice -> Seq Scan de 500K filas
-- =====================================================================
SELECT * FROM hilos WHERE autor_id = 12345;
SELECT * FROM hilos WHERE autor_id = 100;
SELECT * FROM hilos WHERE autor_id = 49000;
SELECT * FROM hilos WHERE autor_id = 7;
SELECT * FROM hilos WHERE autor_id = 33333;
SELECT * FROM hilos WHERE autor_id = 21000;

-- =====================================================================
-- Q02 — OR sobre dos columnas distintas (debería ser UNION)
-- El planner no puede usar índices para un OR de dos columnas
-- =====================================================================
SELECT id FROM hilos WHERE autor_id = 100 OR citado_id = 100;
SELECT id FROM hilos WHERE autor_id = 5000 OR citado_id = 5000;
SELECT id FROM hilos WHERE autor_id = 999 OR citado_id = 999;
SELECT id FROM hilos WHERE autor_id = 42 OR citado_id = 42;
SELECT id FROM hilos WHERE autor_id = 8800 OR citado_id = 8800;
SELECT id FROM hilos WHERE autor_id = 30000 OR citado_id = 30000;

-- =====================================================================
-- Q03 — LIKE con comodín al inicio (nunca usa índice B-tree)
-- =====================================================================
SELECT id FROM hilos WHERE cuerpo LIKE '%bitcoin%';
SELECT id FROM hilos WHERE cuerpo LIKE '%relleno%';
SELECT id FROM hilos WHERE cuerpo LIKE '%comunidad%';
SELECT id FROM hilos WHERE cuerpo LIKE '%especial%';
SELECT id FROM hilos WHERE cuerpo LIKE '%contenido%';

-- =====================================================================
-- Q04 — Función no-immutable sobre columna en WHERE
-- EXTRACT(YEAR FROM creado) impide usar el índice idx_hilos_creado.
-- Debería ser: creado >= '2024-01-01' AND creado < '2025-01-01'
-- =====================================================================
SELECT * FROM hilos WHERE EXTRACT(YEAR FROM creado) = 2024;
SELECT * FROM hilos WHERE EXTRACT(YEAR FROM creado) = 2023;
SELECT * FROM hilos WHERE EXTRACT(YEAR FROM creado) = 2025;
SELECT * FROM hilos WHERE EXTRACT(MONTH FROM creado) = 6;
SELECT * FROM hilos WHERE EXTRACT(YEAR FROM creado) = 2024;

-- =====================================================================
-- Q05 — GROUP BY + ORDER BY que hace sort en disco (work_mem bajo)
-- Con work_mem = 1MB esta agregación derrama a disco
-- =====================================================================
SELECT miembro_id, count(*) FROM votos GROUP BY miembro_id ORDER BY 2 DESC;
SELECT miembro_id, count(*) FROM votos GROUP BY miembro_id ORDER BY count(*) DESC;
SELECT miembro_id, sum(valor) FROM votos GROUP BY miembro_id ORDER BY 2 DESC;
SELECT miembro_id, count(*) FROM votos GROUP BY miembro_id ORDER BY 2 DESC;

-- =====================================================================
-- Q06 — JOIN con sintaxis de coma (estilo viejo) sobre tablas grandes
-- =====================================================================
SELECT h.id, r.contenido FROM hilos h, respuestas r
  WHERE h.id = r.hilo_id AND h.autor_id BETWEEN 1 AND 1000;
SELECT h.id, r.contenido FROM hilos h, respuestas r
  WHERE h.id = r.hilo_id AND h.autor_id BETWEEN 2000 AND 3000;
SELECT h.id, r.contenido FROM hilos h, respuestas r
  WHERE h.id = r.hilo_id AND h.autor_id BETWEEN 5000 AND 6000;
SELECT h.id, r.contenido FROM hilos h, respuestas r
  WHERE h.id = r.hilo_id AND h.autor_id BETWEEN 100 AND 500;

-- =====================================================================
-- Q07 — SELECT * cuando solo se usan pocas columnas
-- =====================================================================
SELECT * FROM hilos WHERE creado > NOW() - INTERVAL '7 days';
SELECT * FROM hilos WHERE creado > NOW() - INTERVAL '30 days';
SELECT * FROM hilos WHERE creado > NOW() - INTERVAL '1 day';
SELECT * FROM hilos WHERE creado > NOW() - INTERVAL '14 days';

-- =====================================================================
-- Q08 — Falta de índice cubriente (oportunidad de index-only scan)
-- SELECT id, creado WHERE autor_id ... ORDER BY creado
-- Un índice (autor_id, creado) permitiría index-only scan
-- =====================================================================
SELECT id, creado FROM hilos WHERE autor_id = 5000 ORDER BY creado DESC LIMIT 20;
SELECT id, creado FROM hilos WHERE autor_id = 12000 ORDER BY creado DESC LIMIT 20;
SELECT id, creado FROM hilos WHERE autor_id = 800 ORDER BY creado DESC LIMIT 20;
SELECT id, creado FROM hilos WHERE autor_id = 44000 ORDER BY creado DESC LIMIT 20;

-- =====================================================================
-- Q09 — Subquery correlacionada que debería ser JOIN
-- =====================================================================
SELECT h.id, (SELECT count(*) FROM respuestas r WHERE r.hilo_id = h.id) AS num_resp
  FROM hilos h WHERE h.autor_id BETWEEN 1 AND 200;
SELECT h.id, (SELECT count(*) FROM respuestas r WHERE r.hilo_id = h.id) AS num_resp
  FROM hilos h WHERE h.autor_id BETWEEN 1000 AND 1200;
SELECT h.id, (SELECT count(*) FROM respuestas r WHERE r.hilo_id = h.id) AS num_resp
  FROM hilos h WHERE h.autor_id BETWEEN 3000 AND 3200;

-- =====================================================================
-- Q10 — Query afectada por estadísticas desactualizadas
-- Se insertan filas nuevas en una tabla y NO se hace ANALYZE; el planner
-- estima mal la cantidad de filas.
-- =====================================================================
CREATE TABLE hilos_recientes (
    id BIGSERIAL PRIMARY KEY,
    autor_id INTEGER,
    titulo TEXT,
    creado TIMESTAMP DEFAULT NOW()
);
-- Desactivar autovacuum para que las estadisticas NO se actualicen solas:
-- es justamente el anti-pattern que queremos que persista hasta el Demo Day.
ALTER TABLE hilos_recientes SET (autovacuum_enabled = false);
-- pocas filas conocidas por el planner (0, porque nunca se analiza)
INSERT INTO hilos_recientes (autor_id, titulo)
SELECT 1 + (g % 50000), 'Hilo reciente ' || g
FROM generate_series(1, 60000) g;
-- (intencionalmente SIN ANALYZE -> reltuples se queda en 0)
SELECT * FROM hilos_recientes WHERE autor_id = 100;
SELECT * FROM hilos_recientes WHERE autor_id = 5000;
SELECT count(*) FROM hilos_recientes WHERE autor_id BETWEEN 1 AND 1000;
SELECT count(*) FROM hilos_recientes WHERE autor_id BETWEEN 1 AND 5000;

-- =====================================================================
-- Q11 — Falta índice parcial para filtro selectivo
-- avisos.leido = false es ~5% de las filas; un índice parcial
-- sobre (miembro_id) WHERE leido = false sería ideal y no existe
-- =====================================================================
SELECT * FROM avisos WHERE miembro_id = 100 AND leido = false;
SELECT * FROM avisos WHERE miembro_id = 5000 AND leido = false;
SELECT * FROM avisos WHERE miembro_id = 30000 AND leido = false;
SELECT * FROM avisos WHERE miembro_id = 999 AND leido = false;
SELECT count(*) FROM avisos WHERE leido = false;

-- =====================================================================
-- Q12 — DISTINCT usado para "arreglar" un JOIN que duplica filas
-- El DISTINCT esconde el problema real: el JOIN multiplica filas
-- =====================================================================
SELECT DISTINCT h.id, h.titulo
  FROM hilos h JOIN hilo_etiquetas he ON he.hilo_id = h.id
  WHERE h.autor_id BETWEEN 1 AND 500;
SELECT DISTINCT h.id, h.titulo
  FROM hilos h JOIN hilo_etiquetas he ON he.hilo_id = h.id
  WHERE h.autor_id BETWEEN 2000 AND 2500;
SELECT DISTINCT h.id, h.titulo
  FROM hilos h JOIN hilo_etiquetas he ON he.hilo_id = h.id
  WHERE h.autor_id BETWEEN 8000 AND 8500;

-- =====================================================================
-- Q13 — OFFSET grande para paginación (escanea y descarta miles de filas)
-- =====================================================================
SELECT * FROM respuestas ORDER BY id LIMIT 20 OFFSET 500000;
SELECT * FROM respuestas ORDER BY id LIMIT 20 OFFSET 700000;
SELECT * FROM respuestas ORDER BY id LIMIT 20 OFFSET 900000;
SELECT * FROM respuestas ORDER BY id LIMIT 20 OFFSET 300000;

-- =====================================================================
-- Q14 — Cast implícito por mismatch de tipo que invalida el índice
-- correo es VARCHAR; comparar contra un número fuerza cast y descarta índice
-- (se usa una expresión que provoca el cast)
-- =====================================================================
SELECT * FROM miembros WHERE correo = 'miembro100@foro.mx';
SELECT id FROM miembros WHERE correo::text = 'miembro5000@foro.mx';
SELECT id FROM miembros WHERE upper(correo) = 'MIEMBRO999@FORO.MX';
SELECT id FROM miembros WHERE upper(correo) = 'MIEMBRO42@FORO.MX';
SELECT id FROM miembros WHERE upper(correo) = 'MIEMBRO7@FORO.MX';

-- =====================================================================
-- Q15 — NOT IN con subquery que puede contener NULL (bug silencioso + lento)
-- Si la subquery devuelve algún NULL, el resultado es vacío. Debería ser NOT EXISTS.
-- =====================================================================
SELECT id FROM miembros WHERE id NOT IN (SELECT autor_id FROM hilos);
SELECT id FROM miembros WHERE id NOT IN (SELECT autor_id FROM hilos WHERE eliminado = false);
SELECT id FROM miembros WHERE id NOT IN (SELECT citado_id FROM hilos);

-- =====================================================================
-- Q16 — COUNT(*) sobre tabla enorme (chequeo de visibilidad fila por fila)
-- Para un conteo aproximado debería usarse pg_class.reltuples
-- =====================================================================
SELECT count(*) FROM hilos;
SELECT count(*) FROM respuestas;
SELECT count(*) FROM votos;
SELECT count(*) FROM avisos;

-- =====================================================================
-- Q17 — ORDER BY con función sobre columna (impide usar índice ordenado)
-- =====================================================================
SELECT id, creado FROM hilos ORDER BY date_trunc('day', creado) DESC LIMIT 50;
SELECT id, creado FROM hilos ORDER BY date_trunc('day', creado) DESC LIMIT 100;
SELECT id, creado FROM hilos ORDER BY date_trunc('month', creado) DESC LIMIT 50;

-- =====================================================================
-- Q18 — ORDER BY ... LIMIT sobre columna sin índice
-- respuestas.creado no tiene índice -> Seq Scan + Sort de 1M filas
-- =====================================================================
SELECT * FROM respuestas ORDER BY creado DESC LIMIT 50;
SELECT * FROM respuestas ORDER BY creado DESC LIMIT 100;
SELECT id, contenido FROM respuestas ORDER BY creado DESC LIMIT 20;
SELECT id, contenido FROM respuestas ORDER BY creado DESC LIMIT 200;

-- =====================================================================
-- Q19 — JOIN sin condición suficiente que produce resultado gigante
-- (cross join accidental acotado por LIMIT, sigue siendo costoso)
-- =====================================================================
SELECT h.id, m.alias FROM hilos h JOIN miembros m ON true
  WHERE h.autor_id = 100 LIMIT 100;
SELECT h.id, m.alias FROM hilos h JOIN miembros m ON true
  WHERE h.autor_id = 5000 LIMIT 100;
SELECT h.id, m.alias FROM hilos h JOIN miembros m ON true
  WHERE h.autor_id = 999 LIMIT 100;

-- =====================================================================
-- Q20 — IN con lista enorme de literales (debería ser JOIN o tabla temporal)
-- =====================================================================
SELECT * FROM miembros WHERE id IN (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,
  21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50);
SELECT * FROM miembros WHERE id IN (100,101,102,103,104,105,106,107,108,109,110,111,112,
  113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130);
SELECT * FROM miembros WHERE id IN (500,501,502,503,504,505,506,507,508,509,510);

-- =====================================================================
-- Q21 — NUEVO — UNION en lugar de UNION ALL (deduplica innecesariamente)
-- Cuando los conjuntos no se solapan, UNION fuerza un sort/hash de
-- deduplicación que no aporta nada. Debería ser UNION ALL.
-- =====================================================================
SELECT id FROM hilos WHERE autor_id = 100
  UNION
  SELECT id FROM hilos WHERE autor_id = 200;
SELECT id FROM hilos WHERE autor_id = 1000
  UNION
  SELECT id FROM hilos WHERE autor_id = 2000;
SELECT id FROM hilos WHERE autor_id = 5
  UNION
  SELECT id FROM hilos WHERE autor_id = 6;
SELECT id FROM hilos WHERE autor_id = 9000
  UNION
  SELECT id FROM hilos WHERE autor_id = 9001;

-- =====================================================================
-- Q22 — NUEVO — Predicado no-sargable: aritmética sobre la columna
-- "WHERE columna + 0 = valor" o "WHERE columna * 1 ..." impide el índice.
-- Aquí: WHERE autor_id + 0 = valor
-- =====================================================================
SELECT * FROM respuestas WHERE autor_id + 0 = 100;
SELECT * FROM respuestas WHERE autor_id + 0 = 5000;
SELECT * FROM respuestas WHERE autor_id + 0 = 999;
SELECT * FROM respuestas WHERE autor_id + 0 = 33000;

-- =====================================================================
-- Q23 — NUEVO — CTE que se materializa cuando debería ser inline
-- En Postgres una CTE simple a veces conviene que sea inline; forzar
-- MATERIALIZED bloquea que el planner empuje los filtros adentro.
-- =====================================================================
WITH hilos_cte AS MATERIALIZED (SELECT * FROM hilos)
SELECT * FROM hilos_cte WHERE autor_id = 100;
WITH hilos_cte AS MATERIALIZED (SELECT * FROM hilos)
SELECT * FROM hilos_cte WHERE autor_id = 5000;
WITH hilos_cte AS MATERIALIZED (SELECT * FROM hilos)
SELECT * FROM hilos_cte WHERE autor_id = 999;

-- =====================================================================
-- Q24 — NUEVO — DELETE/UPDATE sin filtro indexado (full scan de escritura)
-- Un UPDATE que filtra por una columna sin índice escanea toda la tabla.
-- Se ejecuta como SELECT equivalente para no mutar datos, pero el
-- anti-pattern se documenta: el detector debe verlo en pg_stat_statements.
-- =====================================================================
SELECT count(*) FROM respuestas WHERE autor_id = 100;   -- representa el WHERE del UPDATE
SELECT count(*) FROM respuestas WHERE autor_id = 5000;
SELECT count(*) FROM respuestas WHERE autor_id = 999;
SELECT count(*) FROM respuestas WHERE autor_id = 12000;
-- Nota: respuestas.autor_id SÍ tiene índice, pero el UPDATE real plantado
-- como anti-pattern es sobre 'eliminado', columna sin índice:
SELECT count(*) FROM respuestas WHERE eliminado = true;
SELECT count(*) FROM respuestas WHERE eliminado = false;

-- =====================================================================
-- Cierre
-- =====================================================================
\echo '====================================================='
\echo 'AppDB v2 lista. 24 queries problematicas plantadas.'
\echo 'Q01-Q20: anti-patterns de la v1 (disfrazados).'
\echo 'Q21-Q24: anti-patterns NUEVOS no anunciados.'
\echo 'Revisar pg_stat_statements para las queries a detectar.'
\echo 'Lista maestra: ver documento Word adjunto.'
\echo '====================================================='

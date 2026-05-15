-- =====================================================================
-- AppDB v2 — BD DEMO SORPRESA para PgPilot (Demo Day)
-- Universidad Anáhuac Querétaro — Proyecto Final BD Avanzadas
-- =====================================================================
-- Versión 2 ("sorpresa"): mismos tipos de anti-pattern que la v1, pero
-- con OTRO dominio (un foro/comunidad tipo Reddit en lugar de una red
-- social tipo Twitter), OTROS nombres de tabla, OTROS datos, y varios
-- anti-patterns NUEVOS no anunciados.
--
-- v1 usaba: users, posts, comments, likes, follows, notifications,
--           tags, post_tags
-- v2 usa:   miembros, hilos, respuestas, votos, suscripciones,
--           avisos, etiquetas, hilo_etiquetas
--
-- Modo base (~700 MB, ~5M filas, levanta en 3-5 min).
-- =====================================================================

\set ON_ERROR_STOP on
\timing on

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- ---------------------------------------------------------------------
-- SCHEMA
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS avisos CASCADE;
DROP TABLE IF EXISTS hilo_etiquetas CASCADE;
DROP TABLE IF EXISTS etiquetas CASCADE;
DROP TABLE IF EXISTS votos CASCADE;
DROP TABLE IF EXISTS respuestas CASCADE;
DROP TABLE IF EXISTS suscripciones CASCADE;
DROP TABLE IF EXISTS hilos CASCADE;
DROP TABLE IF EXISTS miembros CASCADE;

-- miembros — usuarios del foro
CREATE TABLE miembros (
    id              SERIAL PRIMARY KEY,
    alias           VARCHAR(50) UNIQUE NOT NULL,
    correo          VARCHAR(200) UNIQUE NOT NULL,
    nombre          VARCHAR(200),
    semblanza       TEXT,
    avatar_url      VARCHAR(500),
    ultimo_acceso   TIMESTAMP,
    verificado      BOOLEAN DEFAULT FALSE,
    activo          BOOLEAN DEFAULT TRUE,
    creado          TIMESTAMP DEFAULT NOW()
);

-- hilos — publicaciones / temas del foro (la tabla mas grande)
-- autor_id: Q01 SIN INDICE (plantado)
-- citado_id: usado por Q02 (OR vs UNION)
CREATE TABLE hilos (
    id              BIGSERIAL PRIMARY KEY,
    autor_id        INTEGER NOT NULL,
    titulo          VARCHAR(300),
    cuerpo          TEXT,
    citado_id       INTEGER,
    creado          TIMESTAMP DEFAULT NOW(),
    eliminado       BOOLEAN DEFAULT FALSE
);

-- respuestas — respuestas a hilos
-- creado: Q18 SIN INDICE (plantado)
CREATE TABLE respuestas (
    id              BIGSERIAL PRIMARY KEY,
    hilo_id         BIGINT NOT NULL,
    autor_id        INTEGER NOT NULL,
    contenido       TEXT,
    creado          TIMESTAMP DEFAULT NOW(),
    eliminado       BOOLEAN DEFAULT FALSE
);

-- votos — votos a hilos
CREATE TABLE votos (
    id              BIGSERIAL PRIMARY KEY,
    miembro_id      INTEGER NOT NULL,
    hilo_id         BIGINT NOT NULL,
    valor           SMALLINT DEFAULT 1,
    creado          TIMESTAMP DEFAULT NOW()
);

-- suscripciones — relacion seguidor (autoreferencial miembros-miembros)
CREATE TABLE suscripciones (
    id              BIGSERIAL PRIMARY KEY,
    seguidor_id     INTEGER NOT NULL,
    seguido_id      INTEGER NOT NULL,
    creado          TIMESTAMP DEFAULT NOW()
);

-- avisos — notificaciones
-- Q11: SIN indice parcial sobre (miembro_id) WHERE leido = false (plantado)
CREATE TABLE avisos (
    id              BIGSERIAL PRIMARY KEY,
    miembro_id      INTEGER NOT NULL,
    tipo            VARCHAR(40),
    cuerpo          TEXT,
    leido           BOOLEAN DEFAULT FALSE,
    creado          TIMESTAMP DEFAULT NOW()
);

-- etiquetas — hashtags / temas
CREATE TABLE etiquetas (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(80) NOT NULL,
    usos            INTEGER DEFAULT 0
);

-- hilo_etiquetas — relacion N:M
CREATE TABLE hilo_etiquetas (
    hilo_id         BIGINT NOT NULL,
    etiqueta_id     INTEGER NOT NULL,
    PRIMARY KEY (hilo_id, etiqueta_id)
);

-- ---------------------------------------------------------------------
-- SEED DE DATOS — modo base (~5M filas)
-- ---------------------------------------------------------------------

-- miembros (50K)
INSERT INTO miembros (alias, correo, nombre, semblanza, ultimo_acceso, verificado, activo, creado)
SELECT 'miembro_' || g,
       'miembro' || g || '@foro.mx',
       'Miembro Numero ' || g,
       'Semblanza del miembro ' || g || '. Texto de relleno para dar volumen a la columna.',
       NOW() - ((g % 400) || ' days')::interval,
       (g % 20 = 0),
       (g % 50 <> 0),
       NOW() - ((g % 1000) || ' days')::interval
FROM generate_series(1, 50000) g;

-- etiquetas (1K)
INSERT INTO etiquetas (nombre, usos)
SELECT 'etiqueta-' || g, (g * 37) % 9000
FROM generate_series(1, 1000) g;

-- hilos (500K)
INSERT INTO hilos (autor_id, titulo, cuerpo, citado_id, creado, eliminado)
SELECT 1 + (g % 50000),
       'Hilo numero ' || g || ' sobre un tema de la comunidad',
       'Cuerpo del hilo ' || g || '. ' || repeat('Contenido de relleno para que la columna tenga peso real. ', 3) ||
         CASE WHEN g % 1000 = 0 THEN 'mencion especial bitcoin' ELSE '' END,
       CASE WHEN g % 7 = 0 THEN 1 + (g % 50000) ELSE NULL END,
       NOW() - ((g % 900) || ' days')::interval - ((g % 86400) || ' seconds')::interval,
       (g % 100 = 0)
FROM generate_series(1, 500000) g;

-- respuestas (1M)
INSERT INTO respuestas (hilo_id, autor_id, contenido, creado, eliminado)
SELECT 1 + (g % 500000),
       1 + (g % 50000),
       'Respuesta ' || g || '. Texto de relleno representando una respuesta real del foro.',
       NOW() - ((g % 800) || ' days')::interval - ((g % 86400) || ' seconds')::interval,
       (g % 200 = 0)
FROM generate_series(1, 1000000) g;

-- votos (2M)
INSERT INTO votos (miembro_id, hilo_id, valor, creado)
SELECT 1 + (g % 50000),
       1 + (g % 500000),
       CASE WHEN g % 5 = 0 THEN -1 ELSE 1 END,
       NOW() - ((g % 700) || ' days')::interval
FROM generate_series(1, 2000000) g;

-- suscripciones (300K)
INSERT INTO suscripciones (seguidor_id, seguido_id, creado)
SELECT 1 + (g % 50000),
       1 + ((g * 13) % 50000),
       NOW() - ((g % 600) || ' days')::interval
FROM generate_series(1, 300000) g;

-- avisos (800K)
INSERT INTO avisos (miembro_id, tipo, cuerpo, leido, creado)
SELECT 1 + (g % 50000),
       (ARRAY['respuesta','voto','mencion','suscripcion','sistema'])[1 + g % 5],
       'Aviso ' || g || ' generado por actividad en el foro.',
       (g % 20 <> 0),   -- ~95% leido=true, ~5% leido=false (Q11)
       NOW() - ((g % 500) || ' days')::interval
FROM generate_series(1, 800000) g;

-- hilo_etiquetas (1.5M)
INSERT INTO hilo_etiquetas (hilo_id, etiqueta_id)
SELECT h, e
FROM (
  SELECT 1 + (g % 500000) AS h,
         1 + ((g * 7) % 1000) AS e
  FROM generate_series(1, 1500000) g
) src
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------
-- INDICES
-- Algunos criticos estan INTENCIONALMENTE AUSENTES (problemas plantados).
-- ---------------------------------------------------------------------

-- miembros
CREATE INDEX idx_miembros_correo ON miembros (correo);
CREATE INDEX idx_miembros_ultimo_acceso ON miembros (ultimo_acceso);

-- hilos
-- Q01: SIN indice en hilos.autor_id (plantado)
-- Q08: SIN indice cubriente para (autor_id, creado) ORDER BY (plantado)
CREATE INDEX idx_hilos_creado ON hilos (creado);
CREATE INDEX idx_hilos_citado_id ON hilos (citado_id);

-- respuestas
CREATE INDEX idx_respuestas_hilo_id ON respuestas (hilo_id);
CREATE INDEX idx_respuestas_autor_id ON respuestas (autor_id);
-- Q18: SIN indice en respuestas.creado (plantado)

-- votos
CREATE INDEX idx_votos_miembro_id ON votos (miembro_id);
CREATE INDEX idx_votos_hilo_id ON votos (hilo_id);

-- suscripciones
CREATE INDEX idx_suscripciones_seguidor ON suscripciones (seguidor_id);
CREATE INDEX idx_suscripciones_seguido ON suscripciones (seguido_id);

-- avisos
CREATE INDEX idx_avisos_miembro_id ON avisos (miembro_id);
-- Q11: SIN indice parcial sobre (miembro_id) WHERE leido = false (plantado)

-- etiquetas
CREATE INDEX idx_etiquetas_nombre ON etiquetas (nombre);
CREATE INDEX idx_etiquetas_usos ON etiquetas (usos);

-- hilo_etiquetas
CREATE INDEX idx_hilo_etiquetas_etiqueta ON hilo_etiquetas (etiqueta_id);

COMMENT ON TABLE miembros IS 'Usuarios registrados del foro';
COMMENT ON TABLE hilos IS 'Hilos / temas publicados (contenido principal)';
COMMENT ON TABLE respuestas IS 'Respuestas a los hilos';
COMMENT ON TABLE votos IS 'Votos a favor o en contra de hilos';
COMMENT ON TABLE suscripciones IS 'Relaciones de suscripcion entre miembros';
COMMENT ON TABLE avisos IS 'Notificaciones de actividad';
COMMENT ON TABLE etiquetas IS 'Etiquetas / temas de los hilos';
COMMENT ON TABLE hilo_etiquetas IS 'Relacion N:M hilos-etiquetas';

ANALYZE;

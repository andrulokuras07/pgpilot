-- =====================================================================
-- AppDB v1.0 — Planted Problematic Queries
-- =====================================================================
-- This script plants 20 problematic queries for the PgPilot project.
-- Each query exhibits a specific anti-pattern that the product should
-- detect from pg_stat_statements + EXPLAIN analysis.
--
-- Each query is run multiple times with varying literals so that:
--   1. It registers in pg_stat_statements with calls > 5
--   2. The detector can normalize it (literals become $1, $2, ...)
--
-- DO NOT share this file with students. Master list in
-- /docs/HALLAZGOS_v1.md (instructor only).
-- =====================================================================

SET client_min_messages = WARNING;

-- Reset stats to get clean data
SELECT pg_stat_statements_reset();

-- =====================================================================
-- Q01: Sequential scan on posts (missing index on author_id)
-- The schema intentionally has NO index on posts.author_id.
-- This forces seq scan over 500K rows for any author lookup.
-- =====================================================================
SELECT * FROM posts WHERE author_id = 100;
SELECT * FROM posts WHERE author_id = 250;
SELECT * FROM posts WHERE author_id = 500;
SELECT * FROM posts WHERE author_id = 1000;
SELECT * FROM posts WHERE author_id = 2500;
SELECT * FROM posts WHERE author_id = 5000;
SELECT * FROM posts WHERE author_id = 10000;
SELECT * FROM posts WHERE author_id = 25000;
SELECT * FROM posts WHERE author_id = 40000;
SELECT * FROM posts WHERE author_id = 49000;

-- =====================================================================
-- Q02: OR across two columns where UNION would be faster
-- "Show me all posts where I'm author OR I'm mentioned"
-- Postgres can't use both indexes simultaneously with OR; UNION can.
-- =====================================================================
SELECT id FROM posts WHERE author_id = 100 OR mentioned_user_id = 100;
SELECT id FROM posts WHERE author_id = 500 OR mentioned_user_id = 500;
SELECT id FROM posts WHERE author_id = 1000 OR mentioned_user_id = 1000;
SELECT id FROM posts WHERE author_id = 5000 OR mentioned_user_id = 5000;
SELECT id FROM posts WHERE author_id = 10000 OR mentioned_user_id = 10000;
SELECT id FROM posts WHERE author_id = 25000 OR mentioned_user_id = 25000;

-- =====================================================================
-- Q03: LIKE with leading wildcard (cannot use index)
-- =====================================================================
SELECT id FROM posts WHERE content LIKE '%bitcoin%';
SELECT id FROM posts WHERE content LIKE '%premium%';
SELECT id FROM posts WHERE content LIKE '%special%';
SELECT id FROM posts WHERE content LIKE '%distributed%';
SELECT id FROM posts WHERE content LIKE '%coffee%';
SELECT id FROM posts WHERE content LIKE '%productivity%';
SELECT id FROM posts WHERE content LIKE '%anomalies%';

-- =====================================================================
-- Q04: Non-immutable function in WHERE clause
-- EXTRACT(YEAR FROM created_at) prevents index use on created_at.
-- Should be: created_at >= '2024-01-01' AND created_at < '2025-01-01'
-- =====================================================================
SELECT count(*) FROM posts WHERE EXTRACT(YEAR FROM created_at) = 2024;
SELECT count(*) FROM posts WHERE EXTRACT(YEAR FROM created_at) = 2025;
SELECT count(*) FROM posts WHERE EXTRACT(MONTH FROM created_at) = 6;
SELECT count(*) FROM posts WHERE EXTRACT(MONTH FROM created_at) = 12;
SELECT count(*) FROM posts WHERE EXTRACT(YEAR FROM created_at) = 2023;
SELECT count(*) FROM posts WHERE EXTRACT(YEAR FROM created_at) = 2026;

-- =====================================================================
-- Q05: Sort spill to disk (work_mem too low for full GROUP BY + JOIN)
-- We aggregate likes joined with users — forces hash to overflow.
-- =====================================================================
SET work_mem = '1MB';

SELECT u.username, count(l.id) AS like_count
FROM users u
JOIN likes l ON l.user_id = u.id
GROUP BY u.username
ORDER BY like_count DESC;

SELECT u.full_name, count(l.id) AS like_count
FROM users u
JOIN likes l ON l.user_id = u.id
GROUP BY u.full_name
ORDER BY like_count DESC;

SELECT user_id, post_id, count(*) FROM likes GROUP BY user_id, post_id ORDER BY 1, 2;

RESET work_mem;

-- =====================================================================
-- Q06: Nested loop where hash join would be faster
-- Implicit JOIN syntax with range condition triggers nested loop heuristic.
-- =====================================================================
SELECT p.id, c.content FROM posts p, comments c
  WHERE p.id = c.post_id AND p.author_id BETWEEN 1 AND 100;
SELECT p.id, c.content FROM posts p, comments c
  WHERE p.id = c.post_id AND p.author_id BETWEEN 100 AND 200;
SELECT p.id, c.content FROM posts p, comments c
  WHERE p.id = c.post_id AND p.author_id BETWEEN 1000 AND 1100;
SELECT p.id, c.content FROM posts p, comments c
  WHERE p.id = c.post_id AND p.author_id BETWEEN 5000 AND 5100;

-- =====================================================================
-- Q07: SELECT * when only few columns are needed
-- Forces full row fetch instead of index-only scan.
-- =====================================================================
SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '7 days';
SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '14 days';
SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '30 days';
SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '60 days';
SELECT * FROM posts WHERE created_at > NOW() - INTERVAL '90 days';

-- =====================================================================
-- Q08: Missing covering index for "user's recent posts" query
-- A covering index (author_id, created_at DESC) INCLUDE (id) would
-- enable index-only scan with no heap visits.
-- =====================================================================
SELECT id, created_at FROM posts WHERE author_id = 5000 ORDER BY created_at DESC LIMIT 20;
SELECT id, created_at FROM posts WHERE author_id = 100 ORDER BY created_at DESC LIMIT 20;
SELECT id, created_at FROM posts WHERE author_id = 25000 ORDER BY created_at DESC LIMIT 20;
SELECT id, created_at FROM posts WHERE author_id = 40000 ORDER BY created_at DESC LIMIT 20;
SELECT id, created_at FROM posts WHERE author_id = 1000 ORDER BY created_at DESC LIMIT 20;

-- =====================================================================
-- Q09: Correlated subquery that should be a JOIN
-- =====================================================================
SELECT id, (SELECT count(*) FROM comments WHERE post_id = posts.id)
  FROM posts WHERE author_id = 1000 LIMIT 50;
SELECT id, (SELECT count(*) FROM comments WHERE post_id = posts.id)
  FROM posts WHERE author_id = 5000 LIMIT 50;
SELECT id, (SELECT count(*) FROM comments WHERE post_id = posts.id)
  FROM posts WHERE author_id = 10000 LIMIT 50;
SELECT id, (SELECT count(*) FROM comments WHERE post_id = posts.id)
  FROM posts WHERE author_id = 25000 LIMIT 50;

-- =====================================================================
-- Q10: Stale stats — bulk insert without ANALYZE
-- We disable autovacuum on tags temporarily, insert, and DON'T analyze.
-- pg_class.reltuples will say ~1000 while actual count is ~6000.
-- Detector should flag the mismatch via EXPLAIN's estimated vs actual rows.
-- =====================================================================
ALTER TABLE tags SET (autovacuum_enabled = false);

INSERT INTO tags (name, use_count, created_at)
SELECT
    'newtag_' || i,
    (random() * 100)::int,
    NOW()
FROM generate_series(1, 5000) i;
-- INTENTIONALLY no ANALYZE here

SELECT count(*) FROM tags WHERE use_count > 100;
SELECT count(*) FROM tags WHERE use_count > 500;
SELECT count(*) FROM tags WHERE use_count > 1000;
SELECT count(*) FROM tags WHERE use_count > 50;

-- =====================================================================
-- Q11: Missing partial index on notifications
-- 95% of notifications have read=true, 5% read=false.
-- Most queries filter by user_id AND read=false (the unread ones).
-- A partial index ON (user_id) WHERE read=false would be tiny and fast.
-- =====================================================================
SELECT id FROM notifications WHERE user_id = 100 AND read = false;
SELECT id FROM notifications WHERE user_id = 500 AND read = false;
SELECT id FROM notifications WHERE user_id = 1000 AND read = false;
SELECT id FROM notifications WHERE user_id = 5000 AND read = false;
SELECT id FROM notifications WHERE user_id = 10000 AND read = false;
SELECT id FROM notifications WHERE user_id = 25000 AND read = false;
SELECT id FROM notifications WHERE user_id = 40000 AND read = false;

-- =====================================================================
-- Q12: Implicit cast that prevents index use
-- users.username is VARCHAR but compared against an integer literal.
-- Postgres adds an implicit cast that breaks index use.
-- =====================================================================
-- Note: this query may fail with a runtime error in newer Postgres.
-- We wrap in EXCEPTION-safe DO block to ensure it registers in stats.
DO $$
BEGIN
    BEGIN PERFORM * FROM users WHERE username = 12345::text; EXCEPTION WHEN OTHERS THEN NULL; END;
    BEGIN PERFORM * FROM users WHERE username = 100::text;   EXCEPTION WHEN OTHERS THEN NULL; END;
    BEGIN PERFORM * FROM users WHERE username = 5000::text;  EXCEPTION WHEN OTHERS THEN NULL; END;
END $$;

-- More portable variant of the antipattern: cast on the indexed column itself
SELECT * FROM users WHERE username::text = '12345';
SELECT * FROM users WHERE username::text = '100';
SELECT * FROM users WHERE username::text = '5000';
SELECT * FROM users WHERE username::text = '25000';

-- =====================================================================
-- Q13: Cardinality estimation error in JOIN
-- Multi-condition AND with correlated columns: planner assumes
-- independence and underestimates the join.
-- =====================================================================
SELECT p.id, u.username
FROM posts p
JOIN users u ON u.id = p.author_id
WHERE u.is_verified = true AND u.is_active = true AND p.is_deleted = false;

SELECT p.id, u.username
FROM posts p
JOIN users u ON u.id = p.author_id
WHERE u.is_verified = false AND u.is_active = true AND p.is_deleted = false;

SELECT p.id, u.username
FROM posts p
JOIN users u ON u.id = p.author_id
WHERE u.is_verified = true AND u.is_active = false AND p.is_deleted = true;

-- =====================================================================
-- Q14: CTE forced materialization when inline would be better (Postgres 12+)
-- Using WITH ... AS MATERIALIZED prevents predicate push-down.
-- =====================================================================
WITH active_users AS MATERIALIZED (
    SELECT id FROM users WHERE last_login > NOW() - INTERVAL '30 days'
)
SELECT count(*) FROM active_users JOIN posts ON posts.author_id = active_users.id;

WITH active_users AS MATERIALIZED (
    SELECT id FROM users WHERE last_login > NOW() - INTERVAL '7 days'
)
SELECT count(*) FROM active_users JOIN posts ON posts.author_id = active_users.id;

WITH active_users AS MATERIALIZED (
    SELECT id FROM users WHERE last_login > NOW() - INTERVAL '60 days'
)
SELECT count(*) FROM active_users JOIN posts ON posts.author_id = active_users.id;

-- =====================================================================
-- Q15: Index scan disguised as effective but with high filter ratio
-- Uses an index that returns many rows then filters most via Recheck.
-- =====================================================================
SELECT id FROM posts WHERE created_at > NOW() - INTERVAL '2 years' AND likes_count > 950;
SELECT id FROM posts WHERE created_at > NOW() - INTERVAL '2 years' AND likes_count > 980;
SELECT id FROM posts WHERE created_at > NOW() - INTERVAL '2 years' AND likes_count > 990;
SELECT id FROM posts WHERE created_at > NOW() - INTERVAL '2 years' AND likes_count > 995;

-- =====================================================================
-- Q16: HAVING that should be WHERE
-- Filtering on grouping column post-aggregation; should pre-filter.
-- =====================================================================
SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 1000;
SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 5000;
SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 10000;
SELECT author_id, count(*) FROM posts GROUP BY author_id HAVING author_id = 25000;

-- =====================================================================
-- Q17: IN with subquery vs EXISTS
-- IN with a subquery returning many duplicates is slower than EXISTS.
-- =====================================================================
SELECT id FROM users WHERE id IN (
    SELECT author_id FROM posts WHERE created_at > NOW() - INTERVAL '1 day'
);
SELECT id FROM users WHERE id IN (
    SELECT author_id FROM posts WHERE created_at > NOW() - INTERVAL '7 days'
);
SELECT id FROM users WHERE id IN (
    SELECT author_id FROM posts WHERE created_at > NOW() - INTERVAL '30 days'
);

-- =====================================================================
-- Q18: ORDER BY with LIMIT but no supporting index
-- comments.created_at has NO index. Sorting all 1M comments to get top 50.
-- =====================================================================
SELECT * FROM comments ORDER BY created_at DESC LIMIT 50;
SELECT * FROM comments ORDER BY created_at DESC LIMIT 100;
SELECT id, content FROM comments ORDER BY created_at DESC LIMIT 20;
SELECT id, content FROM comments ORDER BY created_at DESC LIMIT 200;

-- =====================================================================
-- Q19: NOT IN with potentially NULL subquery — silent bug + slow
-- If any row in the subquery has NULL, the result is empty (NULL semantics).
-- Should be NOT EXISTS.
-- =====================================================================
SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts) LIMIT 10;
SELECT id FROM users WHERE id NOT IN (SELECT author_id FROM posts WHERE is_deleted = false) LIMIT 10;

-- =====================================================================
-- Q20: COUNT(*) on huge table — visibility check on every row
-- Classic anti-pattern; should use estimate from pg_stat_user_tables.
-- =====================================================================
SELECT count(*) FROM posts;
SELECT count(*) FROM comments;
SELECT count(*) FROM likes;
SELECT count(*) FROM notifications;

-- =====================================================================
-- Final summary
-- =====================================================================
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'AppDB v1.0 ready with 20 planted problematic queries';
    RAISE NOTICE 'Master list: /docs/HALLAZGOS_v1.md (instructor only)';
    RAISE NOTICE 'Check pg_stat_statements for the queries to detect';
    RAISE NOTICE '========================================';
END $$;

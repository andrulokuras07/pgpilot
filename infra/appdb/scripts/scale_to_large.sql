-- =====================================================================
-- AppDB — Scale to LARGE mode (OPTIONAL)
-- =====================================================================
-- Run this AFTER the base seed has completed if you want a more
-- realistic dataset (~10 GB, 15-30 minutes of seeding).
--
-- Usage:
--   docker exec -i appdb psql -U app_user -d appdb < scripts/scale_to_large.sql
--
-- Targets after scaling:
--   users          ~1M    (from 50K)
--   posts          ~10M   (from 500K)
--   comments       ~20M   (from 1M)
--   likes          ~20M   (from 1M)
--   follows        ~4M    (from 200K)
--   notifications  ~15M   (from 800K)
--   tags           ~5K    (from 6K, no change needed)
--   post_tags      ~30M   (from 1.5M)
-- =====================================================================

SET client_min_messages = WARNING;
SET work_mem = '128MB';
SET maintenance_work_mem = '512MB';

-- =====================================================================
-- Scale users: 50K -> 1M
-- =====================================================================
INSERT INTO users (username, email, full_name, bio, avatar_url, last_login, is_verified, is_active, created_at)
SELECT
    'user_l' || i,
    'user_l' || i || '@example.com',
    'Large User ' || i,
    'Bio for large user ' || i,
    'https://avatars.example.com/l' || i || '.jpg',
    NOW() - make_interval(days => (random() * 90)::int),
    CASE WHEN i % 100 = 0 THEN TRUE ELSE FALSE END,
    CASE WHEN i % 50 = 0 THEN FALSE ELSE TRUE END,
    NOW() - make_interval(days => (random() * 730)::int)
FROM generate_series(50001, 1000000) i;

-- =====================================================================
-- Scale posts: 500K -> 10M (in batches)
-- =====================================================================
DO $$
DECLARE
    batch INTEGER;
BEGIN
    FOR batch IN 1..19 LOOP
        INSERT INTO posts (author_id, content, mentioned_user_id, media_url, likes_count, comments_count, is_deleted, created_at)
        SELECT
            1 + (i % 1000000),
            'Post ' || i || ' content with various keywords like premium, special, distributed, coffee.',
            CASE WHEN i % 7 = 0 THEN 1 + ((i * 17) % 1000000) ELSE NULL END,
            CASE WHEN i % 3 = 0 THEN 'https://media.example.com/' || i || '.jpg' ELSE NULL END,
            (random() * 1000)::int,
            (random() * 200)::int,
            CASE WHEN i % 20 = 0 THEN TRUE ELSE FALSE END,
            NOW() - make_interval(days => (random() * 1095)::int)
        FROM generate_series(500001 + (batch - 1) * 500000, 500000 + batch * 500000) i;
        RAISE NOTICE 'posts batch % done', batch;
    END LOOP;
END $$;

-- =====================================================================
-- Scale comments: 1M -> 20M (in batches)
-- =====================================================================
DO $$
DECLARE
    batch INTEGER;
BEGIN
    FOR batch IN 1..19 LOOP
        INSERT INTO comments (post_id, author_id, content, likes_count, is_deleted, created_at)
        SELECT
            1 + (i % 10000000)::bigint,
            1 + (i % 1000000),
            'Large comment ' || i,
            (random() * 50)::int,
            CASE WHEN i % 20 = 0 THEN TRUE ELSE FALSE END,
            NOW() - make_interval(days => (random() * 730)::int)
        FROM generate_series(1000001 + (batch - 1) * 1000000, 1000000 + batch * 1000000) i;
        RAISE NOTICE 'comments batch % done', batch;
    END LOOP;
END $$;

-- =====================================================================
-- Scale likes: 1M -> 20M (each user likes 20 more posts at different stride)
-- =====================================================================
INSERT INTO likes (user_id, post_id, created_at)
SELECT
    u AS user_id,
    1 + ((u - 1 + (offset_idx - 1) * 11) % 10000000) AS post_id,
    NOW() - make_interval(days => (random() * 730)::int)
FROM generate_series(1, 1000000) u
CROSS JOIN generate_series(1, 19) offset_idx
ON CONFLICT (user_id, post_id) DO NOTHING;

-- =====================================================================
-- Scale follows: 200K -> 4M
-- =====================================================================
INSERT INTO follows (follower_id, followed_id, created_at)
SELECT
    u AS follower_id,
    1 + ((u + stride - 1) % 1000000) AS followed_id,
    NOW() - make_interval(days => (random() * 730)::int)
FROM generate_series(1, 1000000) u
CROSS JOIN unnest(ARRAY[7, 71, 1007, 10007]) stride
WHERE 1 + ((u + stride - 1) % 1000000) != u
ON CONFLICT (follower_id, followed_id) DO NOTHING;

-- =====================================================================
-- Scale notifications: 800K -> 15M
-- =====================================================================
DO $$
DECLARE
    batch INTEGER;
BEGIN
    FOR batch IN 1..15 LOOP
        INSERT INTO notifications (user_id, notification_type, payload, read, created_at)
        SELECT
            1 + (i % 1000000),
            (ARRAY['like', 'comment', 'follow', 'mention', 'reply'])[1 + (i % 5)],
            jsonb_build_object('source_user', 1 + ((i * 7) % 1000000), 'target_id', 1 + ((i * 13) % 10000000)),
            CASE WHEN i % 20 != 0 THEN TRUE ELSE FALSE END,
            NOW() - make_interval(days => (random() * 365)::int)
        FROM generate_series(800001 + (batch - 1) * 1000000, 800000 + batch * 1000000) i;
        RAISE NOTICE 'notifications batch % done', batch;
    END LOOP;
END $$;

-- =====================================================================
-- Scale post_tags: 1.5M -> 30M (6 tags per post avg)
-- =====================================================================
INSERT INTO post_tags (post_id, tag_id)
SELECT
    p AS post_id,
    1 + ((p + tag_stride - 1) % 6000) AS tag_id
FROM generate_series(1, 10000000) p
CROSS JOIN unnest(ARRAY[100, 1100, 2100]) tag_stride
ON CONFLICT (post_id, tag_id) DO NOTHING;

-- =====================================================================
-- Re-analyze (except tags to keep Q10 stale stats)
-- =====================================================================
ANALYZE users;
ANALYZE posts;
ANALYZE comments;
ANALYZE likes;
ANALYZE follows;
ANALYZE notifications;
ANALYZE post_tags;
-- NOTE: tags is INTENTIONALLY not analyzed for Q10

DO $$
BEGIN
    RAISE NOTICE 'AppDB scaled to LARGE mode. Planted queries still active.';
END $$;

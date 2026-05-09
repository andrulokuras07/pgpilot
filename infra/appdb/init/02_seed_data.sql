-- =====================================================================
-- AppDB v1.0 — Seed data (BASE mode)
-- ~500 MB, ~4M rows total
-- Tarda 3-4 minutos en sembrar.
-- For LARGE mode (~80M rows), see scripts/scale_to_large.sql
-- =====================================================================
-- Strategy: deterministic pair generation + ON CONFLICT DO NOTHING
-- as a safety net. We may end with slightly fewer rows than nominal,
-- which is fine — what matters is volume realism for EXPLAIN plans.
-- =====================================================================

SET client_min_messages = WARNING;
SET work_mem = '64MB';
SET maintenance_work_mem = '256MB';

-- =====================================================================
-- users: 50K
-- =====================================================================
INSERT INTO users (username, email, full_name, bio, avatar_url, last_login, is_verified, is_active, created_at)
SELECT
    'user' || i,
    'user' || i || '@example.com',
    (ARRAY['Alex', 'Maria', 'Juan', 'Sofia', 'Diego', 'Laura', 'Carlos', 'Ana', 'Luis', 'Elena'])[1 + (i % 10)] || ' ' ||
    (ARRAY['Garcia', 'Lopez', 'Martinez', 'Smith', 'Johnson', 'Brown', 'Silva', 'Costa', 'Rivera', 'Diaz'])[1 + ((i / 10) % 10)],
    'Bio for user ' || i || '. ' ||
    (ARRAY['Software developer.', 'Designer & artist.', 'Crypto enthusiast.', 'Travel lover.', 'Foodie & chef.'])[1 + (i % 5)],
    'https://avatars.example.com/' || i || '.jpg',
    NOW() - make_interval(days => (random() * 90)::int),
    CASE WHEN i % 100 = 0 THEN TRUE ELSE FALSE END,
    CASE WHEN i % 50 = 0 THEN FALSE ELSE TRUE END,
    NOW() - make_interval(days => (random() * 730)::int)
FROM generate_series(1, 50000) i;

-- =====================================================================
-- tags: 1K
-- =====================================================================
INSERT INTO tags (name, use_count, created_at)
SELECT
    'tag_' || i,
    (random() * 10000)::int,
    NOW() - make_interval(days => (random() * 730)::int)
FROM generate_series(1, 1000) i;

-- =====================================================================
-- posts: 500K
-- =====================================================================
INSERT INTO posts (author_id, content, mentioned_user_id, media_url, likes_count, comments_count, is_deleted, created_at)
SELECT
    1 + (i % 50000),
    (ARRAY[
        'Just finished a great book about distributed systems. Highly recommend.',
        'Beautiful sunset today. Sometimes you need to stop and look around.',
        'New blog post is up: how I optimized my Postgres queries last week.',
        'Coffee, code, and quiet morning. Best combination for productivity.',
        'Bitcoin is rallying again. Thoughts on where it goes next?',
        'Working on a premium feature for our SaaS product. Excited to ship.',
        'The detailed product specifications are finally complete.',
        'Special edition merch dropping next week. Stay tuned.',
        'Quality over quantity. Always.',
        'Just shipped a new feature to detect anomalies in real-time data.'
    ])[1 + (i % 10)] || ' ' || 'Post number ' || i,
    CASE WHEN i % 7 = 0 THEN 1 + ((i * 17) % 50000) ELSE NULL END,
    CASE WHEN i % 3 = 0 THEN 'https://media.example.com/' || i || '.jpg' ELSE NULL END,
    (random() * 1000)::int,
    (random() * 200)::int,
    CASE WHEN i % 20 = 0 THEN TRUE ELSE FALSE END,
    NOW() - make_interval(days => (random() * 1095)::int)
FROM generate_series(1, 500000) i;

-- =====================================================================
-- comments: 1M (deterministic post_id, no UNIQUE constraint to fight)
-- =====================================================================
INSERT INTO comments (post_id, author_id, content, likes_count, is_deleted, created_at)
SELECT
    1 + (i % 500000)::bigint,
    1 + (i % 50000),
    (ARRAY[
        'Great post, thanks for sharing!',
        'I disagree with this take.',
        'Could you elaborate on your second point?',
        'This matches my experience exactly.',
        'Have you considered the alternative approach?',
        'Bookmarking this for later.',
        'Excellent analysis.',
        'Not sure I follow.',
        'Reposting this with attribution.',
        'Looking forward to your next post.'
    ])[1 + (i % 10)],
    (random() * 50)::int,
    CASE WHEN i % 20 = 0 THEN TRUE ELSE FALSE END,
    NOW() - make_interval(days => (random() * 730)::int)
FROM generate_series(1, 1000000) i;

-- =====================================================================
-- likes: ~1M (each user likes 20 posts at coprime stride)
-- ON CONFLICT as safety net.
-- =====================================================================
INSERT INTO likes (user_id, post_id, created_at)
SELECT
    u AS user_id,
    1 + ((u - 1 + (offset_idx - 1) * 7) % 500000) AS post_id,
    NOW() - make_interval(days => (random() * 730)::int)
FROM generate_series(1, 50000) u
CROSS JOIN generate_series(1, 20) offset_idx
ON CONFLICT (user_id, post_id) DO NOTHING;

-- =====================================================================
-- follows: ~200K relationships (each user follows 4 others)
-- =====================================================================
INSERT INTO follows (follower_id, followed_id, created_at)
SELECT
    u AS follower_id,
    1 + ((u + stride - 1) % 50000) AS followed_id,
    NOW() - make_interval(days => (random() * 730)::int)
FROM generate_series(1, 50000) u
CROSS JOIN unnest(ARRAY[1, 1001, 10001, 25001]) stride
WHERE 1 + ((u + stride - 1) % 50000) != u
ON CONFLICT (follower_id, followed_id) DO NOTHING;

-- =====================================================================
-- notifications: 800K with ~95% read=true (Q11 partial index opportunity)
-- =====================================================================
INSERT INTO notifications (user_id, notification_type, payload, read, created_at)
SELECT
    1 + (i % 50000),
    (ARRAY['like', 'comment', 'follow', 'mention', 'reply'])[1 + (i % 5)],
    jsonb_build_object('source_user', 1 + ((i * 7) % 50000), 'target_id', 1 + ((i * 13) % 500000)),
    CASE WHEN i % 20 != 0 THEN TRUE ELSE FALSE END,
    NOW() - make_interval(days => (random() * 365)::int)
FROM generate_series(1, 800000) i;

-- =====================================================================
-- post_tags: 1.5M relations (3 tags per post at fixed offsets)
-- =====================================================================
INSERT INTO post_tags (post_id, tag_id)
SELECT
    p AS post_id,
    1 + ((p + tag_stride - 1) % 1000) AS tag_id
FROM generate_series(1, 500000) p
CROSS JOIN unnest(ARRAY[0, 333, 666]) tag_stride
ON CONFLICT (post_id, tag_id) DO NOTHING;

-- =====================================================================
-- Update statistics
-- =====================================================================
ANALYZE users;
ANALYZE posts;
ANALYZE comments;
ANALYZE likes;
ANALYZE follows;
ANALYZE notifications;
ANALYZE tags;
ANALYZE post_tags;

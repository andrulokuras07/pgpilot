-- =====================================================================
-- AppDB v1.0 — Schema base
-- Social network demo database for PgPilot project (SIS2404)
-- =====================================================================
-- Schema in English. Designed for query analysis with realistic volumes
-- so that EXPLAIN plans show meaningful anti-patterns.
-- =====================================================================

-- Enable extension for query stats
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Drop in correct order if re-running
DROP TABLE IF EXISTS notifications CASCADE;
DROP TABLE IF EXISTS post_tags CASCADE;
DROP TABLE IF EXISTS tags CASCADE;
DROP TABLE IF EXISTS likes CASCADE;
DROP TABLE IF EXISTS comments CASCADE;
DROP TABLE IF EXISTS follows CASCADE;
DROP TABLE IF EXISTS posts CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- =====================================================================
-- users — platform users
-- =====================================================================
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(50) UNIQUE NOT NULL,
    email           VARCHAR(200) UNIQUE NOT NULL,
    full_name       VARCHAR(200),
    bio             TEXT,
    avatar_url      VARCHAR(500),
    last_login      TIMESTAMP,
    is_verified     BOOLEAN DEFAULT FALSE,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- =====================================================================
-- posts — main content table (largest)
-- mentioned_user_id used by Q02 (OR vs UNION antipattern)
-- =====================================================================
CREATE TABLE posts (
    id                  BIGSERIAL PRIMARY KEY,
    author_id           INTEGER NOT NULL,        -- Q01: NO INDEX (planted)
    content             TEXT,                    -- Q03: LIKE '%text%' antipattern
    mentioned_user_id   INTEGER,                 -- For Q02 OR vs UNION
    media_url           VARCHAR(500),
    likes_count         INTEGER DEFAULT 0,
    comments_count      INTEGER DEFAULT 0,
    is_deleted          BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- =====================================================================
-- comments — comments on posts
-- =====================================================================
CREATE TABLE comments (
    id              BIGSERIAL PRIMARY KEY,
    post_id         BIGINT NOT NULL REFERENCES posts(id),
    author_id       INTEGER NOT NULL REFERENCES users(id),
    content         TEXT,
    parent_comment_id BIGINT REFERENCES comments(id),
    likes_count     INTEGER DEFAULT 0,
    is_deleted      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()        -- Q18: no index, ORDER BY needs it
);

-- =====================================================================
-- likes — likes on posts
-- =====================================================================
CREATE TABLE likes (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    post_id         BIGINT NOT NULL REFERENCES posts(id),
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, post_id)
);

-- =====================================================================
-- follows — follower relationships (self-referencing)
-- =====================================================================
CREATE TABLE follows (
    id              BIGSERIAL PRIMARY KEY,
    follower_id     INTEGER NOT NULL REFERENCES users(id),
    followed_id     INTEGER NOT NULL REFERENCES users(id),
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(follower_id, followed_id)
);

-- =====================================================================
-- notifications — user notifications (for Q11 partial index)
-- ~95% of rows are read=true, ~5% are read=false
-- =====================================================================
CREATE TABLE notifications (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    notification_type VARCHAR(50),
    payload         JSONB,
    read            BOOLEAN DEFAULT FALSE,         -- Q11: partial index opportunity
    created_at      TIMESTAMP DEFAULT NOW()
);

-- =====================================================================
-- tags — hashtags / topics
-- =====================================================================
CREATE TABLE tags (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(50) UNIQUE NOT NULL,
    use_count       INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- =====================================================================
-- post_tags — N:M between posts and tags
-- =====================================================================
CREATE TABLE post_tags (
    post_id         BIGINT REFERENCES posts(id),
    tag_id          INTEGER REFERENCES tags(id),
    PRIMARY KEY (post_id, tag_id)
);

-- =====================================================================
-- "Legitimate" indexes — what a developer would create on day 1.
-- Some critical ones are INTENTIONALLY MISSING (planted problems).
-- =====================================================================

-- users
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_last_login ON users(last_login);

-- posts
-- Q01: NO index on posts.author_id (planted)
-- Q08: NO covering index for (author_id, created_at) ORDER BY (planted)
CREATE INDEX idx_posts_created_at ON posts(created_at);
CREATE INDEX idx_posts_mentioned_user_id ON posts(mentioned_user_id);

-- comments
CREATE INDEX idx_comments_post_id ON comments(post_id);
CREATE INDEX idx_comments_author_id ON comments(author_id);
-- Q18: NO index on comments.created_at (planted)

-- likes
CREATE INDEX idx_likes_user_id ON likes(user_id);
CREATE INDEX idx_likes_post_id ON likes(post_id);

-- follows
CREATE INDEX idx_follows_follower_id ON follows(follower_id);
CREATE INDEX idx_follows_followed_id ON follows(followed_id);

-- notifications
CREATE INDEX idx_notifications_user_id ON notifications(user_id);
-- Q11: NO partial index on (user_id) WHERE read = false (planted)

-- tags
CREATE INDEX idx_tags_name ON tags(name);
CREATE INDEX idx_tags_use_count ON tags(use_count);

-- post_tags
CREATE INDEX idx_post_tags_tag_id ON post_tags(tag_id);

-- =====================================================================
-- Schema-level comments
-- =====================================================================
COMMENT ON TABLE users IS 'Platform user accounts';
COMMENT ON TABLE posts IS 'User posts (main content)';
COMMENT ON TABLE comments IS 'Comments on posts';
COMMENT ON TABLE likes IS 'Likes on posts';
COMMENT ON TABLE follows IS 'Follower relationships';
COMMENT ON TABLE notifications IS 'User notifications';
COMMENT ON TABLE tags IS 'Content tags / hashtags';
COMMENT ON TABLE post_tags IS 'Many-to-many tagging';

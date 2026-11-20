-- Nova's news desk on PostgreSQL / Supabase: the same tables as the SQLite database (news_intel/store.py),
-- plus pgvector embeddings for semantic search and a generated tsvector for keyword search.
-- Apply with `psql "$DATABASE_URL" -f migrations/postgres/001_news.sql`, or paste it into Supabase's SQL editor.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS articles (
    id            BIGSERIAL PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,              -- canonical link: one row per story
    original_url  TEXT NOT NULL,                     -- as the provider gave it, for checking
    title         TEXT NOT NULL,
    title_key     TEXT NOT NULL,
    publisher     TEXT NOT NULL DEFAULT '',
    publisher_url TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL,
    language      TEXT NOT NULL DEFAULT '',
    country       TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT 'general',
    subcategory   TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    image         TEXT NOT NULL DEFAULT '',
    published_at  TIMESTAMPTZ NOT NULL,              -- from the source
    collected_at  TIMESTAMPTZ NOT NULL,              -- when Nova collected it
    summary       TEXT NOT NULL DEFAULT '',
    key_facts     JSONB NOT NULL DEFAULT '[]',
    entities      JSONB NOT NULL DEFAULT '{}',
    location      TEXT NOT NULL DEFAULT '',
    importance    SMALLINT CHECK (importance BETWEEN 1 AND 10),
    impact        TEXT NOT NULL DEFAULT '',
    sentiment     TEXT NOT NULL DEFAULT '',
    claims        JSONB NOT NULL DEFAULT '[]',
    related_ids   BIGINT[] NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'processed', 'failed')),
    attempts      SMALLINT NOT NULL DEFAULT 0,
    error         TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    processed_at  TIMESTAMPTZ,
    embedding     vector(768),                       -- e.g. nomic-embed-text through Ollama, when semantic search is on
    search        tsvector GENERATED ALWAYS AS
                  (to_tsvector('english', title || ' ' || description || ' ' || summary)) STORED
);
CREATE INDEX IF NOT EXISTS articles_published ON articles (published_at DESC);
CREATE INDEX IF NOT EXISTS articles_category ON articles (category, published_at DESC);
CREATE INDEX IF NOT EXISTS articles_status ON articles (status, published_at DESC);
CREATE INDEX IF NOT EXISTS articles_title_key ON articles (title_key);
CREATE INDEX IF NOT EXISTS articles_search ON articles USING GIN (search);
CREATE INDEX IF NOT EXISTS articles_embedding ON articles USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS runs (
    id          BIGSERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    collected   INTEGER NOT NULL DEFAULT 0,
    added       INTEGER NOT NULL DEFAULT 0,
    duplicates  INTEGER NOT NULL DEFAULT 0,
    rejected    JSONB NOT NULL DEFAULT '{}',
    processed   INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    providers   JSONB NOT NULL DEFAULT '{}',
    errors      JSONB NOT NULL DEFAULT '[]',
    briefing    TEXT NOT NULL DEFAULT ''
);

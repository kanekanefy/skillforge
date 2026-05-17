-- skillforge SQLite schema
--
-- Design notes:
--   - We use FTS5 (built-in, no extra deps) for BM25 ranking.
--   - skills_fts is a contentless virtual table; the canonical row lives in `skills`.
--     We sync via triggers below so callers only ever write to `skills`.
--   - All TEXT timestamps are ISO-8601 UTC (sqlite stores as text; cheap & sortable).

PRAGMA journal_mode = WAL;        -- concurrent readers + one writer; good for hooks
PRAGMA synchronous = NORMAL;       -- WAL-safe; faster than FULL
PRAGMA foreign_keys = ON;

-- ─── core skills table ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS skills (
    skill_id        TEXT    PRIMARY KEY,   -- ULID
    name            TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    tags            TEXT    DEFAULT '',    -- space-separated
    category        TEXT    DEFAULT '',
    body            TEXT    NOT NULL,      -- the SKILL.md body (sans frontmatter)
    path            TEXT    NOT NULL,      -- absolute path to SKILL.md
    origin          TEXT    NOT NULL DEFAULT 'original',  -- original|fixed|derived|captured
    version         INTEGER NOT NULL DEFAULT 1,
    generation      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_skills_active ON skills(is_active);
CREATE INDEX IF NOT EXISTS idx_skills_origin ON skills(origin);

-- ─── FTS5 mirror for BM25 ─────────────────────────────────────────
-- 'content' option points at the canonical table; saves storage.
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    skill_id UNINDEXED,
    name,
    description,
    tags,
    body,
    content='skills',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS skills_ai AFTER INSERT ON skills BEGIN
    INSERT INTO skills_fts(rowid, skill_id, name, description, tags, body)
    VALUES (new.rowid, new.skill_id, new.name, new.description, new.tags, new.body);
END;
CREATE TRIGGER IF NOT EXISTS skills_ad AFTER DELETE ON skills BEGIN
    INSERT INTO skills_fts(skills_fts, rowid, skill_id, name, description, tags, body)
    VALUES ('delete', old.rowid, old.skill_id, old.name, old.description, old.tags, old.body);
END;
CREATE TRIGGER IF NOT EXISTS skills_au AFTER UPDATE ON skills BEGIN
    INSERT INTO skills_fts(skills_fts, rowid, skill_id, name, description, tags, body)
    VALUES ('delete', old.rowid, old.skill_id, old.name, old.description, old.tags, old.body);
    INSERT INTO skills_fts(rowid, skill_id, name, description, tags, body)
    VALUES (new.rowid, new.skill_id, new.name, new.description, new.tags, new.body);
END;

-- ─── per-skill quality metrics ────────────────────────────────────
CREATE TABLE IF NOT EXISTS skill_metrics (
    skill_id          TEXT    PRIMARY KEY REFERENCES skills(skill_id) ON DELETE CASCADE,
    total_selections  INTEGER NOT NULL DEFAULT 0,
    applied           INTEGER NOT NULL DEFAULT 0,
    effective         INTEGER NOT NULL DEFAULT 0,
    fallback          INTEGER NOT NULL DEFAULT 0,
    completed_tasks   INTEGER NOT NULL DEFAULT 0,
    containing_tasks  INTEGER NOT NULL DEFAULT 0,
    last_used_at      TEXT
);

-- ─── version lineage (FIX/DERIVED/CAPTURED) ───────────────────────
CREATE TABLE IF NOT EXISTS skill_lineage (
    child_id    TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    parent_id   TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,  -- fix | derived | captured
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (child_id, parent_id)
);

-- ─── anti-loop signatures for evolution ───────────────────────────
CREATE TABLE IF NOT EXISTS addressed_degradations (
    skill_id         TEXT NOT NULL,
    signature        TEXT NOT NULL,
    last_addressed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (skill_id, signature)
);

-- ─── evolution queue (mirrors ~/.skillforge/queue/evolve.jsonl) ───
-- Stored in SQL too for query convenience; jsonl is the durable form.
CREATE TABLE IF NOT EXISTS evolve_queue (
    queue_id      TEXT PRIMARY KEY,            -- ULID
    skill_id      TEXT,                         -- nullable for CAPTURED
    kind          TEXT NOT NULL,                -- fix | derived | captured
    candidate     TEXT NOT NULL,                -- JSON blob with full context
    enqueued_at   TEXT NOT NULL DEFAULT (datetime('now')),
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
    backend       TEXT,
    finished_at   TEXT,
    error         TEXT
);

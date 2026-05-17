"""Thin SQLite wrapper.

Deliberately stateless: each function opens a connection, does its work,
closes. Hooks fire fast and exit fast, so we don't want long-lived
connections fighting for the WAL lock.

For Phase 1 we only need:
  - init_schema(): apply schema.sql idempotently
  - search(query, limit): BM25 against skills_fts
  - seed_dummies(): insert demo skills
  - list_skills(): full listing
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import resources
from typing import Iterator

from .. import config


def _schema_sql() -> str:
    """Read schema.sql packaged alongside this module."""
    return resources.files("skillforge.store").joinpath("schema.sql").read_text()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection with row_factory set so callers get dict-like rows."""
    config.ensure_layout()
    conn = sqlite3.connect(config.db_path(), isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_schema() -> None:
    """Apply schema.sql. Safe to call repeatedly."""
    with connect() as conn:
        conn.executescript(_schema_sql())


def search(query: str, limit: int = 5) -> list[sqlite3.Row]:
    """BM25 search against skills_fts.

    Returns top-N rows ordered by rank (lower = better in FTS5).
    Falls back to LIKE search if query is too short to FTS5-tokenize.
    """
    if not query.strip():
        return []
    sql_fts = """
        SELECT s.skill_id, s.name, s.description, s.tags, bm25(skills_fts) AS rank
        FROM skills_fts
        JOIN skills s ON s.rowid = skills_fts.rowid
        WHERE skills_fts MATCH ? AND s.is_active = 1
        ORDER BY rank
        LIMIT ?
    """
    sql_like = """
        SELECT skill_id, name, description, tags, 0.0 AS rank
        FROM skills
        WHERE is_active = 1 AND (name LIKE ? OR description LIKE ?)
        LIMIT ?
    """
    with connect() as conn:
        # FTS5 hates some user input (unbalanced quotes, etc.). Defensive try.
        try:
            return list(conn.execute(sql_fts, (_sanitize_fts(query), limit)))
        except sqlite3.OperationalError:
            wild = f"%{query.strip()[:80]}%"
            return list(conn.execute(sql_like, (wild, wild, limit)))


# Common English stop words. Kept short on purpose — we want to drop the
# words that match everything (is/the/in) but keep content words even if
# they're frequent in code contexts (file/data/git).
_STOP = frozenset("""
a an the and or but if then else of in on at to for with by from up out
is are was were be been being do does did has have had can could would
should will shall may might must this that these those it its as so than
i me my our your their his her them us we you they he she who whom whose
what when where why how which here there now then again very much more
most some any all each every no not nor only own same other another such
into over under above below between through during before after about
please just like want need get got make made take took give gave go went
do does doing done done done been hi hello yo
""".split())


def _sanitize_fts(q: str) -> str:
    """Turn raw user input into a safe FTS5 MATCH query.

    Strategy:
      - Strip punctuation
      - Drop tokens shorter than 3 chars
      - Drop common stop words (so "weather in tokyo" doesn't match docs
        purely on "in")
      - Quote each remaining token and join with OR (BM25 handles ranking)
    """
    tokens: list[str] = []
    for raw in q.lower().split():
        t = raw.strip(".,;:!?\"'()[]{}<>`/\\")
        if len(t) < 3:
            continue
        if t in _STOP:
            continue
        # FTS5 needs alphanumerics + a few; bail tokens that are pure punctuation
        if not any(c.isalnum() for c in t):
            continue
        tokens.append(f'"{t}"')
    return " OR ".join(tokens)


def list_skills() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute(
            "SELECT skill_id, name, description, origin, version, generation, is_active "
            "FROM skills ORDER BY name"
        ))


def insert_skill(*, skill_id: str, name: str, description: str,
                 body: str = "", path: str = "", tags: str = "",
                 category: str = "", origin: str = "original") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO skills "
            "(skill_id, name, description, tags, category, body, path, origin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (skill_id, name, description, tags, category, body, path, origin),
        )


def bump_metrics(skill_id: str, **deltas: int) -> None:
    """Increment one or more counter columns in skill_metrics atomically.

    Creates the row if it doesn't exist (UPSERT). All deltas must be ints.

    Valid column names: total_selections, applied, effective, fallback,
    completed_tasks, containing_tasks.
    """
    valid = {"total_selections", "applied", "effective", "fallback",
             "completed_tasks", "containing_tasks"}
    if not skill_id or not deltas:
        return
    bad = set(deltas) - valid
    if bad:
        raise ValueError(f"unknown metric columns: {bad}")

    # Build a single UPSERT that increments each named column.
    # SQLite ON CONFLICT lets us do create-or-increment in one statement.
    cols = list(deltas)
    set_clause = ", ".join(f"{c} = {c} + ?" for c in cols)
    insert_cols = "skill_id, last_used_at, " + ", ".join(cols)
    insert_vals = "?, datetime('now'), " + ", ".join(["?"] * len(cols))
    values = [deltas[c] for c in cols]

    sql = f"""
        INSERT INTO skill_metrics ({insert_cols})
        VALUES ({insert_vals})
        ON CONFLICT(skill_id) DO UPDATE SET
            {set_clause},
            last_used_at = datetime('now')
    """
    # Bind values twice: once for INSERT, once for SET.
    with connect() as conn:
        conn.execute(sql, [skill_id] + values + values)


def get_metrics(skill_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM skill_metrics WHERE skill_id = ?", (skill_id,)
        ).fetchone()
    return dict(row) if row else None


def all_metrics() -> list[dict]:
    """Return metrics joined with skill name for display."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT m.*, s.name FROM skill_metrics m "
            "JOIN skills s ON s.skill_id = m.skill_id "
            "ORDER BY m.last_used_at DESC NULLS LAST"
        ).fetchall()
    return [dict(r) for r in rows]


def find_skill_by_name(name: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT skill_id, name FROM skills WHERE name = ? AND is_active = 1",
            (name,)
        ).fetchone()


def seed_dummies() -> None:
    """Three demo skills for Phase 1 smoke testing.

    Real installs go through `sf install <skill-id>` later.
    """
    demo = [
        dict(
            skill_id="01HDEMO000000000000001",
            name="sql-format",
            description="Format SQL queries with consistent indentation and capitalize keywords.",
            tags="sql database format",
            category="data",
            body="When the user shares a raw SQL query, reformat it with each clause on its own line, capitalize keywords, indent subqueries by 2 spaces.",
            path="(demo)",
        ),
        dict(
            skill_id="01HDEMO000000000000002",
            name="git-log-explain",
            description="Summarize recent git commits into a human-readable changelog grouped by area.",
            tags="git changelog vcs",
            category="dev",
            body="Run `git log --oneline -n 20`, then group commits by directory or feature area, output as bullets.",
            path="(demo)",
        ),
        dict(
            skill_id="01HDEMO000000000000003",
            name="json-pretty",
            description="Pretty-print and validate arbitrary JSON, surfacing parse errors with line numbers.",
            tags="json format validate",
            category="data",
            body="Use `python -m json.tool` for pretty-print; on parse error, show the offending line and character offset.",
            path="(demo)",
        ),
    ]
    for d in demo:
        insert_skill(**d)

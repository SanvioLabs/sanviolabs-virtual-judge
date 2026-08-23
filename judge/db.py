"""SQLite database for Virtual Judge."""

import json
import logging
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

# Overridable so a test run does not write into the event database sitting in
# the project root. The Playwright suite starts a real server, and without this
# every browser test filed its fixtures alongside real hackathon results.
logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("VJ_DB_PATH") or Path(__file__).parent.parent / "judge.db")


def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """A connection that closes even when the body raises.

    sqlite3's own context manager governs the transaction, not the handle, so
    closing has to be explicit. Every function here used to open a connection
    and close it on the last line, which means any exception in between leaked
    the handle. Under WAL a leaked handle holds a read transaction open, and
    the write-ahead log stops checkpointing.
    """
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                rubric_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                FOREIGN KEY (rubric_id) REFERENCES rubrics(id)
            );

            CREATE TABLE IF NOT EXISTS rubrics (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                categories_json TEXT NOT NULL,
                scale_min INTEGER NOT NULL DEFAULT 1,
                scale_max INTEGER NOT NULL DEFAULT 5,
                calibration TEXT,
                judge_persona TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                team_name TEXT NOT NULL,
                rubric_id TEXT NOT NULL,
                audio_path TEXT,
                transcript TEXT,
                status TEXT NOT NULL DEFAULT 'recording',
                created_at TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id),
                FOREIGN KEY (rubric_id) REFERENCES rubrics(id)
            );

            CREATE TABLE IF NOT EXISTS scores (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL,
                category TEXT NOT NULL,
                score INTEGER NOT NULL,
                rationale TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (submission_id) REFERENCES submissions(id)
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL UNIQUE,
                overall_score REAL NOT NULL,
                summary TEXT NOT NULL,
                audio_path TEXT,
                spoken_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (submission_id) REFERENCES submissions(id)
            );

            CREATE TABLE IF NOT EXISTS finalist_runs (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                rubric_id TEXT NOT NULL,
                top_picks_json TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                audio_path TEXT,
                spoken_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id),
                FOREIGN KEY (rubric_id) REFERENCES rubrics(id)
            );

            CREATE TABLE IF NOT EXISTS prfaqs (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL UNIQUE,
                content_json TEXT NOT NULL,
                markdown TEXT NOT NULL,
                model TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (submission_id) REFERENCES submissions(id)
            );
        """)
        # Migrations for existing databases
        _migrate(conn)


def _migrate(conn):
    """Apply schema migrations for existing databases."""
    # Check if submissions table has event_id column
    cols = [row[1] for row in conn.execute("PRAGMA table_info(submissions)").fetchall()]
    if "event_id" not in cols:
        _migrate_event_id(conn)

    # Additive: the spoken verdict read aloud at the event. Runs last so it also
    # patches whatever shape the destructive migration above leaves behind.
    for table in ("reviews", "finalist_runs"):
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if cols and "spoken_text" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN spoken_text TEXT")
            conn.commit()


def _backup_before_destructive_migration(conn) -> Path | None:
    """Take a consistent copy of the database before dropping anything.

    The migration below destroys every submission, score, review, PRFAQ and
    finalist round. It runs automatically at startup, so without this an
    operator opening an older database loses the whole record of an event and
    is never told. The README calls judge.db the complete event record.

    Copied through sqlite's own backup API rather than the filesystem, because
    the database runs in WAL mode and a file copy can miss committed pages
    still sitting in the log.
    """
    if not DB_PATH.exists():
        return None

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = DB_PATH.with_name(f"{DB_PATH.stem}.pre-migration-{stamp}.db")
    try:
        with connection_to(backup_path) as target:
            conn.backup(target)
    except sqlite3.Error as e:
        logger.error("Could not back up %s before migrating: %s", DB_PATH, e)
        return None

    logger.warning(
        "Migrating an old database. Every submission, score, review and PRFAQ in it "
        "is being dropped. A copy of the original is at %s",
        backup_path,
    )
    return backup_path


@contextmanager
def connection_to(path: Path) -> Iterator[sqlite3.Connection]:
    """A connection to a specific file, closed on the way out."""
    conn = sqlite3.connect(str(path))
    try:
        yield conn
    finally:
        conn.close()


def _migrate_event_id(conn):
    """Old schema detected. Recreate with event_id.

    Destructive: the tables below are dropped. The database is copied aside
    first and the location is logged, so the loss is recoverable and announced
    rather than silent.
    """
    _backup_before_destructive_migration(conn)
    conn.executescript("""
        DROP TABLE IF EXISTS prfaqs;
        DROP TABLE IF EXISTS finalist_runs;
        DROP TABLE IF EXISTS reviews;
        DROP TABLE IF EXISTS scores;
        DROP TABLE IF EXISTS submissions;

        CREATE TABLE submissions (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            team_name TEXT NOT NULL,
            rubric_id TEXT NOT NULL,
            audio_path TEXT,
            transcript TEXT,
            status TEXT NOT NULL DEFAULT 'recording',
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (rubric_id) REFERENCES rubrics(id)
        );

        CREATE TABLE scores (
            id TEXT PRIMARY KEY,
            submission_id TEXT NOT NULL,
            category TEXT NOT NULL,
            score INTEGER NOT NULL,
            rationale TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (submission_id) REFERENCES submissions(id)
        );

        CREATE TABLE reviews (
            id TEXT PRIMARY KEY,
            submission_id TEXT NOT NULL UNIQUE,
            overall_score REAL NOT NULL,
            summary TEXT NOT NULL,
            audio_path TEXT,
            spoken_text TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (submission_id) REFERENCES submissions(id)
        );

        CREATE TABLE finalist_runs (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            rubric_id TEXT NOT NULL,
            top_picks_json TEXT NOT NULL,
            reasoning TEXT NOT NULL,
            audio_path TEXT,
            spoken_text TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (rubric_id) REFERENCES rubrics(id)
        );

        CREATE TABLE prfaqs (
            id TEXT PRIMARY KEY,
            submission_id TEXT NOT NULL UNIQUE,
            content_json TEXT NOT NULL,
            markdown TEXT NOT NULL,
            model TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (submission_id) REFERENCES submissions(id)
        );
    """)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id() -> str:
    return str(uuid.uuid4())


# --- Events ---

def create_event(name: str, rubric_id: str, description: str = "") -> str:
    """Create a new event (hackathon), return its ID."""
    event_id = _id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO events (id, name, description, rubric_id, status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
            (event_id, name, description, rubric_id, _now())
        )
        conn.commit()
        return event_id


def get_event(event_id: str) -> dict | None:
    """Get an event by ID."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None


def list_events() -> list[dict]:
    """List all events, newest first."""
    with connection() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


EVENT_COLUMNS = frozenset({"name", "description", "rubric_id", "status"})
SUBMISSION_COLUMNS = frozenset({
    "team_name", "event_id", "rubric_id", "audio_path", "transcript", "status",
})


def _assert_columns(keys, allowed: frozenset, table: str):
    """Refuse a column name that is not on the list.

    The column has to be interpolated: SQLite takes no parameter in that
    position. Today every caller passes a literal keyword, so nothing hostile
    reaches here, but the guard is what keeps that true after the next
    refactor decides to forward a request body.
    """
    unknown = sorted(set(keys) - allowed)
    if unknown:
        raise ValueError(f"Not a column of {table}: {', '.join(unknown)}")


def update_event(event_id: str, **kwargs):
    """Update event fields."""
    _assert_columns(kwargs, EVENT_COLUMNS, "events")
    with connection() as conn:
        for key, value in kwargs.items():
            conn.execute(f"UPDATE events SET {key} = ? WHERE id = ?", (value, event_id))
        conn.commit()


    # --- Rubrics ---

def create_rubric(name: str, categories: list[dict], scale_min: int = 1,
                  scale_max: int = 5, description: str = "",
                  calibration: str = "", judge_persona: str = "") -> str:
    """Insert a rubric, return its ID."""
    rubric_id = _id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO rubrics (id, name, description, categories_json, scale_min, scale_max, calibration, judge_persona, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rubric_id, name, description, json.dumps(categories), scale_min, scale_max, calibration, judge_persona, _now())
        )
        conn.commit()
        return rubric_id


def get_rubric(rubric_id: str) -> dict | None:
    """Get a rubric by ID."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM rubrics WHERE id = ?", (rubric_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["categories"] = json.loads(d["categories_json"])
        return d


def list_rubrics() -> list[dict]:
    """List all rubrics."""
    with connection() as conn:
        rows = conn.execute("SELECT * FROM rubrics ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["categories"] = json.loads(d["categories_json"])
            result.append(d)
        return result


    # --- Submissions ---

def create_submission(team_name: str, event_id: str, rubric_id: str) -> str:
    """Create a new submission, return its ID."""
    sub_id = _id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO submissions (id, event_id, team_name, rubric_id, status, created_at) VALUES (?, ?, ?, ?, 'recording', ?)",
            (sub_id, event_id, team_name, rubric_id, _now())
        )
        conn.commit()
        return sub_id


def delete_submission(sub_id: str) -> list[str]:
    """Delete one submission and everything hanging off it.

    Returns the audio paths that were recorded against it, so the caller can
    remove the files. The database does not own them and will not clean them up.

    Children go first: foreign keys are enforced, so deleting the parent while
    a score still points at it fails rather than cascading.
    """
    with connection() as conn:
        row = conn.execute("SELECT audio_path FROM submissions WHERE id = ?", (sub_id,)).fetchone()
        if row is None:
            raise KeyError(sub_id)

        audio_paths = [row["audio_path"]] if row["audio_path"] else []
        review = conn.execute(
            "SELECT audio_path FROM reviews WHERE submission_id = ?", (sub_id,)
        ).fetchone()
        if review and review["audio_path"]:
            audio_paths.append(review["audio_path"])

        for table in ("prfaqs", "reviews", "scores"):
            conn.execute(f"DELETE FROM {table} WHERE submission_id = ?", (sub_id,))
        conn.execute("DELETE FROM submissions WHERE id = ?", (sub_id,))
        conn.commit()
        return audio_paths


def delete_event(event_id: str) -> list[str]:
    """Delete an event, every submission in it, and every finalist round it ran.

    Returns every audio path involved, for the same reason delete_submission does.
    """
    with connection() as conn:
        if conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone() is None:
            raise KeyError(event_id)

        sub_ids = [
            r["id"] for r in
            conn.execute("SELECT id FROM submissions WHERE event_id = ?", (event_id,)).fetchall()
        ]
        audio_paths = [
            r["audio_path"] for r in
            conn.execute("SELECT audio_path FROM submissions WHERE event_id = ?", (event_id,)).fetchall()
            if r["audio_path"]
        ]
        for r in conn.execute(
            "SELECT audio_path FROM reviews WHERE submission_id IN "
            "(SELECT id FROM submissions WHERE event_id = ?)", (event_id,)
        ).fetchall():
            if r["audio_path"]:
                audio_paths.append(r["audio_path"])
        for r in conn.execute(
            "SELECT audio_path FROM finalist_runs WHERE event_id = ?", (event_id,)
        ).fetchall():
            if r["audio_path"]:
                audio_paths.append(r["audio_path"])

        if sub_ids:
            marks = ",".join("?" for _ in sub_ids)
            for table in ("prfaqs", "reviews", "scores"):
                conn.execute(f"DELETE FROM {table} WHERE submission_id IN ({marks})", sub_ids)
        conn.execute("DELETE FROM finalist_runs WHERE event_id = ?", (event_id,))
        conn.execute("DELETE FROM submissions WHERE event_id = ?", (event_id,))
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
        return audio_paths


def submission_counts_by_event() -> dict[str, dict]:
    """Total and completed submission counts for every event, in one query.

    The event list used to run list_submissions once per event. On a database
    that has accumulated a season of events that is hundreds of queries to fill
    a dropdown, and nothing deletes events, so it only ever grew.
    """
    with connection() as conn:
        rows = conn.execute(
            "SELECT event_id, "
            "COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS completed "
            "FROM submissions GROUP BY event_id"
        ).fetchall()
        return {
            r["event_id"]: {"submission_count": r["total"], "completed_count": r["completed"] or 0}
            for r in rows
        }


def update_submission(sub_id: str, **kwargs):
    """Update submission fields."""
    _assert_columns(kwargs, SUBMISSION_COLUMNS, "submissions")
    with connection() as conn:
        for key, value in kwargs.items():
            conn.execute(f"UPDATE submissions SET {key} = ? WHERE id = ?", (value, sub_id))
        conn.commit()


def get_submission(sub_id: str) -> dict | None:
    """Get a submission by ID."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)).fetchone()
        return dict(row) if row else None


def list_submissions(event_id: str | None = None, rubric_id: str | None = None) -> list[dict]:
    """List submissions, optionally filtered by event or rubric."""
    with connection() as conn:
        if event_id:
            rows = conn.execute("SELECT * FROM submissions WHERE event_id = ? ORDER BY created_at", (event_id,)).fetchall()
        elif rubric_id:
            rows = conn.execute("SELECT * FROM submissions WHERE rubric_id = ? ORDER BY created_at", (rubric_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM submissions ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]


    # --- Scores ---

def save_scores(submission_id: str, scores: list[dict]):
    """Save category scores for a submission."""
    with connection() as conn:
        for s in scores:
            conn.execute(
                "INSERT INTO scores (id, submission_id, category, score, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (_id(), submission_id, s["category"], s["score"], s.get("rationale", ""), _now())
            )
        conn.commit()


def get_scores(submission_id: str) -> list[dict]:
    """Get all scores for a submission."""
    with connection() as conn:
        rows = conn.execute("SELECT * FROM scores WHERE submission_id = ? ORDER BY category", (submission_id,)).fetchall()
        return [dict(r) for r in rows]


    # --- Reviews ---

def save_review(submission_id: str, overall_score: float, summary: str, audio_path: str = "", spoken_text: str = "") -> str:
    """Save the overall review for a submission.

    `spoken_text` is what the voice actually said — kept so the export and the UI
    can show the spoken verdict, not just the written rationales.
    """
    review_id = _id()
    with connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reviews (id, submission_id, overall_score, summary, audio_path, spoken_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (review_id, submission_id, overall_score, summary, audio_path, spoken_text, _now())
        )
        conn.commit()
        return review_id


def get_review(submission_id: str) -> dict | None:
    """Get the review for a submission."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM reviews WHERE submission_id = ?", (submission_id,)).fetchone()
        return dict(row) if row else None


    # --- PRFAQs ---

def save_prfaq(submission_id: str, content: dict, markdown: str, model: str = "") -> str:
    """Save the PRFAQ for a submission, replacing any earlier one.

    Both forms are kept: `content` so the UI can render sections without parsing
    Markdown, and `markdown` so the export ships exactly what was generated rather
    than re-rendering it later against a template that may have moved.
    """
    prfaq_id = _id()
    with connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO prfaqs (id, submission_id, content_json, markdown, model, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (prfaq_id, submission_id, json.dumps(content), markdown, model, _now())
        )
        conn.commit()
        return prfaq_id


def get_prfaq(submission_id: str) -> dict | None:
    """Get the PRFAQ for a submission."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM prfaqs WHERE submission_id = ?", (submission_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["content"] = json.loads(d["content_json"])
        return d


    # --- Finalist Runs ---

def save_finalist_run(event_id: str, rubric_id: str, top_picks: list[dict], reasoning: str, audio_path: str = "", spoken_text: str = "") -> str:
    """Save a finalist run result."""
    run_id = _id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO finalist_runs (id, event_id, rubric_id, top_picks_json, reasoning, audio_path, spoken_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, event_id, rubric_id, json.dumps(top_picks), reasoning, audio_path, spoken_text, _now())
        )
        conn.commit()
        return run_id


def get_latest_finalist_run(event_id: str) -> dict | None:
    """Get the most recent finalist run for an event."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM finalist_runs WHERE event_id = ? ORDER BY created_at DESC LIMIT 1",
            (event_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["top_picks"] = json.loads(d["top_picks_json"])
        return d

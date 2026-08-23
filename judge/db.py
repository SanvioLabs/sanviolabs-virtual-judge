"""SQLite database for Virtual Judge."""

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent.parent / "judge.db"


def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
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
    conn.close()


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


def _migrate_event_id(conn):
    """Old schema detected — recreate with event_id.

    Drop and recreate (data loss acceptable for pre-release).
    """
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
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return str(uuid.uuid4())


# --- Events ---

def create_event(name: str, rubric_id: str, description: str = "") -> str:
    """Create a new event (hackathon), return its ID."""
    event_id = _id()
    conn = get_db()
    conn.execute(
        "INSERT INTO events (id, name, description, rubric_id, status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
        (event_id, name, description, rubric_id, _now())
    )
    conn.commit()
    conn.close()
    return event_id


def get_event(event_id: str) -> Optional[dict]:
    """Get an event by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_events() -> list[dict]:
    """List all events, newest first."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM events ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_event(event_id: str, **kwargs):
    """Update event fields."""
    conn = get_db()
    for key, value in kwargs.items():
        conn.execute(f"UPDATE events SET {key} = ? WHERE id = ?", (value, event_id))
    conn.commit()
    conn.close()


# --- Rubrics ---

def create_rubric(name: str, categories: list[dict], scale_min: int = 1,
                  scale_max: int = 5, description: str = "",
                  calibration: str = "", judge_persona: str = "") -> str:
    """Insert a rubric, return its ID."""
    rubric_id = _id()
    conn = get_db()
    conn.execute(
        "INSERT INTO rubrics (id, name, description, categories_json, scale_min, scale_max, calibration, judge_persona, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rubric_id, name, description, json.dumps(categories), scale_min, scale_max, calibration, judge_persona, _now())
    )
    conn.commit()
    conn.close()
    return rubric_id


def get_rubric(rubric_id: str) -> Optional[dict]:
    """Get a rubric by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM rubrics WHERE id = ?", (rubric_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["categories"] = json.loads(d["categories_json"])
    return d


def list_rubrics() -> list[dict]:
    """List all rubrics."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM rubrics ORDER BY created_at DESC").fetchall()
    conn.close()
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
    conn = get_db()
    conn.execute(
        "INSERT INTO submissions (id, event_id, team_name, rubric_id, status, created_at) VALUES (?, ?, ?, ?, 'recording', ?)",
        (sub_id, event_id, team_name, rubric_id, _now())
    )
    conn.commit()
    conn.close()
    return sub_id


def update_submission(sub_id: str, **kwargs):
    """Update submission fields."""
    conn = get_db()
    for key, value in kwargs.items():
        conn.execute(f"UPDATE submissions SET {key} = ? WHERE id = ?", (value, sub_id))
    conn.commit()
    conn.close()


def get_submission(sub_id: str) -> Optional[dict]:
    """Get a submission by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_submissions(event_id: Optional[str] = None, rubric_id: Optional[str] = None) -> list[dict]:
    """List submissions, optionally filtered by event or rubric."""
    conn = get_db()
    if event_id:
        rows = conn.execute("SELECT * FROM submissions WHERE event_id = ? ORDER BY created_at", (event_id,)).fetchall()
    elif rubric_id:
        rows = conn.execute("SELECT * FROM submissions WHERE rubric_id = ? ORDER BY created_at", (rubric_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM submissions ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Scores ---

def save_scores(submission_id: str, scores: list[dict]):
    """Save category scores for a submission."""
    conn = get_db()
    for s in scores:
        conn.execute(
            "INSERT INTO scores (id, submission_id, category, score, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (_id(), submission_id, s["category"], s["score"], s.get("rationale", ""), _now())
        )
    conn.commit()
    conn.close()


def get_scores(submission_id: str) -> list[dict]:
    """Get all scores for a submission."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM scores WHERE submission_id = ? ORDER BY category", (submission_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Reviews ---

def save_review(submission_id: str, overall_score: float, summary: str, audio_path: str = "", spoken_text: str = "") -> str:
    """Save the overall review for a submission.

    `spoken_text` is what the voice actually said — kept so the export and the UI
    can show the spoken verdict, not just the written rationales.
    """
    review_id = _id()
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO reviews (id, submission_id, overall_score, summary, audio_path, spoken_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (review_id, submission_id, overall_score, summary, audio_path, spoken_text, _now())
    )
    conn.commit()
    conn.close()
    return review_id


def get_review(submission_id: str) -> Optional[dict]:
    """Get the review for a submission."""
    conn = get_db()
    row = conn.execute("SELECT * FROM reviews WHERE submission_id = ?", (submission_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# --- PRFAQs ---

def save_prfaq(submission_id: str, content: dict, markdown: str, model: str = "") -> str:
    """Save the PRFAQ for a submission, replacing any earlier one.

    Both forms are kept: `content` so the UI can render sections without parsing
    Markdown, and `markdown` so the export ships exactly what was generated rather
    than re-rendering it later against a template that may have moved.
    """
    prfaq_id = _id()
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO prfaqs (id, submission_id, content_json, markdown, model, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (prfaq_id, submission_id, json.dumps(content), markdown, model, _now())
    )
    conn.commit()
    conn.close()
    return prfaq_id


def get_prfaq(submission_id: str) -> Optional[dict]:
    """Get the PRFAQ for a submission."""
    conn = get_db()
    row = conn.execute("SELECT * FROM prfaqs WHERE submission_id = ?", (submission_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["content"] = json.loads(d["content_json"])
    return d


# --- Finalist Runs ---

def save_finalist_run(event_id: str, rubric_id: str, top_picks: list[dict], reasoning: str, audio_path: str = "", spoken_text: str = "") -> str:
    """Save a finalist run result."""
    run_id = _id()
    conn = get_db()
    conn.execute(
        "INSERT INTO finalist_runs (id, event_id, rubric_id, top_picks_json, reasoning, audio_path, spoken_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, event_id, rubric_id, json.dumps(top_picks), reasoning, audio_path, spoken_text, _now())
    )
    conn.commit()
    conn.close()
    return run_id


def get_latest_finalist_run(event_id: str) -> Optional[dict]:
    """Get the most recent finalist run for an event."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM finalist_runs WHERE event_id = ? ORDER BY created_at DESC LIMIT 1",
        (event_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["top_picks"] = json.loads(d["top_picks_json"])
    return d

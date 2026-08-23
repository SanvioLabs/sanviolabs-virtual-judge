"""Tests for the database and rubric modules."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from judge import db, rubrics
from judge.rubrics import load_rubric_from_yaml


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    """Use a temporary database for each test."""
    test_db = tmp_path / "test.db"
    with patch.object(db, "DB_PATH", test_db):
        db.init_db()
        yield test_db


class TestEvents:
    def test_create_and_get_event(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event("Hackathon 2026", rubric_id, "A fun event")

        event = db.get_event(event_id)
        assert event is not None
        assert event["name"] == "Hackathon 2026"
        assert event["rubric_id"] == rubric_id
        assert event["status"] == "active"

    def test_list_events(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        db.create_event("Event A", rubric_id)
        db.create_event("Event B", rubric_id)

        events = db.list_events()
        assert len(events) == 2


class TestDatabase:
    def test_create_and_get_rubric(self):
        categories = [
            {"name": "Impact", "description": "Real-world impact", "weight": 1.0},
            {"name": "Innovation", "description": "Creative approach", "weight": 1.0},
        ]
        rubric_id = db.create_rubric(
            name="Test Rubric",
            categories=categories,
            scale_min=1,
            scale_max=5,
            description="A test rubric",
            calibration="Score fairly.",
            judge_persona="You are a judge.",
        )

        rubric = db.get_rubric(rubric_id)
        assert rubric is not None
        assert rubric["name"] == "Test Rubric"
        assert rubric["scale_min"] == 1
        assert rubric["scale_max"] == 5
        assert len(rubric["categories"]) == 2
        assert rubric["categories"][0]["name"] == "Impact"

    def test_list_rubrics(self):
        db.create_rubric("Rubric A", [{"name": "X", "description": "x", "weight": 1}])
        db.create_rubric("Rubric B", [{"name": "Y", "description": "y", "weight": 1}])

        rubrics = db.list_rubrics()
        assert len(rubrics) == 2

    def test_submission_lifecycle(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event("Test Event", rubric_id)
        sub_id = db.create_submission("Team Alpha", event_id, rubric_id)

        sub = db.get_submission(sub_id)
        assert sub["team_name"] == "Team Alpha"
        assert sub["event_id"] == event_id
        assert sub["status"] == "recording"

        db.update_submission(sub_id, status="transcribing", transcript="Hello world")
        sub = db.get_submission(sub_id)
        assert sub["status"] == "transcribing"
        assert sub["transcript"] == "Hello world"

    def test_list_submissions_by_event(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_a = db.create_event("Event A", rubric_id)
        event_b = db.create_event("Event B", rubric_id)

        db.create_submission("Team 1", event_a, rubric_id)
        db.create_submission("Team 2", event_a, rubric_id)
        db.create_submission("Team 3", event_b, rubric_id)

        subs_a = db.list_submissions(event_id=event_a)
        subs_b = db.list_submissions(event_id=event_b)
        assert len(subs_a) == 2
        assert len(subs_b) == 1

    def test_scores(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event("E", rubric_id)
        sub_id = db.create_submission("Team Beta", event_id, rubric_id)

        db.save_scores(sub_id, [
            {"category": "Impact", "score": 4, "rationale": "Good problem choice"},
            {"category": "Innovation", "score": 3, "rationale": "Decent approach"},
        ])

        scores = db.get_scores(sub_id)
        assert len(scores) == 2

    def test_review(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event("E", rubric_id)
        sub_id = db.create_submission("Team Gamma", event_id, rubric_id)

        db.save_review(sub_id, 3.5, "Solid effort overall.", "/audio/test.mp3")
        review = db.get_review(sub_id)
        assert review["overall_score"] == 3.5
        assert review["summary"] == "Solid effort overall."

    def test_finalist_run(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event("E", rubric_id)

        top_picks = [
            {"rank": 1, "team_name": "Alpha", "reasoning": "Best overall"},
            {"rank": 2, "team_name": "Beta", "reasoning": "Strong second"},
            {"rank": 3, "team_name": "Gamma", "reasoning": "Creative approach"},
        ]
        db.save_finalist_run(event_id, rubric_id, top_picks, "Strong cohort overall.")

        run = db.get_latest_finalist_run(event_id)
        assert run is not None
        assert len(run["top_picks"]) == 3
        assert run["top_picks"][0]["team_name"] == "Alpha"


class TestAFreshCloneComesUpUsable:
    """The rest of the suite mocks the rubric sync away, so nothing else proves
    that a clone with no `judge.db` starts, builds one, and finds a rubric in it.

    This is the first-run path every new user takes, and it is the one that breaks
    silently: an empty rubrics directory or a rubric that fails to parse leaves a
    server that starts fine and cannot judge anything.
    """

    def _fresh_clone(self, tmp_path):
        """A rubrics directory holding only the files git actually ships."""
        import shutil
        repo_rubrics = Path(__file__).parent.parent / "rubrics"
        clone = tmp_path / "rubrics"
        clone.mkdir()
        shutil.copy2(repo_rubrics / "example-hackathon.yaml", clone)
        return clone

    def test_startup_creates_the_database_and_loads_the_shipped_rubric(self, tmp_path):
        clone = self._fresh_clone(tmp_path)
        db_path = tmp_path / "judge.db"
        with patch.object(db, "DB_PATH", db_path), \
             patch.object(rubrics, "RUBRICS_DIR", clone):
            assert not db_path.exists()
            # Exactly what the FastAPI lifespan does on startup.
            db.init_db()
            rubrics.sync_rubrics_to_db()

            assert db_path.exists()
            loaded = db.list_rubrics()
            assert len(loaded) == 1
            assert loaded[0]["name"] == "Example Hackathon"
            assert len(loaded[0]["categories"]) == 4

    def test_the_shipped_rubric_carries_the_fields_that_drive_the_prompt(self, tmp_path):
        """Categories alone produce an uncalibrated judge that scores everything a 4."""
        clone = self._fresh_clone(tmp_path)
        with patch.object(db, "DB_PATH", tmp_path / "judge.db"), \
             patch.object(rubrics, "RUBRICS_DIR", clone):
            db.init_db()
            rubrics.sync_rubrics_to_db()
            r = db.get_rubric(rubrics.get_default_rubric_id())
            assert r["calibration"].strip()
            assert r["judge_persona"].strip()
            assert r["scale_min"] == 1 and r["scale_max"] == 5

    def test_an_event_created_on_a_fresh_clone_gets_that_rubric(self, tmp_path):
        clone = self._fresh_clone(tmp_path)
        with patch.object(db, "DB_PATH", tmp_path / "judge.db"), \
             patch.object(rubrics, "RUBRICS_DIR", clone):
            db.init_db()
            rubrics.sync_rubrics_to_db()
            event_id = db.create_event("First Event", rubrics.get_default_rubric_id(), "")
            assert db.get_rubric(db.get_event(event_id)["rubric_id"])["name"] == "Example Hackathon"

    def test_restarting_the_server_does_not_duplicate_the_rubric(self, tmp_path):
        """Sync runs on every startup. It is keyed by name and must stay idempotent."""
        clone = self._fresh_clone(tmp_path)
        with patch.object(db, "DB_PATH", tmp_path / "judge.db"), \
             patch.object(rubrics, "RUBRICS_DIR", clone):
            db.init_db()
            rubrics.sync_rubrics_to_db()
            rubrics.sync_rubrics_to_db()
            rubrics.sync_rubrics_to_db()
            assert len(db.list_rubrics()) == 1


class TestRubrics:
    def test_load_yaml(self):
        rubric_path = Path(__file__).parent.parent / "rubrics" / "example-hackathon.yaml"
        if rubric_path.exists():
            data = load_rubric_from_yaml(rubric_path)
            assert data["name"] == "Example Hackathon"
            assert len(data["categories"]) == 4
            assert data["scale_min"] == 1
            assert data["scale_max"] == 5


class TestDeleting:
    """Nothing could be removed before this existed. A misfired recording was
    permanent, and a season of test events sat in the dropdown forever."""

    def _judged(self, team="Team", event_name="Event"):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event(event_name, rubric_id, "")
        sub_id = db.create_submission(team, event_id, rubric_id)
        db.update_submission(sub_id, transcript="t", audio_path="/tmp/x.webm", status="complete")
        db.save_scores(sub_id, [{"category": "A", "score": 4, "rationale": "r"}])
        db.save_review(sub_id, 4.0, "s", "/tmp/x_review.mp3", "spoken")
        db.save_prfaq(sub_id, {"a": 1}, "# md", "model")
        return event_id, sub_id

    def test_deleting_a_submission_takes_its_children(self):
        _, sub_id = self._judged()
        db.delete_submission(sub_id)
        assert db.get_submission(sub_id) is None
        assert db.get_scores(sub_id) == []
        assert db.get_review(sub_id) is None
        assert db.get_prfaq(sub_id) is None

    def test_it_returns_the_audio_to_clean_up(self):
        _, sub_id = self._judged()
        paths = db.delete_submission(sub_id)
        assert "/tmp/x.webm" in paths
        assert "/tmp/x_review.mp3" in paths

    def test_deleting_an_unknown_submission_raises(self):
        with pytest.raises(KeyError):
            db.delete_submission("nope")

    def test_deleting_an_event_takes_every_submission(self):
        event_id, sub_id = self._judged()
        db.delete_event(event_id)
        assert db.get_event(event_id) is None
        assert db.get_submission(sub_id) is None
        assert db.get_scores(sub_id) == []
        assert db.get_prfaq(sub_id) is None

    def test_deleting_an_event_takes_its_finalist_round(self):
        event_id, _ = self._judged()
        rubric_id = db.get_event(event_id)["rubric_id"]
        db.save_finalist_run(event_id, rubric_id, [{"rank": 1, "team_name": "A"}], "why", "/tmp/f.mp3", "x")
        db.delete_event(event_id)
        assert db.get_latest_finalist_run(event_id) is None

    def test_deleting_one_event_leaves_the_others_alone(self):
        keep_event, keep_sub = self._judged(team="Keep", event_name="Keeper")
        drop_event, _ = self._judged(team="Drop", event_name="Doomed")
        db.delete_event(drop_event)
        assert db.get_event(keep_event) is not None
        assert db.get_submission(keep_sub) is not None
        assert len(db.get_scores(keep_sub)) == 1

    def test_deleting_an_unknown_event_raises(self):
        with pytest.raises(KeyError):
            db.delete_event("nope")


class TestSubmissionCounts:
    """The event list used to run one query per event to build these."""

    def test_counts_are_grouped_by_event(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        e1 = db.create_event("One", rubric_id, "")
        e2 = db.create_event("Two", rubric_id, "")
        a = db.create_submission("A", e1, rubric_id)
        db.create_submission("B", e1, rubric_id)
        db.create_submission("C", e2, rubric_id)
        db.update_submission(a, status="complete")

        counts = db.submission_counts_by_event()
        assert counts[e1] == {"submission_count": 2, "completed_count": 1}
        assert counts[e2] == {"submission_count": 1, "completed_count": 0}

    def test_an_event_with_no_submissions_is_simply_absent(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        empty = db.create_event("Empty", rubric_id, "")
        assert empty not in db.submission_counts_by_event()


class TestConnectionsAlwaysClose:
    """Every function used to open a connection and close it on the last line,
    so anything that raised in between leaked the handle. Under WAL a leaked
    handle holds a read transaction open and the log stops checkpointing."""

    def test_the_context_manager_closes_on_success(self):
        with db.connection() as conn:
            conn.execute("SELECT 1")
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_the_context_manager_closes_when_the_body_raises(self):
        with pytest.raises(RuntimeError), db.connection() as conn:
            raise RuntimeError("boom")
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_a_failing_delete_does_not_leak(self):
        # delete_submission raises KeyError before it finishes. The handle it
        # opened first still has to close.
        for _ in range(50):
            with pytest.raises(KeyError):
                db.delete_submission("does-not-exist")
        # 50 leaked handles would show up here.
        assert db.list_events() == []


class TestUpdateColumnsAreNotFreeText:
    """The column has to be interpolated, because SQLite takes no parameter in
    that position. The whitelist is what keeps that safe."""

    def _sub(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event("E", rubric_id, "")
        return db.create_submission("T", event_id, rubric_id), event_id

    def test_a_real_column_still_updates(self):
        sub_id, _ = self._sub()
        db.update_submission(sub_id, status="complete", transcript="hello")
        row = db.get_submission(sub_id)
        assert row["status"] == "complete"
        assert row["transcript"] == "hello"

    def test_an_unknown_submission_column_is_refused(self):
        sub_id, _ = self._sub()
        with pytest.raises(ValueError) as exc:
            db.update_submission(sub_id, nonsense="x")
        assert "nonsense" in str(exc.value)

    def test_an_injection_attempt_is_refused_before_it_reaches_sql(self):
        sub_id, _ = self._sub()
        with pytest.raises(ValueError):
            db.update_submission(sub_id, **{"status = 'x' WHERE 1=1 --": "y"})
        # And the row is untouched.
        assert db.get_submission(sub_id)["status"] == "recording"

    def test_an_unknown_event_column_is_refused(self):
        _, event_id = self._sub()
        with pytest.raises(ValueError):
            db.update_event(event_id, nonsense="x")

    def test_a_real_event_column_still_updates(self):
        _, event_id = self._sub()
        db.update_event(event_id, name="Renamed")
        assert db.get_event(event_id)["name"] == "Renamed"


class TestTheDestructiveMigrationIsRecoverable:
    """init_db drops five tables when it meets a pre-events database. It runs
    at startup, so without a backup an operator opening last season's file
    loses the whole record and is never told."""

    def _old_schema_db(self, path):
        conn = sqlite3.connect(str(path))
        conn.executescript("""
            CREATE TABLE rubrics (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                categories_json TEXT NOT NULL, scale_min INTEGER, scale_max INTEGER,
                calibration TEXT, judge_persona TEXT, created_at TEXT NOT NULL);
            CREATE TABLE events (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                rubric_id TEXT NOT NULL, status TEXT, created_at TEXT NOT NULL);
            -- The old shape: no event_id.
            CREATE TABLE submissions (
                id TEXT PRIMARY KEY, team_name TEXT NOT NULL, rubric_id TEXT NOT NULL,
                audio_path TEXT, transcript TEXT, status TEXT, created_at TEXT NOT NULL);
            CREATE TABLE scores (
                id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, category TEXT,
                score INTEGER, rationale TEXT, created_at TEXT NOT NULL);
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, overall_score REAL,
                summary TEXT, audio_path TEXT, created_at TEXT NOT NULL);
            CREATE TABLE finalist_runs (
                id TEXT PRIMARY KEY, event_id TEXT, rubric_id TEXT,
                top_picks_json TEXT, reasoning TEXT, audio_path TEXT, created_at TEXT NOT NULL);
            INSERT INTO submissions VALUES
                ('s1', 'Last Season', 'r1', NULL, 'their pitch', 'complete', '2026-01-01');
        """)
        conn.commit()
        conn.close()

    def test_the_old_rows_survive_in_a_backup(self, tmp_path):
        old = tmp_path / "judge.db"
        self._old_schema_db(old)
        with patch.object(db, "DB_PATH", old):
            db.init_db()

        backups = list(tmp_path.glob("judge.pre-migration-*.db"))
        assert len(backups) == 1, "the migration left no backup"

        conn = sqlite3.connect(str(backups[0]))
        rows = conn.execute("SELECT team_name, transcript FROM submissions").fetchall()
        conn.close()
        assert rows == [("Last Season", "their pitch")]

    def test_the_migration_still_produces_the_new_schema(self, tmp_path):
        old = tmp_path / "judge.db"
        self._old_schema_db(old)
        with patch.object(db, "DB_PATH", old):
            db.init_db()
            rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
            event_id = db.create_event("E", rubric_id, "")
            sub_id = db.create_submission("New Team", event_id, rubric_id)
            assert db.get_submission(sub_id)["event_id"] == event_id

    def test_a_current_database_is_not_backed_up_or_touched(self, tmp_path):
        current = tmp_path / "judge.db"
        with patch.object(db, "DB_PATH", current):
            db.init_db()
            rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
            event_id = db.create_event("E", rubric_id, "")
            sub_id = db.create_submission("Keep Me", event_id, rubric_id)
            db.init_db()  # restart
            assert db.get_submission(sub_id)["team_name"] == "Keep Me"
        assert list(tmp_path.glob("*pre-migration*")) == []

    def test_the_backup_is_announced(self, tmp_path, caplog):
        old = tmp_path / "judge.db"
        self._old_schema_db(old)
        with patch.object(db, "DB_PATH", old), caplog.at_level("WARNING"):
            db.init_db()
        assert "pre-migration" in caplog.text
        assert "dropped" in caplog.text


class TestTheDefaultRubric:
    """SPEC.md R2. An event created without a named rubric takes the most
    recently created one. On a fresh install there is only one rubric, so this
    never surfaces until a second is added, which is exactly when it matters."""

    def test_the_newest_rubric_wins(self):
        db.create_rubric("First", [{"name": "A", "description": "a", "weight": 1}])
        newest = db.create_rubric("Second", [{"name": "B", "description": "b", "weight": 1}])
        assert rubrics.get_default_rubric_id() == newest

    def test_a_single_rubric_is_the_default(self):
        only = db.create_rubric("Only", [{"name": "A", "description": "a", "weight": 1}])
        assert rubrics.get_default_rubric_id() == only

    def test_an_event_created_without_one_gets_it(self):
        db.create_rubric("Old", [{"name": "A", "description": "a", "weight": 1}])
        newest = db.create_rubric("New", [{"name": "B", "description": "b", "weight": 1}])
        event_id = db.create_event("E", rubrics.get_default_rubric_id(), "")
        assert db.get_event(event_id)["rubric_id"] == newest


class TestWhatABackupActuallyCovers:
    """SPEC.md R30.

    The README used to tell operators that copying judge.db was the full
    history. It is not: every recording lives in audio_recordings/ and the
    database refers to them by absolute path. Following that instruction and
    then wiping the machine loses every pitch, while the restored database
    still shows an audio player for each one.
    """

    def _judged_event(self, audio_dir):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event("Backed Up", rubric_id, "")
        sub_id = db.create_submission("Recorded Team", event_id, rubric_id)
        pitch = audio_dir / f"{sub_id}.webm"
        pitch.write_bytes(b"pitch audio")
        db.update_submission(sub_id, audio_path=str(pitch), transcript="what they said",
                             status="complete")
        db.save_scores(sub_id, [{"category": "A", "score": 4, "rationale": "why"}])
        db.save_review(sub_id, 4.0, "summary", str(audio_dir / f"{sub_id}_review.mp3"), "spoken")
        db.save_prfaq(sub_id, {"one_liner": "x"}, "# doc", "model")
        return sub_id

    def test_the_database_carries_every_score_transcript_review_and_prfaq(self, tmp_path):
        audio = tmp_path / "audio"
        audio.mkdir()
        sub_id = self._judged_event(audio)

        copy = tmp_path / "restored.db"
        with db.connection() as source, db.connection_to(copy) as target:
            source.backup(target)

        with patch.object(db, "DB_PATH", copy):
            sub = db.get_submission(sub_id)
            assert sub["transcript"] == "what they said"
            assert len(db.get_scores(sub_id)) == 1
            assert db.get_review(sub_id)["overall_score"] == 4.0
            assert db.get_prfaq(sub_id)["markdown"] == "# doc"

    def test_the_database_carries_no_audio(self, tmp_path):
        audio = tmp_path / "audio"
        audio.mkdir()
        sub_id = self._judged_event(audio)
        assert b"pitch audio" not in db.DB_PATH.read_bytes()
        # Only a path to it, which is why the directory has to be copied too.
        assert db.get_submission(sub_id)["audio_path"].endswith(".webm")

    def test_the_recorded_path_is_absolute(self, tmp_path):
        """So a restore into a different directory breaks every reference."""
        audio = tmp_path / "audio"
        audio.mkdir()
        sub_id = self._judged_event(audio)
        assert Path(db.get_submission(sub_id)["audio_path"]).is_absolute()


class TestRejudgingReplaces:
    """SPEC.md R31.

    Reviews and PRFAQs are unique on submission and replace on a second write.
    Scores were the only one of the three left as a plain insert, so re-judging
    a team appended a second set: eight rows for a four-category rubric, all
    eight rendered. The overall score survived because numerator and
    denominator doubled together, which is why it went unnoticed.
    """

    def _submission(self):
        rubric_id = db.create_rubric("R", [
            {"name": "Impact", "description": "i", "weight": 1},
            {"name": "Craft", "description": "c", "weight": 1},
        ])
        event_id = db.create_event("E", rubric_id, "")
        return db.create_submission("Team", event_id, rubric_id)

    def test_a_second_scoring_replaces_the_first(self):
        sub_id = self._submission()
        db.save_scores(sub_id, [
            {"category": "Impact", "score": 2, "rationale": "first run"},
            {"category": "Craft", "score": 2, "rationale": "first run"},
        ])
        db.save_scores(sub_id, [
            {"category": "Impact", "score": 5, "rationale": "second run"},
            {"category": "Craft", "score": 4, "rationale": "second run"},
        ])
        scores = db.get_scores(sub_id)
        assert len(scores) == 2
        assert {s["category"]: s["score"] for s in scores} == {"Impact": 5, "Craft": 4}
        assert all(s["rationale"] == "second run" for s in scores)

    def test_a_third_run_does_not_accumulate(self):
        sub_id = self._submission()
        for n in range(3):
            db.save_scores(sub_id, [{"category": "Impact", "score": n, "rationale": str(n)}])
        assert len(db.get_scores(sub_id)) == 1

    def test_another_submission_is_untouched(self):
        keep = self._submission()
        other = self._submission()
        db.save_scores(keep, [{"category": "Impact", "score": 3, "rationale": "keep"}])
        db.save_scores(other, [{"category": "Impact", "score": 1, "rationale": "other"}])
        db.save_scores(other, [{"category": "Impact", "score": 2, "rationale": "again"}])
        assert len(db.get_scores(keep)) == 1
        assert db.get_scores(keep)[0]["score"] == 3

    def test_the_review_already_replaced_and_still_does(self):
        sub_id = self._submission()
        db.save_review(sub_id, 2.0, "first", "/tmp/a.mp3", "spoken one")
        db.save_review(sub_id, 4.5, "second", "/tmp/b.mp3", "spoken two")
        review = db.get_review(sub_id)
        assert review["overall_score"] == 4.5
        assert review["summary"] == "second"


class TestStatusIsOneOfOurs:
    """SPEC.md R34. The value is constrained; the order is not, and the spec
    says so rather than implying a state machine that does not exist."""

    def _sub(self):
        rubric_id = db.create_rubric("R", [{"name": "A", "description": "a", "weight": 1}])
        event_id = db.create_event("E", rubric_id, "")
        return db.create_submission("T", event_id, rubric_id)

    @pytest.mark.parametrize(
        "status", ["recording", "transcribing", "scoring", "speaking", "complete", "error"]
    )
    def test_every_status_the_pipeline_uses_is_accepted(self, status):
        sub_id = self._sub()
        db.update_submission(sub_id, status=status)
        assert db.get_submission(sub_id)["status"] == status

    def test_an_undefined_status_is_refused(self):
        sub_id = self._sub()
        with pytest.raises(ValueError) as exc:
            db.update_submission(sub_id, status="finished")
        assert "finished" in str(exc.value)
        assert db.get_submission(sub_id)["status"] == "recording"

    def test_the_message_names_the_valid_ones(self):
        sub_id = self._sub()
        with pytest.raises(ValueError) as exc:
            db.update_submission(sub_id, status="")
        assert "complete" in str(exc.value)

    def test_the_pipeline_statuses_and_the_constant_agree(self):
        """The constant is the definition. If server.py grows a seventh status
        without adding it here, this fails rather than the event does."""
        import re
        source = (Path(__file__).parent.parent / "server.py").read_text()
        used = set(re.findall(r'status="([a-z]+)"', source))
        assert used <= db.SUBMISSION_STATUSES, f"server.py writes {used - db.SUBMISSION_STATUSES}"


class TestARubricCanDeclareItselfTheDefault:
    """SPEC.md R42.

    Without a declared default the newest rubric wins, which is invisible until
    the day somebody adds a second one and an event is quietly judged against
    the wrong thing. The flag is opt-in, so nothing changes for an install with
    one rubric.
    """

    def _dir(self, tmp_path, files):
        d = tmp_path / "rubrics"
        d.mkdir()
        for name, body in files.items():
            (d / name).write_text(body)
        return d

    def _rubric(self, name, default=False):
        flag = "default: true\n" if default else ""
        return f'name: "{name}"\n{flag}categories:\n  - name: "A"\n    description: "a"\n'

    def test_the_declared_default_wins_over_the_newest(self, tmp_path, monkeypatch):
        d = self._dir(tmp_path, {
            "a.yaml": self._rubric("Chosen", default=True),
            "b.yaml": self._rubric("Newer"),
        })
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "j.db")
        monkeypatch.setattr(rubrics, "RUBRICS_DIR", d)
        db.init_db()
        rubrics.sync_rubrics_to_db()
        assert db.get_rubric(rubrics.get_default_rubric_id())["name"] == "Chosen"

    def test_without_a_flag_the_newest_still_wins(self, tmp_path, monkeypatch):
        """R2 is unchanged for anyone who does not opt in."""
        d = self._dir(tmp_path, {"a.yaml": self._rubric("One"), "b.yaml": self._rubric("Two")})
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "j.db")
        monkeypatch.setattr(rubrics, "RUBRICS_DIR", d)
        db.init_db()
        rubrics.sync_rubrics_to_db()
        newest = db.list_rubrics()[0]["id"]
        assert rubrics.get_default_rubric_id() == newest

    def test_a_flag_pointing_at_a_rubric_that_failed_to_load_falls_back(self, tmp_path, monkeypatch):
        d = self._dir(tmp_path, {"a.yaml": self._rubric("Present")})
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "j.db")
        monkeypatch.setattr(rubrics, "RUBRICS_DIR", d)
        db.init_db()
        rubrics.sync_rubrics_to_db()
        # Declared after the sync, so nothing in the database matches it.
        (d / "b.yaml").write_text(self._rubric("Never Synced", default=True))
        assert db.get_rubric(rubrics.get_default_rubric_id())["name"] == "Present"

    def test_the_shipped_rubric_does_not_claim_the_default(self, tmp_path, monkeypatch):
        """Otherwise adding your own rubric would still get ours."""
        import yaml
        shipped = Path(__file__).parent.parent / "rubrics" / "example-hackathon.yaml"
        assert not yaml.safe_load(shipped.read_text()).get("default")

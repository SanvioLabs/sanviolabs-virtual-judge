"""Tests for the database and rubric modules."""

import json
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
        with pytest.raises(RuntimeError):
            with db.connection() as conn:
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

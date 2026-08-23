"""SPEC.md R47. Purging old material.

Recordings are people's voices. Keeping them forever because nothing deletes
them is not a decision anybody made, and a tool that holds participant data has
to make removing it easy.

Deliberately not automatic. Deleting a recording somebody still needs, on a
timer they did not set, is worse than a directory that grows. This is a command
the operator runs, it names what it will remove before removing it, and it
refuses to guess.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

import server
from judge import db


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "AUDIO_DIR", tmp_path / "audio")
    server.AUDIO_DIR.mkdir()
    with patch.object(db, "DB_PATH", tmp_path / "test.db"):
        db.init_db()
        yield


def _event_aged(days: int, name="Old Event"):
    rubric_id = db.create_rubric(f"R{days}{name}", [{"name": "A", "description": "a", "weight": 1}])
    event_id = db.create_event(name, rubric_id, "")
    sub_id = db.create_submission(f"Team {name}", event_id, rubric_id)
    audio = server.AUDIO_DIR / f"{sub_id}.webm"
    audio.write_bytes(b"a voice")
    db.update_submission(sub_id, audio_path=str(audio), transcript="what they said",
                         status="complete")
    when = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with db.connection() as conn:
        conn.execute("UPDATE events SET created_at = ? WHERE id = ?", (when, event_id))
        conn.commit()
    return event_id, sub_id, audio


class TestItNamesWhatItWouldRemove:
    def test_a_dry_run_reports_and_deletes_nothing(self):
        event_id, _sub_id, audio = _event_aged(90)
        found = server.purge_older_than(30, dry_run=True)
        assert [e["name"] for e in found] == ["Old Event"]
        assert db.get_event(event_id) is not None
        assert audio.is_file()

    def test_it_counts_the_recordings_at_stake(self):
        _event_aged(90)
        found = server.purge_older_than(30, dry_run=True)
        assert found[0]["submissions"] == 1


class TestItRemovesOnlyWhatIsOldEnough:
    def test_an_old_event_goes(self):
        event_id, sub_id, audio = _event_aged(90)
        server.purge_older_than(30)
        assert db.get_event(event_id) is None
        assert db.get_submission(sub_id) is None
        assert not audio.exists()

    def test_a_recent_event_stays(self):
        event_id, _sub_id, audio = _event_aged(5, name="Recent")
        server.purge_older_than(30)
        assert db.get_event(event_id) is not None
        assert audio.is_file()

    def test_the_boundary_is_not_guessed_at(self):
        """An event exactly at the cutoff is kept, because deleting on a
        rounding error is the failure that loses somebody's data."""
        event_id, _, _ = _event_aged(30, name="Exactly")
        server.purge_older_than(30)
        assert db.get_event(event_id) is not None

    def test_it_reports_what_it_removed(self):
        _event_aged(90, name="Gone One")
        _event_aged(91, name="Gone Two")
        _event_aged(1, name="Kept")
        removed = server.purge_older_than(30)
        assert {e["name"] for e in removed} == {"Gone One", "Gone Two"}


class TestItRefusesToGuess:
    @pytest.mark.parametrize("days", [0, -1, -30])
    def test_a_nonsense_age_is_refused(self, days):
        with pytest.raises(ValueError):
            server.purge_older_than(days)

    def test_zero_would_delete_everything_and_is_refused(self):
        _event_aged(0, name="Today")
        with pytest.raises(ValueError):
            server.purge_older_than(0)
        assert len(db.list_events()) == 1

"""Full API test suite — covers all endpoints, happy paths, and error cases."""

import csv
import io
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

import server
from judge import db


# --- Fixtures ---

@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    """Use a temporary database for each test."""
    test_db = tmp_path / "test.db"
    with patch.object(db, "DB_PATH", test_db):
        db.init_db()
        # Seed a rubric and event
        rubric_id = db.create_rubric(
            name="Test Rubric",
            categories=[
                {"name": "Impact", "description": "Real-world impact", "weight": 1.0},
                {"name": "Innovation", "description": "Creative approach", "weight": 2.0},
            ],
            scale_min=1,
            scale_max=5,
            calibration="Score fairly.",
            judge_persona="You are a judge.",
        )
        db.create_event("Test Hackathon", rubric_id, "A test event")
        yield test_db


@pytest.fixture
def app():
    """Create the FastAPI app with mocked rubric sync."""
    with patch("server.sync_rubrics_to_db"):
        from server import app as _app
        return _app


@pytest.fixture
async def client(app):
    """Async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _get_event_id(client) -> str:
    events = (await client.get("/api/events")).json()
    return events[0]["id"]


async def _create_submission(client, team_name="Team Test") -> dict:
    event_id = await _get_event_id(client)
    res = await client.post("/api/submissions", json={"team_name": team_name, "event_id": event_id})
    return res.json()


async def _create_judged_submission(client, mock_transcribe, mock_score, mock_speak, team_name="Team Judged"):
    """Create a fully judged submission (with mocked externals)."""
    mock_transcribe.return_value = f"Pitch from {team_name}: We built something great."
    mock_score.return_value = {
        "scores": [
            {"category": "Impact", "score": 4, "rationale": "Solves a real problem."},
            {"category": "Innovation", "score": 3, "rationale": "Decent approach."},
        ],
        "summary": f"{team_name} delivered a solid submission.",
    }
    mock_speak.return_value = Path("/tmp/fake.mp3")

    sub = await _create_submission(client, team_name)
    await client.post(
        f"/api/submissions/{sub['id']}/audio",
        files={"file": ("test.webm", b"fake audio data", "audio/webm")},
    )
    res = await client.post(f"/api/submissions/{sub['id']}/judge")
    return res.json()


# --- Health ---

class TestHealth:
    async def test_health_returns_status(self, client):
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert "keys_configured" in data
        assert "rubrics_loaded" in data
        assert "events_count" in data

    async def test_health_reports_key_status(self, client):
        res = await client.get("/api/health")
        data = res.json()
        # Keys are booleans
        for key in ["openrouter", "elevenlabs"]:
            assert isinstance(data["keys_configured"][key], bool)
        # Placeholder values from .env.example must not read as configured
        assert data["keys_configured"].keys() == {"openrouter", "elevenlabs"}


# --- Events ---

class TestEvents:
    async def test_list_events(self, client):
        res = await client.get("/api/events")
        assert res.status_code == 200
        events = res.json()
        assert len(events) >= 1
        assert events[0]["name"] == "Test Hackathon"
        assert events[0]["submission_count"] == 0
        assert events[0]["completed_count"] == 0

    async def test_create_event(self, client):
        res = await client.post("/api/events", json={"name": "New Hackathon", "description": "A new one"})
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "New Hackathon"
        assert data["id"]
        assert data["rubric_id"]

    async def test_create_event_with_rubric(self, client):
        rubrics = (await client.get("/api/rubrics")).json()
        rubric_id = rubrics[0]["id"]

        res = await client.post("/api/events", json={"name": "Custom Rubric Event", "rubric_id": rubric_id})
        assert res.status_code == 200
        assert res.json()["rubric_id"] == rubric_id

    async def test_get_event(self, client):
        event_id = await _get_event_id(client)
        res = await client.get(f"/api/events/{event_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Test Hackathon"
        assert data["rubric"] is not None
        assert data["submission_count"] == 0

    async def test_get_event_not_found(self, client):
        res = await client.get("/api/events/nonexistent-id")
        assert res.status_code == 404

    async def test_events_track_submission_counts(self, client):
        event_id = await _get_event_id(client)
        await client.post("/api/submissions", json={"team_name": "A", "event_id": event_id})
        await client.post("/api/submissions", json={"team_name": "B", "event_id": event_id})

        events = (await client.get("/api/events")).json()
        event = next(e for e in events if e["id"] == event_id)
        assert event["submission_count"] == 2
        assert event["completed_count"] == 0


# --- Rubrics ---

class TestRubrics:
    async def test_list_rubrics(self, client):
        res = await client.get("/api/rubrics")
        assert res.status_code == 200
        rubrics = res.json()
        assert len(rubrics) >= 1
        assert "categories" in rubrics[0]
        assert rubrics[0]["scale_min"] == 1
        assert rubrics[0]["scale_max"] == 5


# --- Submissions ---

class TestSubmissions:
    async def test_create_submission(self, client):
        sub = await _create_submission(client, "Team Flux")
        assert sub["team_name"] == "Team Flux"
        assert sub["status"] == "recording"
        assert sub["id"]
        assert sub["event_id"]

    async def test_create_submission_bad_event(self, client):
        res = await client.post("/api/submissions", json={
            "team_name": "Team Bad",
            "event_id": "nonexistent",
        })
        assert res.status_code == 404

    async def test_create_submission_missing_team_name(self, client):
        event_id = await _get_event_id(client)
        res = await client.post("/api/submissions", json={"event_id": event_id})
        assert res.status_code == 422  # Validation error

    async def test_upload_audio(self, client):
        sub = await _create_submission(client, "Team Audio")
        res = await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("recording.webm", b"fake audio content here", "audio/webm")},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "uploaded"

    async def test_upload_audio_not_found(self, client):
        res = await client.post(
            "/api/submissions/nonexistent/audio",
            files={"file": ("test.webm", b"data", "audio/webm")},
        )
        assert res.status_code == 404

    async def test_get_submission(self, client):
        sub = await _create_submission(client, "Team Get")
        res = await client.get(f"/api/submissions/{sub['id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["team_name"] == "Team Get"
        assert data["scores"] == []
        assert data["review"] is None

    async def test_get_submission_not_found(self, client):
        res = await client.get("/api/submissions/nonexistent")
        assert res.status_code == 404

    async def test_list_event_submissions(self, client):
        event_id = await _get_event_id(client)
        await client.post("/api/submissions", json={"team_name": "A", "event_id": event_id})
        await client.post("/api/submissions", json={"team_name": "B", "event_id": event_id})
        await client.post("/api/submissions", json={"team_name": "C", "event_id": event_id})

        res = await client.get(f"/api/events/{event_id}/submissions")
        assert res.status_code == 200
        subs = res.json()
        assert len(subs) == 3
        assert all("scores" in s for s in subs)
        assert all("review" in s for s in subs)

    async def test_submissions_isolated_between_events(self, client):
        """Submissions in one event don't appear in another."""
        # Create two fresh events
        res1 = await client.post("/api/events", json={"name": "Event Alpha"})
        event_a = res1.json()["id"]
        res2 = await client.post("/api/events", json={"name": "Event Beta"})
        event_b = res2.json()["id"]

        await client.post("/api/submissions", json={"team_name": "Team A", "event_id": event_a})
        await client.post("/api/submissions", json={"team_name": "Team X", "event_id": event_b})
        await client.post("/api/submissions", json={"team_name": "Team Y", "event_id": event_b})

        subs_a = (await client.get(f"/api/events/{event_a}/submissions")).json()
        subs_b = (await client.get(f"/api/events/{event_b}/submissions")).json()

        assert len(subs_a) == 1
        assert subs_a[0]["team_name"] == "Team A"
        assert len(subs_b) == 2


# --- Judging Pipeline ---

class TestJudging:
    async def test_judge_without_audio_returns_400(self, client):
        sub = await _create_submission(client, "No Audio Team")
        res = await client.post(f"/api/submissions/{sub['id']}/judge")
        assert res.status_code == 400
        assert "No audio" in res.json()["detail"]

    async def test_judge_nonexistent_submission(self, client):
        res = await client.post("/api/submissions/fake-id/judge")
        assert res.status_code == 404

    @patch("server.transcribe_audio")
    @patch("server.score_submission")
    @patch("server.speak")
    async def test_full_judge_pipeline(self, mock_speak, mock_score, mock_transcribe, client):
        """End-to-end: create → upload → judge → verify result."""
        mock_transcribe.return_value = "We built an AI tool that helps doctors find research papers faster."
        mock_score.return_value = {
            "scores": [
                {"category": "Impact", "score": 4, "rationale": "Solves a real problem for doctors."},
                {"category": "Innovation", "score": 3, "rationale": "RAG is common, but the UX is fresh."},
            ],
            "summary": "Solid submission with real-world applicability.",
        }
        mock_speak.return_value = Path("/tmp/fake_review.mp3")

        sub = await _create_submission(client, "Team Pipeline")
        await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("test.webm", b"fake audio data", "audio/webm")},
        )

        res = await client.post(f"/api/submissions/{sub['id']}/judge")
        assert res.status_code == 200
        data = res.json()

        # Verify response structure
        assert data["status"] == "complete"
        assert data["transcript"] == "We built an AI tool that helps doctors find research papers faster."
        assert len(data["scores"]) == 2
        assert data["scores"][0]["category"] == "Impact"
        assert data["scores"][0]["score"] == 4
        assert data["summary"] == "Solid submission with real-world applicability."
        assert "/audio/" in data["review_audio"]

        # Verify weighted score (Impact weight=1, Innovation weight=2)
        # (4*1 + 3*2) / (1+2) = 10/3 = 3.33
        assert data["overall_score"] == pytest.approx(3.33, abs=0.01)

        # Verify all external services called
        mock_transcribe.assert_called_once()
        mock_score.assert_called_once()
        mock_speak.assert_called_once()

    @patch("server.transcribe_audio")
    @patch("server.score_submission")
    @patch("server.speak")
    async def test_judge_updates_submission_status(self, mock_speak, mock_score, mock_transcribe, client):
        """Submission status should be 'complete' after successful judging."""
        mock_transcribe.return_value = "Hello world."
        mock_score.return_value = {
            "scores": [
                {"category": "Impact", "score": 3, "rationale": "OK."},
                {"category": "Innovation", "score": 3, "rationale": "OK."},
            ],
            "summary": "Average.",
        }
        mock_speak.return_value = Path("/tmp/fake.mp3")

        sub = await _create_submission(client, "Team Status")
        await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("test.webm", b"audio", "audio/webm")},
        )
        await client.post(f"/api/submissions/{sub['id']}/judge")

        # Verify final state
        detail = (await client.get(f"/api/submissions/{sub['id']}")).json()
        assert detail["status"] == "complete"
        assert detail["transcript"] == "Hello world."
        assert len(detail["scores"]) == 2
        assert detail["review"]["overall_score"] == 3.0

    @patch("server.transcribe_audio", side_effect=KeyError("OPENROUTER_API_KEY"))
    async def test_judge_missing_openrouter_key_on_transcribe(self, mock_transcribe, client):
        """Returns helpful error when OPENROUTER_API_KEY is missing at transcription."""
        sub = await _create_submission(client, "Team NoKey")
        await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("test.webm", b"audio", "audio/webm")},
        )
        res = await client.post(f"/api/submissions/{sub['id']}/judge")
        assert res.status_code == 500
        assert "OPENROUTER_API_KEY" in res.json()["detail"]

    @patch("server.transcribe_audio", return_value="Some transcript")
    @patch("server.score_submission", side_effect=KeyError("OPENROUTER_API_KEY"))
    async def test_judge_missing_openrouter_key_on_score(self, mock_score, mock_transcribe, client):
        """Returns helpful error when OPENROUTER_API_KEY is missing at scoring."""
        sub = await _create_submission(client, "Team NoScoreKey")
        await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("test.webm", b"audio", "audio/webm")},
        )
        res = await client.post(f"/api/submissions/{sub['id']}/judge")
        assert res.status_code == 500
        assert "OPENROUTER_API_KEY" in res.json()["detail"]

    @patch("server.transcribe_audio", return_value="Transcript")
    @patch("server.score_submission")
    @patch("server.speak", side_effect=KeyError("ELEVENLABS_API_KEY"))
    async def test_judge_missing_elevenlabs_key(self, mock_speak, mock_score, mock_transcribe, client):
        """Returns helpful error when ELEVENLABS_API_KEY is missing."""
        mock_score.return_value = {
            "scores": [{"category": "Impact", "score": 3, "rationale": "OK."}, {"category": "Innovation", "score": 3, "rationale": "OK."}],
            "summary": "Fine.",
        }
        sub = await _create_submission(client, "Team NoEL")
        await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("test.webm", b"audio", "audio/webm")},
        )
        res = await client.post(f"/api/submissions/{sub['id']}/judge")
        assert res.status_code == 500
        assert "ELEVENLABS_API_KEY" in res.json()["detail"]

    @patch("server.transcribe_audio", side_effect=RuntimeError("transcription model timeout"))
    async def test_judge_transcription_failure(self, mock_transcribe, client):
        """Sets status to 'error' when transcription fails."""
        sub = await _create_submission(client, "Team Fail")
        await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("test.webm", b"audio", "audio/webm")},
        )
        res = await client.post(f"/api/submissions/{sub['id']}/judge")
        assert res.status_code == 500
        assert "Transcription failed" in res.json()["detail"]

        # Check status was set to error
        detail = (await client.get(f"/api/submissions/{sub['id']}")).json()
        assert detail["status"] == "error"


# --- Finalist ---

class TestFinalist:
    async def test_finalist_requires_3_submissions(self, client):
        event_id = await _get_event_id(client)
        res = await client.post(f"/api/events/{event_id}/finalist")
        assert res.status_code == 400
        assert "at least 3" in res.json()["detail"]

    async def test_finalist_event_not_found(self, client):
        res = await client.post("/api/events/fake-event/finalist")
        assert res.status_code == 404

    @patch("server.transcribe_audio")
    @patch("server.score_submission")
    @patch("server.speak")
    @patch("server.run_finalist_round")
    async def test_finalist_full_flow(self, mock_finalist, mock_speak, mock_score, mock_transcribe, client):
        """Create 3 judged submissions, run finalist, verify result."""
        mock_transcribe.return_value = "We built something."
        mock_score.return_value = {
            "scores": [
                {"category": "Impact", "score": 4, "rationale": "Good."},
                {"category": "Innovation", "score": 3, "rationale": "OK."},
            ],
            "summary": "Solid.",
        }
        mock_speak.return_value = Path("/tmp/fake.mp3")
        mock_finalist.return_value = {
            "top_picks": [
                {"rank": 1, "team_name": "Alpha", "reasoning": "Best overall execution."},
                {"rank": 2, "team_name": "Beta", "reasoning": "Most innovative approach."},
                {"rank": 3, "team_name": "Gamma", "reasoning": "Strongest pitch delivery."},
            ],
            "reasoning": "All three teams showed exceptional work. Alpha won on completeness.",
        }

        event_id = await _get_event_id(client)

        # Create and judge 3 teams
        for name in ["Alpha", "Beta", "Gamma"]:
            sub = (await client.post("/api/submissions", json={"team_name": name, "event_id": event_id})).json()
            await client.post(f"/api/submissions/{sub['id']}/audio", files={"file": ("t.webm", b"audio", "audio/webm")})
            await client.post(f"/api/submissions/{sub['id']}/judge")

        # Run finalist
        res = await client.post(f"/api/events/{event_id}/finalist")
        assert res.status_code == 200
        data = res.json()
        assert len(data["top_picks"]) == 3
        assert data["top_picks"][0]["team_name"] == "Alpha"
        assert data["top_picks"][0]["rank"] == 1
        assert "reasoning" in data
        assert "/audio/" in data["audio"]

    @patch("server.transcribe_audio")
    @patch("server.score_submission")
    @patch("server.speak")
    @patch("server.run_finalist_round")
    async def test_get_finalist_latest(self, mock_finalist, mock_speak, mock_score, mock_transcribe, client):
        """Can retrieve saved finalist results."""
        mock_transcribe.return_value = "Pitch."
        mock_score.return_value = {
            "scores": [{"category": "Impact", "score": 4, "rationale": "G."}, {"category": "Innovation", "score": 4, "rationale": "G."}],
            "summary": "Good.",
        }
        mock_speak.return_value = Path("/tmp/f.mp3")
        mock_finalist.return_value = {
            "top_picks": [
                {"rank": 1, "team_name": "W1", "reasoning": "R1."},
                {"rank": 2, "team_name": "W2", "reasoning": "R2."},
                {"rank": 3, "team_name": "W3", "reasoning": "R3."},
            ],
            "reasoning": "Overall.",
        }

        event_id = await _get_event_id(client)
        for name in ["W1", "W2", "W3"]:
            sub = (await client.post("/api/submissions", json={"team_name": name, "event_id": event_id})).json()
            await client.post(f"/api/submissions/{sub['id']}/audio", files={"file": ("t.webm", b"a", "audio/webm")})
            await client.post(f"/api/submissions/{sub['id']}/judge")

        await client.post(f"/api/events/{event_id}/finalist")

        # Get latest
        res = await client.get(f"/api/events/{event_id}/finalist/latest")
        assert res.status_code == 200
        data = res.json()
        assert len(data["top_picks"]) == 3

    async def test_get_finalist_latest_none(self, client):
        event_id = await _get_event_id(client)
        res = await client.get(f"/api/events/{event_id}/finalist/latest")
        assert res.status_code == 404

    @patch("server.transcribe_audio", return_value="A pitch.")
    @patch("server.score_submission")
    @patch("server.speak")
    @patch("server.run_finalist_round")
    async def test_latest_matches_the_shape_the_ui_renders(
        self, mock_finalist, mock_speak, mock_score, mock_transcribe, client
    ):
        """GET must return what POST returns, so the UI has one render path.

        The stored row carries a filesystem `audio_path`; the UI needs a served
        `audio` URL. Returning the raw row left the audio element broken when
        results were loaded rather than freshly run.
        """
        mock_score.return_value = {
            "scores": [
                {"category": "Impact", "score": 4, "rationale": "Good."},
                {"category": "Innovation", "score": 4, "rationale": "Good."},
            ],
            "summary": "Solid.",
        }
        mock_finalist.return_value = {
            "top_picks": [
                {"rank": 1, "team_name": "S1", "reasoning": "First."},
                {"rank": 2, "team_name": "S2", "reasoning": "Second."},
                {"rank": 3, "team_name": "S3", "reasoning": "Third."},
            ],
            "reasoning": "Strong cohort.",
            "spoken_announcement": "What a cohort. Congratulations to everyone.",
        }
        event_id = await _get_event_id(client)
        for name in ["S1", "S2", "S3"]:
            sub = (await client.post("/api/submissions", json={"team_name": name, "event_id": event_id})).json()
            await client.post(f"/api/submissions/{sub['id']}/audio", files={"file": ("t.webm", b"a", "audio/webm")})
            await client.post(f"/api/submissions/{sub['id']}/judge")

        posted = (await client.post(f"/api/events/{event_id}/finalist")).json()
        fetched = (await client.get(f"/api/events/{event_id}/finalist/latest")).json()

        assert set(posted) == set(fetched)
        assert fetched["top_picks"] == posted["top_picks"]
        assert fetched["reasoning"] == posted["reasoning"]
        assert fetched["spoken_announcement"] == posted["spoken_announcement"]
        # A served URL, never a filesystem path.
        assert fetched["audio"] is None or fetched["audio"].startswith("/audio/")
        assert "audio_path" not in fetched


# --- Export ---

class TestExport:
    @patch("server.transcribe_audio")
    @patch("server.score_submission")
    @patch("server.speak")
    async def test_export_csv(self, mock_speak, mock_score, mock_transcribe, client):
        """CSV export includes headers and submission data."""
        mock_transcribe.return_value = "Pitch text."
        mock_score.return_value = {
            "scores": [
                {"category": "Impact", "score": 5, "rationale": "Excellent."},
                {"category": "Innovation", "score": 4, "rationale": "Novel."},
            ],
            "summary": "Great work.",
        }
        mock_speak.return_value = Path("/tmp/f.mp3")

        event_id = await _get_event_id(client)
        sub = (await client.post("/api/submissions", json={"team_name": "CSV Team", "event_id": event_id})).json()
        await client.post(f"/api/submissions/{sub['id']}/audio", files={"file": ("t.webm", b"a", "audio/webm")})
        await client.post(f"/api/submissions/{sub['id']}/judge")

        res = await client.get(f"/api/events/{event_id}/export/csv")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")

        # Parsed as a real CSV, not as a JSON string. This used to come back
        # JSON-encoded, which opens in a spreadsheet as one cell of nonsense.
        rows = list(csv.reader(io.StringIO(res.text)))
        assert rows[0][0] == "Team"
        assert any(r and r[0] == "CSV Team" for r in rows)
        assert "Impact" in rows[0]
        assert "Innovation" in rows[0]

    @patch("server.transcribe_audio")
    @patch("server.score_submission")
    @patch("server.speak")
    async def test_export_json(self, mock_speak, mock_score, mock_transcribe, client):
        """JSON export includes structured event data."""
        mock_transcribe.return_value = "Pitch."
        mock_score.return_value = {
            "scores": [
                {"category": "Impact", "score": 4, "rationale": "Good."},
                {"category": "Innovation", "score": 3, "rationale": "OK."},
            ],
            "summary": "Solid.",
        }
        mock_speak.return_value = Path("/tmp/f.mp3")

        event_id = await _get_event_id(client)
        sub = (await client.post("/api/submissions", json={"team_name": "JSON Team", "event_id": event_id})).json()
        await client.post(f"/api/submissions/{sub['id']}/audio", files={"file": ("t.webm", b"a", "audio/webm")})
        await client.post(f"/api/submissions/{sub['id']}/judge")

        res = await client.get(f"/api/events/{event_id}/export/json")
        assert res.status_code == 200
        data = res.json()
        assert data["event"] == "Test Hackathon"
        assert "rubric" in data
        assert len(data["submissions"]) == 1
        assert data["submissions"][0]["team_name"] == "JSON Team"
        assert data["submissions"][0]["overall_score"] is not None

    async def test_export_csv_event_not_found(self, client):
        res = await client.get("/api/events/fake/export/csv")
        assert res.status_code == 404

    async def test_export_json_event_not_found(self, client):
        res = await client.get("/api/events/fake/export/json")
        assert res.status_code == 404

    async def test_export_empty_event(self, client):
        """Export works with zero submissions (just headers)."""
        event_id = await _get_event_id(client)
        res = await client.get(f"/api/events/{event_id}/export/csv")
        assert res.status_code == 200
        rows = list(csv.reader(io.StringIO(res.text)))
        assert rows[0][0] == "Team"


# --- Serving ---

class TestServing:
    async def test_index_returns_html(self, client):
        res = await client.get("/")
        assert res.status_code == 200
        assert "Virtual Judge" in res.text
        assert "text/html" in res.headers["content-type"]


# --- Spoken review ---

class TestSpeechFormatting:
    """The judge writes its own ~1 minute spoken verdict for the live room.

    Assembling one here from score fragments produced a clipped readout, so the
    model-written text wins and the mechanical version is only a fallback.
    """

    RUBRIC = {"scale_max": 5}
    SCORES = [
        {"category": "Impact", "score": 5, "rationale": "A" * 400},
        {"category": "Innovation & Creativity", "score": 3, "rationale": "B" * 400},
    ]
    SUMMARY = (
        "This is a sharp, credible pitch built on a real problem. "
        "It is backed by genuine validation rather than vague promises. "
        "The team should tighten its go-to-market story. "
        "There is an open question about integration timelines."
    )
    WRITTEN = (
        "Let's talk about what you built. The detail that stopped me was the way "
        "your system turns a spoken instruction into a structured plan, which is a "
        "much harder problem than transcription. Your next move is real usage. "
        "Overall, this scores a four out of five."
    )

    def _review(self, spoken=None, summary=None):
        return server._format_review_for_speech(
            "NovaMind", self.SCORES, 4.0,
            summary if summary is not None else self.SUMMARY,
            self.RUBRIC, spoken,
        )

    def test_uses_the_written_verdict_when_present(self):
        text = self._review(spoken=self.WRITTEN)
        assert text == self.WRITTEN

    def test_written_verdict_is_not_padded_with_score_recital(self):
        """The screen already shows the scores; reading them aloud wastes the minute."""
        text = self._review(spoken=self.WRITTEN)
        assert "Impact, 5" not in text
        assert "Review for team" not in text

    def test_runaway_verdict_is_capped(self):
        runaway = "This pitch was good. " * 300
        text = self._review(spoken=runaway)
        assert len(text.split()) <= server.SPOKEN_REVIEW_MAX_WORDS
        assert text.rstrip()[-1] in ".!?"

    def test_unpunctuated_wall_of_text_is_capped(self):
        """Word counts don't bound speaking time if the model emits no sentence breaks."""
        text = self._review(spoken="word " * 5000)
        assert len(text.split()) <= server.SPOKEN_REVIEW_MAX_WORDS
        assert text.rstrip()[-1] in ".!?"

    def test_verdict_long_enough_to_be_worth_hearing(self):
        """~150 words is the target — roughly a minute of speech."""
        text = self._review(spoken=self.WRITTEN)
        assert len(text.split()) > 40

    def test_ampersand_is_spoken_as_and(self):
        text = self._review(spoken="Innovation & Creativity really landed here.")
        assert "&" not in text
        assert "Innovation and Creativity" in text

    def test_falls_back_when_model_omits_the_verdict(self):
        text = self._review(spoken=None)
        assert "Review for team NovaMind" in text
        assert "Impact, 5." in text
        assert "Innovation and Creativity, 3." in text
        assert "Overall, 4.0 out of 5" in text

    def test_fallback_omits_raw_rationales(self):
        text = self._review(spoken=None)
        assert "A" * 400 not in text
        assert "B" * 400 not in text

    def test_fallback_never_ends_mid_sentence(self):
        text = self._review(spoken="")
        assert text.rstrip()[-1] in ".!?"

    def test_fallback_keeps_abbreviations_intact(self):
        """Splitting on "vs." used to cut the spoken review mid-thought."""
        text = self._review(spoken=None, summary="Structured output vs. a raw transcript is the point here.")
        assert "vs. a raw transcript" in text

    def test_fallback_keeps_decimals_intact(self):
        text = self._review(spoken=None, summary="Accuracy landed at 92.5 percent across the test set.")
        assert "92.5 percent" in text

    def test_fallback_keeps_dotted_acronyms_intact(self):
        text = self._review(spoken=None, summary="They target U.S. clinics first.")
        assert "U.S. clinics" in text


class TestFinalistSpeech:
    WRITTEN = (
        "What a cohort. In third place, a team whose instinct was right. "
        "In second place, the team that proved its own pitch. "
        "And in first place, a team that measured whether it actually worked. "
        "Congratulations to everyone who pitched."
    )
    PICKS = [
        {"rank": 1, "team_name": "Alpha", "reasoning": "Best overall. " + "C " * 300},
        {"rank": 2, "team_name": "Beta", "reasoning": "Strong second. " + "D " * 300},
        {"rank": 3, "team_name": "Gamma", "reasoning": "Creative. " + "E " * 300},
    ]

    def test_uses_the_written_announcement(self):
        result = {"top_picks": self.PICKS, "reasoning": "x", "spoken_announcement": self.WRITTEN}
        assert server._format_finalist_for_speech(result) == self.WRITTEN

    def test_runaway_announcement_is_capped(self):
        result = {"top_picks": self.PICKS, "reasoning": "x",
                  "spoken_announcement": "They all did well. " * 300}
        text = server._format_finalist_for_speech(result)
        assert len(text.split()) <= server.SPOKEN_ANNOUNCEMENT_MAX_WORDS
        assert text.rstrip()[-1] in ".!?"

    def test_falls_back_to_assembled_announcement(self):
        result = {"top_picks": self.PICKS, "reasoning": "F " * 500}
        text = server._format_finalist_for_speech(result)
        for team in ("Alpha", "Beta", "Gamma"):
            assert team in text
        assert "C " * 300 not in text
        assert "F " * 500 not in text

    def test_fallback_announces_third_place_first(self):
        result = {"top_picks": [
            {"rank": 1, "team_name": "Alpha", "reasoning": "Best."},
            {"rank": 2, "team_name": "Beta", "reasoning": "Second."},
            {"rank": 3, "team_name": "Gamma", "reasoning": "Third."},
        ], "reasoning": "Strong cohort."}
        text = server._format_finalist_for_speech(result)
        assert text.index("Gamma") < text.index("Beta") < text.index("Alpha")


class TestSpokenVerdictPersistence:
    """The spoken verdict is stored so exports and the UI can show what was said."""

    @patch("server.transcribe_audio", return_value="We built a thing that works.")
    @patch("server.score_submission")
    @patch("server.speak")
    async def test_judge_returns_and_persists_spoken_review(
        self, mock_speak, mock_score, mock_transcribe, client
    ):
        spoken = "Let's talk about what you built. It matters because it works. Overall, four out of five."
        mock_score.return_value = {
            "scores": [
                {"category": "Impact", "score": 4, "rationale": "Good."},
                {"category": "Innovation", "score": 4, "rationale": "Good."},
            ],
            "summary": "Solid.",
            "spoken_review": spoken,
        }
        sub = await _create_submission(client, "Team Spoken")
        await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("test.webm", b"audio", "audio/webm")},
        )
        res = await client.post(f"/api/submissions/{sub['id']}/judge")
        assert res.status_code == 200
        assert res.json()["spoken_review"] == spoken

        # It is the text actually handed to the voice, and it is persisted.
        assert mock_speak.call_args.args[0] == spoken
        assert db.get_review(sub["id"])["spoken_text"] == spoken


class TestUploadLimits:
    """The upload used to be read whole into memory before anything checked
    its size, on a server that binds 0.0.0.0 in event mode with no auth."""

    @pytest.mark.asyncio
    async def test_a_normal_recording_uploads(self, app, tmp_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            events = (await ac.get("/api/events")).json()
            sub = (await ac.post("/api/submissions", json={
                "team_name": "Normal", "event_id": events[0]["id"]})).json()
            res = await ac.post(
                f"/api/submissions/{sub['id']}/audio",
                files={"file": ("p.webm", b"x" * 8192, "audio/webm")},
            )
            assert res.status_code == 200
            assert res.json()["status"] == "uploaded"

    @pytest.mark.asyncio
    async def test_an_oversized_recording_is_refused(self, app, tmp_db, monkeypatch):
        monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 4096)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            events = (await ac.get("/api/events")).json()
            sub = (await ac.post("/api/submissions", json={
                "team_name": "Huge", "event_id": events[0]["id"]})).json()
            res = await ac.post(
                f"/api/submissions/{sub['id']}/audio",
                files={"file": ("p.webm", b"x" * 20000, "audio/webm")},
            )
            assert res.status_code == 413
            assert "larger than" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_the_partial_file_is_not_left_behind(self, app, tmp_db, monkeypatch):
        monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 4096)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            events = (await ac.get("/api/events")).json()
            sub = (await ac.post("/api/submissions", json={
                "team_name": "Partial", "event_id": events[0]["id"]})).json()
            await ac.post(
                f"/api/submissions/{sub['id']}/audio",
                files={"file": ("p.webm", b"x" * 20000, "audio/webm")},
            )
            assert not (server.AUDIO_DIR / f"{sub['id']}.webm").exists()
            # And the submission was not marked as having audio.
            assert (await ac.get(f"/api/submissions/{sub['id']}")).json()["audio_path"] is None

    @pytest.mark.asyncio
    async def test_an_empty_recording_is_refused(self, app, tmp_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            events = (await ac.get("/api/events")).json()
            sub = (await ac.post("/api/submissions", json={
                "team_name": "Empty", "event_id": events[0]["id"]})).json()
            res = await ac.post(
                f"/api/submissions/{sub['id']}/audio",
                files={"file": ("p.webm", b"", "audio/webm")},
            )
            assert res.status_code == 400
            assert not (server.AUDIO_DIR / f"{sub['id']}.webm").exists()



class TestTheCsvIsSafeToOpen:
    """The results CSV gets mailed to organisers and teams. A spreadsheet reads
    a leading =, +, - or @ as a formula, and team names are typed by whoever is
    at the keyboard or posted by anyone on the network."""

    async def _event_with_team(self, client, team_name):
        event_id = await _get_event_id(client)
        await client.post("/api/submissions",
                          json={"team_name": team_name, "event_id": event_id})
        res = await client.get(f"/api/events/{event_id}/export/csv")
        return list(csv.reader(io.StringIO(res.text)))

    async def test_a_formula_is_neutralised(self, client):
        rows = await self._event_with_team(client, "=cmd|'/c calc'!A1")
        cell = [r[0] for r in rows if r and "cmd" in r[0]][0]
        assert cell.startswith("'")
        assert not cell.startswith("=")

    @pytest.mark.parametrize("leader", ["=", "+", "-", "@"])
    async def test_every_formula_leader_is_covered(self, client, leader):
        rows = await self._event_with_team(client, f"{leader}SUM(A1:A9)")
        cell = [r[0] for r in rows if r and "SUM" in r[0]][0]
        assert cell.startswith("'")

    async def test_an_ordinary_name_is_left_alone(self, client):
        rows = await self._event_with_team(client, "Normal Team")
        assert any(r and r[0] == "Normal Team" for r in rows)

    async def test_the_name_is_still_readable(self, client):
        # Neutralised, not censored. The organiser still sees what was typed.
        rows = await self._event_with_team(client, "=Weird Name")
        cell = [r[0] for r in rows if r and "Weird" in r[0]][0]
        assert cell == "'=Weird Name"


class TestPrfaqDownload:
    """It used to write a NamedTemporaryFile with delete=False per request, so
    every download left that team's document in the temp directory for good."""

    async def _with_prfaq(self, client):
        event_id = await _get_event_id(client)
        sub = (await client.post("/api/submissions", json={
            "team_name": "Download Team", "event_id": event_id})).json()
        server.db.update_submission(sub["id"], transcript="A pitch.")
        server.db.save_prfaq(sub["id"], {"one_liner": "x"}, "# The Document\n\nBody.", "m")
        return sub

    async def test_it_returns_the_markdown(self, client):
        sub = await self._with_prfaq(client)
        res = await client.get(f"/api/submissions/{sub['id']}/prfaq/download")
        assert res.status_code == 200
        assert res.text == "# The Document\n\nBody."
        assert res.headers["content-type"].startswith("text/markdown")

    async def test_the_filename_is_the_team(self, client):
        sub = await self._with_prfaq(client)
        res = await client.get(f"/api/submissions/{sub['id']}/prfaq/download")
        assert "PRFAQ-Download_Team.md" in res.headers["content-disposition"]

    async def test_it_writes_nothing_to_disk(self, client, monkeypatch):
        # Asserted directly rather than by watching a directory: reaching for a
        # temp file at all is the defect, and TMPDIR is cached by tempfile.
        import tempfile

        def refuse(*a, **kw):
            raise AssertionError("the download reached for a temp file again")

        monkeypatch.setattr(tempfile, "NamedTemporaryFile", refuse)
        sub = await self._with_prfaq(client)
        for _ in range(5):
            assert (await client.get(f"/api/submissions/{sub['id']}/prfaq/download")).status_code == 200

    async def test_a_missing_prfaq_is_a_404(self, client):
        event_id = await _get_event_id(client)
        sub = (await client.post("/api/submissions", json={
            "team_name": "No Doc", "event_id": event_id})).json()
        res = await client.get(f"/api/submissions/{sub['id']}/prfaq/download")
        assert res.status_code == 404

    async def test_an_unknown_submission_is_a_404(self, client):
        assert (await client.get("/api/submissions/nope/prfaq/download")).status_code == 404

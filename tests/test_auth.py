"""SPEC.md R46. The access code.

The product is unauthenticated by design on a trusted network, and that stays
the default: `npm run dev` on localhost needs nothing. What changed is that
exposing an event to the room's WiFi no longer means exposing delete to it.

The threat is not sophisticated. It is somebody on the conference network who
finds the port, reads every team's transcript, and deletes the event. A shared
code stops exactly that and nothing more, which is the right size for a tool
one person runs from a laptop for two hours.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from judge import db


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    """A throwaway database with one rubric and one event."""
    with patch.object(db, "DB_PATH", tmp_path / "test.db"):
        db.init_db()
        rubric_id = db.create_rubric(
            "R", [{"name": "Impact", "description": "i", "weight": 1.0}])
        db.create_event("Test Event", rubric_id, "")
        yield


@pytest.fixture
def app():
    with patch("server.sync_rubrics_to_db"):
        from server import app as _app
        return _app


@pytest.fixture
def coded(monkeypatch):
    monkeypatch.setenv("VJ_ACCESS_CODE", "letmein")
    return "letmein"


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


class TestWhenNoCodeIsSet:
    """Unchanged. This is every existing install and the localhost default."""

    async def test_the_api_is_open(self, client, monkeypatch):
        monkeypatch.delenv("VJ_ACCESS_CODE", raising=False)
        assert (await client.get("/api/events")).status_code == 200

    async def test_health_says_it_is_open(self, client, monkeypatch):
        monkeypatch.delenv("VJ_ACCESS_CODE", raising=False)
        assert (await client.get("/api/health")).json()["access_code_set"] is False


class TestWhenACodeIsSet:
    async def test_a_request_without_it_is_refused(self, client, coded):
        res = await client.get("/api/events")
        assert res.status_code == 401
        assert "code" in res.json()["detail"].lower()

    async def test_a_request_with_it_is_allowed(self, client, coded):
        res = await client.get("/api/events", headers={"X-Access-Code": coded})
        assert res.status_code == 200

    async def test_a_wrong_code_is_refused(self, client, coded):
        res = await client.get("/api/events", headers={"X-Access-Code": "guessing"})
        assert res.status_code == 401

    async def test_delete_is_covered(self, client, coded):
        """The route that turns a nuisance into a lost event."""
        res = await client.delete("/api/events/anything")
        assert res.status_code == 401

    async def test_the_ui_itself_still_loads(self, client, coded):
        """Otherwise the operator cannot reach the page to enter the code."""
        assert (await client.get("/")).status_code == 200

    async def test_health_still_answers(self, client, coded):
        """It carries no event data and is how you check the server is up."""
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["access_code_set"] is True

    async def test_audio_is_covered(self, client, coded):
        res = await client.get("/audio/11111111-2222-3333-4444-555555555555.webm")
        assert res.status_code == 401

    async def test_a_cookie_works_so_the_browser_asks_once(self, client, coded):
        """The operator types it once, not on every request."""
        res = await client.post("/api/session", json={"code": coded})
        assert res.status_code == 200
        assert (await client.get("/api/events")).status_code == 200

    async def test_the_wrong_code_gets_no_cookie(self, client, coded):
        assert (await client.post("/api/session", json={"code": "nope"})).status_code == 401
        assert (await client.get("/api/events")).status_code == 401

    async def test_the_code_is_never_returned_anywhere(self, client, coded):
        body = (await client.get("/api/health")).text
        assert coded not in body

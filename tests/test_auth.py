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

import server
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
        res = await client.get("/audio/11111111-2222-3333-4444-aaaabbbbcccc.webm")
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


class TestHealthIsOpenButVerifyIsNot:
    """SPEC.md R53.

    `/api/health` is exempt from the access code on purpose: it carries no event
    data and it is how you check the server is up before an event. But
    `?verify=1` makes a live billed call to OpenRouter and to ElevenLabs, so the
    exemption handed anyone on the conference network a way to spend Sanvio's
    money in a loop without knowing the code.

    The plain check stays open. The one that costs money does not.
    """

    async def test_plain_health_stays_open(self, client, coded):
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["access_code_set"] is True

    async def test_verify_requires_the_code(self, client, coded):
        res = await client.get("/api/health?verify=1")
        assert res.status_code == 401

    async def test_verify_works_with_the_code(self, client, coded):
        with patch("server._verify_providers", return_value={"openrouter": {"ok": True, "detail": "x"}}):
            res = await client.get("/api/health?verify=1", headers={"X-Access-Code": coded})
        assert res.status_code == 200
        assert "verified" in res.json()

    async def test_verify_is_open_when_no_code_is_set(self, client, monkeypatch):
        """Unchanged for every install that has not opted in."""
        monkeypatch.delenv("VJ_ACCESS_CODE", raising=False)
        with patch("server._verify_providers", return_value={}):
            res = await client.get("/api/health?verify=1")
        assert res.status_code == 200


class TestTheCodeCannotBeBruteForced:
    """SPEC.md R55.

    compare_digest defeats a timing attack and does nothing about volume. A
    code an organiser reads out to a room is short by construction, and the
    network it defends is the one the attacker is already sitting on, so an
    unthrottled endpoint is a wordlist away from open.
    """

    def setup_method(self):
        server._FAILED_ATTEMPTS.clear()

    async def test_wrong_codes_eventually_lock_out(self, client, coded):
        for _ in range(server.ATTEMPTS_BEFORE_LOCKOUT):
            assert (await client.post("/api/session", json={"code": "wrong"})).status_code == 401
        res = await client.post("/api/session", json={"code": "wrong"})
        assert res.status_code == 429
        assert "too many attempts" in res.json()["detail"].lower()

    async def test_the_lockout_covers_the_header_too(self, client, coded):
        """Otherwise the guess loop just moves to a different route."""
        for _ in range(server.ATTEMPTS_BEFORE_LOCKOUT):
            await client.get("/api/events", headers={"X-Access-Code": "wrong"})
        res = await client.get("/api/events", headers={"X-Access-Code": "wrong"})
        assert res.status_code == 429

    async def test_the_right_code_still_works_before_the_threshold(self, client, coded):
        for _ in range(server.ATTEMPTS_BEFORE_LOCKOUT - 1):
            await client.post("/api/session", json={"code": "wrong"})
        assert (await client.post("/api/session", json={"code": coded})).status_code == 200

    async def test_success_clears_the_count(self, client, coded):
        """An operator who fumbles it twice and then gets it right is not one
        typo away from being locked out of their own event."""
        for _ in range(server.ATTEMPTS_BEFORE_LOCKOUT - 1):
            await client.post("/api/session", json={"code": "wrong"})
        await client.post("/api/session", json={"code": coded})
        assert server._FAILED_ATTEMPTS == {}

    async def test_the_lockout_is_capped(self):
        """It doubles, but not until the end of the event."""
        assert server.MAX_LOCKOUT_SECONDS <= 15 * 60

    async def test_nothing_throttles_when_no_code_is_set(self, client, monkeypatch):
        monkeypatch.delenv("VJ_ACCESS_CODE", raising=False)
        for _ in range(server.ATTEMPTS_BEFORE_LOCKOUT + 3):
            assert (await client.get("/api/events")).status_code == 200

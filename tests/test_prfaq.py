"""PRFAQ generation, rendering, storage, and the API surface around it."""

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

import server
from judge import db, prfaq
from judge.mock_externals import mock_generate_prfaq

# --- Fixtures ---

@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    test_db = tmp_path / "test.db"
    with patch.object(db, "DB_PATH", test_db):
        db.init_db()
        rubric_id = db.create_rubric(
            name="Test Rubric",
            categories=[{"name": "Impact", "description": "Real-world impact", "weight": 1.0}],
            scale_min=1,
            scale_max=5,
        )
        db.create_event("Test Hackathon", rubric_id, "A test event")
        yield test_db


@pytest.fixture
def app():
    with patch("server.sync_rubrics_to_db"):
        from server import app as _app
        return _app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _judged_submission(client, team_name="Team Test") -> dict:
    """Create a submission that has been through the judging pipeline."""
    event_id = (await client.get("/api/events")).json()[0]["id"]
    sub = (await client.post(
        "/api/submissions", json={"team_name": team_name, "event_id": event_id}
    )).json()

    with patch("server.transcribe_audio", return_value=f"{team_name} pitch: we built a thing."), \
         patch("server.score_submission", return_value={
             "scores": [{"category": "Impact", "score": 4, "rationale": "Solid."}],
             "summary": "A solid submission.",
         }), \
         patch("server.speak", return_value=Path("/tmp/fake.mp3")):
        await client.post(
            f"/api/submissions/{sub['id']}/audio",
            files={"file": ("test.webm", b"fake audio data", "audio/webm")},
        )
        await client.post(f"/api/submissions/{sub['id']}/judge")

    return sub


SAMPLE = mock_generate_prfaq("NovaMind", "transcript", "Test Hackathon")


# --- Rendering ---

class TestRenderMarkdown:
    def test_includes_the_disclaimer(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "Nobody reviewed it" in md
        assert "⚠️" in md

    def test_disclaimer_is_not_the_models_responsibility(self):
        """A model that returns only the bare minimum still produces a safe document."""
        md = prfaq.render_markdown({"product_name": "Thing"}, "NovaMind")
        assert "Nobody reviewed it" in md
        assert "Not verified." in md

    def test_labels_the_invented_customer_quote(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "[INVENTED ARCHETYPE — not a real customer, not a reference.]" in md

    def test_omits_the_customer_label_when_there_is_no_quote(self):
        content = {**SAMPLE, "press_release": {"headline": "A headline"}}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "INVENTED ARCHETYPE" not in md

    def test_has_all_five_sections(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        for heading in (
            "## 1. Press Release",
            "## 2. Customer FAQ",
            "## 3. The Hard FAQ",
            "## 4. Assumptions Ledger",
            "## 5. What Would Change Our Mind",
            "## Provenance",
        ):
            assert heading in md

    def test_tallies_the_assumption_grades(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert f"{len(SAMPLE['assumptions'])} assumptions:" in md
        assert "**6** untested" in md

    def test_records_the_model_that_wrote_it(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind", model="anthropic/claude-sonnet-5")
        assert "`anthropic/claude-sonnet-5`" in md

    def test_press_release_carries_no_hedging(self):
        """The two-voice rule: doubt belongs in sections 3 and 4, never in the launch."""
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        press_release = md.split("## 2. Customer FAQ")[0]
        # The header disclaimer is rendered above section 1 by design; check the
        # press release body itself.
        body = press_release.split("## 1. Press Release")[1]
        for hedge in ("Untested", "Partly tested", "[ASSUMPTION]", "not been measured"):
            assert hedge not in body

    def test_survives_an_empty_response(self):
        md = prfaq.render_markdown({}, "NovaMind")
        assert "# PRFAQ — NovaMind" in md

    def test_falls_back_to_team_name_when_the_product_is_unnamed(self):
        md = prfaq.render_markdown({"press_release": {"headline": "H"}}, "NovaMind")
        assert "# PRFAQ — NovaMind" in md


class TestTheFounderQuoteIsNeverInvented:
    """A pitch describes the product. It rarely describes the reason.

    The generator returns null for `team_quote` when the pitch carries no
    founding account, and the document has to ask for one rather than write one.
    """

    def test_a_missing_quote_becomes_a_placeholder(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "[QUOTE TO COME FROM THE TEAM" in md

    def test_the_placeholder_says_it_is_a_placeholder_not_a_caveat(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "Production placeholder, not a caveat" in md

    def test_a_real_quote_wins(self):
        content = {**SAMPLE, "press_release": {
            **SAMPLE["press_release"],
            "team_quote": {"speaker": "Ada", "role": "Founder", "quote": "My sister needed it."},
        }}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "> My sister needed it." in md
        assert "QUOTE TO COME" not in md
        assert "### Quote — Ada, Founder" in md


class TestItReadsLikeAnAmazonPressRelease:
    """The order is most of what makes a press release read like one.

    A spokesperson explains why the thing was built before the reader is told how
    to use it, and the customer quote is someone reporting back from having done
    exactly that. Getting started between the two is the hinge.
    """

    def _order(self, md):
        section = md.split("## 1. Press Release")[1].split("## 2. Customer FAQ")[0]
        marks = {
            "problem": section.index("### The problem"),
            "solution": section.index("### The solution"),
            "team_quote": section.index("QUOTE TO COME"),
            "getting_started": section.index("### Getting started"),
            "customer_quote": section.index("INVENTED ARCHETYPE"),
            "closing": section.index("start with one real task"),
        }
        return [k for k, _ in sorted(marks.items(), key=lambda kv: kv[1])]

    def test_the_elements_run_in_the_amazon_order(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert self._order(md) == [
            "problem", "solution", "team_quote",
            "getting_started", "customer_quote", "closing",
        ]

    def test_the_team_quote_comes_before_getting_started(self):
        """The regression this guards: quotes bunched at the end read as a brief."""
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        order = self._order(md)
        assert order.index("team_quote") < order.index("getting_started")

    def test_it_closes_on_what_the_reader_does_next(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        section = md.split("## 1. Press Release")[1].split("## 2. Customer FAQ")[0]
        assert section.rstrip().rstrip("-").rstrip().endswith("account they already have.")

    def test_a_stated_launch_date_becomes_a_dateline(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "**MARCH 2027** — " in md
        assert "the launch the team described" in md

    def test_an_unstated_launch_date_is_named_as_an_assumption(self):
        content = {**SAMPLE, "press_release": {**SAMPLE["press_release"], "launch_timing": None}}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "a launch date nobody has set" in md
        assert "**MARCH 2027**" not in md

    def test_a_document_with_no_closing_still_ends_cleanly(self):
        content = {**SAMPLE, "press_release": {**SAMPLE["press_release"], "closing": None}}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "## 2. Customer FAQ" in md


class TestDifferentiators:
    def test_each_mechanism_gets_a_bold_lead(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "**It runs during the work, not after it.**" in md

    def test_they_sit_inside_the_press_release(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        press_release = md.split("## 2. Customer FAQ")[0]
        assert "It runs during the work" in press_release

    def test_the_lead_sentence_is_closed_before_the_explanation(self):
        """Without this the bold run crashes straight into the next sentence."""
        content = {**SAMPLE, "press_release": {
            **SAMPLE["press_release"],
            "differentiators": [{"name": "It runs during the work", "why": "A plain transcript does not."}],
        }}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "**It runs during the work.** A plain transcript does not." in md

    def test_a_lead_that_already_ends_cleanly_is_left_alone(self):
        content = {**SAMPLE, "press_release": {
            **SAMPLE["press_release"],
            "differentiators": [{"name": "Why not run it live?", "why": "So they did."}],
        }}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "**Why not run it live?** So they did." in md

    def test_a_document_without_them_still_renders(self):
        content = {**SAMPLE, "press_release": {"headline": "H", "solution": "It works."}}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "It works." in md


class TestWhatWouldChangeOurMind:
    def test_each_entry_carries_its_measurement(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "**How you would measure it.**" in md
        assert "**What it would mean.**" in md

    def test_entries_are_numbered_headings_rather_than_bullets(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        section = md.split("## 5. What Would Change Our Mind")[1]
        assert "### 1. Fewer than one in four users" in section

    def test_a_stored_document_from_the_old_shape_still_renders(self):
        """Plain strings were the shape before the measurement fields existed."""
        content = {**SAMPLE, "would_change_our_mind": ["Nobody runs a second task."]}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "1. Nobody runs a second task." in md


class TestTheLedgerNamesWhereToStart:
    def test_the_cheapest_row_is_marked(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "⬅ start here" in md
        assert "It is where Monday starts." in md

    def test_only_the_marked_row_carries_it(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert md.count("⬅ start here") == 1

    def test_a_ledger_with_nothing_marked_renders_unchanged(self):
        rows = [{**a, "cheapest_to_close": False} for a in SAMPLE["assumptions"]]
        md = prfaq.render_markdown({**SAMPLE, "assumptions": rows}, "NovaMind")
        assert "start here" not in md


class TestFrontmatter:
    def test_carries_the_grade_tally(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        head = md.split("---")[1]
        assert "assumptions_total: 6" in head
        assert "assumptions_untested: 6" in head
        assert "assumptions_tested: 0" in head

    def test_states_that_nobody_reviewed_it(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "reviewed_by_a_human: false" in md

    def test_records_the_model_when_there_is_one(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind", model="anthropic/claude-sonnet-5")
        assert 'written_by: "anthropic/claude-sonnet-5"' in md


class TestProvenanceNamesTheMisreading:
    def test_warns_that_the_press_release_numbers_are_the_teams_own_claims(self):
        md = prfaq.render_markdown(SAMPLE, "NovaMind")
        assert "How this document is most likely to mislead you" in md
        assert "does not become evidence" in md


class TestPrfaqModel:
    def test_defaults_to_the_scoring_model(self, monkeypatch):
        monkeypatch.delenv(prfaq.PRFAQ_MODEL_ENV, raising=False)
        monkeypatch.setenv("OPENROUTER_SCORING_MODEL", "anthropic/claude-sonnet-5")
        assert prfaq.prfaq_model() == "anthropic/claude-sonnet-5"

    def test_override_wins(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_SCORING_MODEL", "cheap/model")
        monkeypatch.setenv(prfaq.PRFAQ_MODEL_ENV, "expensive/model")
        assert prfaq.prfaq_model() == "expensive/model"


# --- Storage ---

class TestPrfaqStorage:
    @staticmethod
    def _submission(team_name="NovaMind") -> str:
        event = db.list_events()[0]
        return db.create_submission(team_name, event["id"], event["rubric_id"])

    def test_round_trips(self):
        sub_id = self._submission()
        db.save_prfaq(sub_id, SAMPLE, "# markdown", "some/model")
        stored = db.get_prfaq(sub_id)
        assert stored["content"]["product_name"] == "NovaMind"
        assert stored["markdown"] == "# markdown"
        assert stored["model"] == "some/model"

    def test_returns_none_when_absent(self):
        assert db.get_prfaq("nope") is None

    def test_regenerating_replaces_rather_than_duplicates(self):
        sub_id = self._submission()
        db.save_prfaq(sub_id, SAMPLE, "# first", "m")
        db.save_prfaq(sub_id, SAMPLE, "# second", "m")
        assert db.get_prfaq(sub_id)["markdown"] == "# second"


# --- API ---

class TestPrfaqApi:
    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_generates_from_a_judged_submission(self, mock_gen, client):
        sub = await _judged_submission(client)
        res = await client.post(f"/api/submissions/{sub['id']}/prfaq")
        assert res.status_code == 200
        data = res.json()
        assert data["cached"] is False
        assert data["content"]["assumptions"]
        assert "# PRFAQ" in data["markdown"]

    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_second_call_returns_the_stored_document(self, mock_gen, client):
        sub = await _judged_submission(client)
        await client.post(f"/api/submissions/{sub['id']}/prfaq")
        res = await client.post(f"/api/submissions/{sub['id']}/prfaq")
        assert res.json()["cached"] is True
        assert mock_gen.call_count == 1

    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_force_regenerates(self, mock_gen, client):
        sub = await _judged_submission(client)
        await client.post(f"/api/submissions/{sub['id']}/prfaq")
        res = await client.post(f"/api/submissions/{sub['id']}/prfaq?force=true")
        assert res.json()["cached"] is False
        assert mock_gen.call_count == 2

    async def test_rejects_a_submission_with_no_transcript(self, client):
        event_id = (await client.get("/api/events")).json()[0]["id"]
        sub = (await client.post(
            "/api/submissions", json={"team_name": "Unjudged", "event_id": event_id}
        )).json()
        res = await client.post(f"/api/submissions/{sub['id']}/prfaq")
        assert res.status_code == 400
        assert "transcript" in res.json()["detail"].lower()

    async def test_unknown_submission_404s(self, client):
        res = await client.post("/api/submissions/nope/prfaq")
        assert res.status_code == 404

    @patch("server.generate_prfaq", side_effect=KeyError("OPENROUTER_API_KEY"))
    async def test_missing_key_is_readable(self, mock_gen, client):
        sub = await _judged_submission(client)
        res = await client.post(f"/api/submissions/{sub['id']}/prfaq")
        assert res.status_code == 500
        assert "OPENROUTER_API_KEY" in res.json()["detail"]

    @patch("server.generate_prfaq", side_effect=RuntimeError("provider exploded"))
    async def test_generation_failure_surfaces(self, mock_gen, client):
        sub = await _judged_submission(client)
        res = await client.post(f"/api/submissions/{sub['id']}/prfaq")
        assert res.status_code == 500
        assert "provider exploded" in res.json()["detail"]

    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_get_returns_the_stored_document(self, mock_gen, client):
        sub = await _judged_submission(client)
        await client.post(f"/api/submissions/{sub['id']}/prfaq")
        res = await client.get(f"/api/submissions/{sub['id']}/prfaq")
        assert res.status_code == 200
        assert res.json()["team_name"] == "Team Test"

    async def test_get_404s_before_generation(self, client):
        sub = await _judged_submission(client)
        res = await client.get(f"/api/submissions/{sub['id']}/prfaq")
        assert res.status_code == 404

    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_submission_detail_reports_whether_one_exists(self, mock_gen, client):
        sub = await _judged_submission(client)
        assert (await client.get(f"/api/submissions/{sub['id']}")).json()["has_prfaq"] is False
        await client.post(f"/api/submissions/{sub['id']}/prfaq")
        assert (await client.get(f"/api/submissions/{sub['id']}")).json()["has_prfaq"] is True


class TestEventPrfaqs:
    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_generates_for_every_judged_team(self, mock_gen, client):
        await _judged_submission(client, "Alpha")
        await _judged_submission(client, "Beta")
        event_id = (await client.get("/api/events")).json()[0]["id"]

        res = await client.post(f"/api/events/{event_id}/prfaqs")
        assert res.status_code == 200
        data = res.json()
        assert sorted(data["generated"]) == ["Alpha", "Beta"]
        assert data["failed"] == []

    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_skips_teams_with_no_transcript(self, mock_gen, client):
        await _judged_submission(client, "Alpha")
        event_id = (await client.get("/api/events")).json()[0]["id"]
        await client.post("/api/submissions", json={"team_name": "NoShow", "event_id": event_id})

        data = (await client.post(f"/api/events/{event_id}/prfaqs")).json()
        assert data["generated"] == ["Alpha"]
        assert data["skipped"] == [{"team_name": "NoShow", "reason": "no transcript"}]

    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_skips_teams_that_already_have_one(self, mock_gen, client):
        sub = await _judged_submission(client, "Alpha")
        await client.post(f"/api/submissions/{sub['id']}/prfaq")
        event_id = (await client.get("/api/events")).json()[0]["id"]

        data = (await client.post(f"/api/events/{event_id}/prfaqs")).json()
        assert data["generated"] == []
        assert data["skipped"] == [{"team_name": "Alpha", "reason": "already generated"}]

    async def test_one_teams_failure_does_not_stop_the_rest(self, client):
        await _judged_submission(client, "Alpha")
        await _judged_submission(client, "Beta")
        event_id = (await client.get("/api/events")).json()[0]["id"]

        calls = []

        def flaky(team_name, transcript, event_name=""):
            calls.append(team_name)
            if team_name == "Alpha":
                raise RuntimeError("provider exploded")
            return mock_generate_prfaq(team_name, transcript, event_name)

        with patch("server.generate_prfaq", side_effect=flaky):
            data = (await client.post(f"/api/events/{event_id}/prfaqs")).json()

        assert data["generated"] == ["Beta"]
        assert data["failed"][0]["team_name"] == "Alpha"
        assert "provider exploded" in data["failed"][0]["reason"]

    async def test_unknown_event_404s(self, client):
        res = await client.post("/api/events/nope/prfaqs")
        assert res.status_code == 404


# --- Export ---

class TestPrfaqExport:
    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_bundle_writes_one_file_per_team(self, mock_gen, client, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "__file__", str(tmp_path / "server.py"))
        sub = await _judged_submission(client, "Alpha")
        await client.post(f"/api/submissions/{sub['id']}/prfaq")
        event_id = (await client.get("/api/events")).json()[0]["id"]

        res = await client.get(f"/api/events/{event_id}/export/bundle")
        assert res.status_code == 200
        data = res.json()
        assert data["prfaqs"] == 1

        prfaq_file = Path(data["path"]) / "prfaqs" / "alpha.md"
        assert prfaq_file.exists()
        assert "Nobody reviewed it" in prfaq_file.read_text()

    async def test_bundle_omits_the_folder_when_none_were_generated(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "__file__", str(tmp_path / "server.py"))
        await _judged_submission(client, "Alpha")
        event_id = (await client.get("/api/events")).json()[0]["id"]

        data = (await client.get(f"/api/events/{event_id}/export/bundle")).json()
        assert data["prfaqs"] == 0
        assert not (Path(data["path"]) / "prfaqs").exists()

    @patch("server.generate_prfaq", side_effect=mock_generate_prfaq)
    async def test_json_export_carries_the_prfaq(self, mock_gen, client):
        sub = await _judged_submission(client, "Alpha")
        await client.post(f"/api/submissions/{sub['id']}/prfaq")
        event_id = (await client.get("/api/events")).json()[0]["id"]

        data = (await client.get(f"/api/events/{event_id}/export/json")).json()
        assert data["submissions"][0]["prfaq"]["assumptions"]


class TestGradeTallyAlwaysAddsUp:
    """The frontmatter carries the counts so they survive being pasted
    elsewhere. A total that does not equal the sum of its parts is worse than
    no total, because it looks authoritative."""

    def test_the_three_known_grades_are_kept(self):
        for g in ("Tested", "Partly tested", "Untested"):
            assert prfaq.normalize_grade(g) == g

    def test_case_and_spacing_do_not_matter(self):
        assert prfaq.normalize_grade("partly   TESTED") == "Partly tested"
        assert prfaq.normalize_grade("  untested ") == "Untested"

    def test_anything_unrecognised_becomes_untested(self):
        for g in ("Unproven", "Not tested", "unknown", "", None, 7):
            assert prfaq.normalize_grade(g) == "Untested"

    def test_the_counts_sum_to_the_total(self):
        assumptions = [
            {"grade": "Tested"}, {"grade": "Partly tested"}, {"grade": "Untested"},
            {"grade": "Unproven"}, {"grade": None}, {},
        ]
        counts = prfaq._grade_counts(assumptions)
        assert sum(counts.values()) == len(assumptions)
        assert set(counts) == {"Tested", "Partly tested", "Untested"}

    def test_the_rendered_frontmatter_adds_up(self):
        content = {**SAMPLE, "assumptions": [
            {"assumption": "a", "grade": "Tested", "evidence": ""},
            {"assumption": "b", "grade": "Unproven", "evidence": ""},
        ]}
        md = prfaq.render_markdown(content, "NovaMind")
        import re
        vals = {k: int(v) for k, v in re.findall(r"^assumptions_(\w+): (\d+)$", md, re.MULTILINE)}
        assert vals["total"] == vals["untested"] + vals["partly_tested"] + vals["tested"]

    def test_the_body_shows_the_grade_it_was_counted_as(self):
        content = {**SAMPLE, "assumptions": [
            {"assumption": "a", "grade": "Unproven", "evidence": ""},
        ]}
        md = prfaq.render_markdown(content, "NovaMind")
        assert "**Grade:** Untested" in md
        assert "Unproven" not in md

"""The finalist round.

This is the highest-stakes output the tool produces: it is read aloud to a room
and it decides who won. The model hands back team names as free text, and until
these tests existed nothing checked them against the teams that actually
pitched.
"""

import pytest

from judge import llm
from server import _reconcile_top_picks


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Build no client and make no call, for every test in this module.

    _get_client reads OPENROUTER_API_KEY, so without this a test only passes on
    a machine that happens to have a real key in its environment. CI does not.

    Module scoped rather than per class, because it was per class, the next
    class added to this file did not inherit it, and it failed in CI for
    exactly the reason this docstring already gave.
    """
    # `object` is callable and returns an instance, which is all the code under
    # test does with the result.
    monkeypatch.setattr(llm, "_get_client", object)


def completed(*names):
    return [{"team_name": n} for n in names]


def picks(*names):
    return [{"rank": i, "team_name": n, "reasoning": "because"} for i, n in enumerate(names, 1)]


class TestThePodiumMustBeRealTeams:
    def test_matching_names_pass_through(self):
        got = _reconcile_top_picks(picks("Alpha", "Beta", "Gamma"),
                                   completed("Alpha", "Beta", "Gamma"))
        assert [p["team_name"] for p in got] == ["Alpha", "Beta", "Gamma"]

    def test_the_rest_of_the_pick_is_preserved(self):
        got = _reconcile_top_picks(picks("Alpha"), completed("Alpha"))
        assert got[0]["rank"] == 1
        assert got[0]["reasoning"] == "because"

    def test_a_case_difference_is_corrected_silently(self):
        got = _reconcile_top_picks(picks("alpha"), completed("Alpha"))
        assert got[0]["team_name"] == "Alpha"

    def test_a_spacing_difference_is_corrected_silently(self):
        got = _reconcile_top_picks(picks("Team   Alpha"), completed("Team Alpha"))
        assert got[0]["team_name"] == "Team Alpha"

    def test_an_invented_team_is_refused(self):
        with pytest.raises(ValueError) as exc:
            _reconcile_top_picks(picks("Alpha", "Nobody"), completed("Alpha", "Beta"))
        assert "did not pitch" in str(exc.value)
        assert "Nobody" in str(exc.value)

    def test_the_same_team_twice_is_refused(self):
        with pytest.raises(ValueError) as exc:
            _reconcile_top_picks(picks("Alpha", "Alpha"), completed("Alpha", "Beta"))
        assert "twice" in str(exc.value)

    def test_a_duplicate_that_differs_only_in_case_is_still_a_duplicate(self):
        with pytest.raises(ValueError):
            _reconcile_top_picks(picks("Alpha", "ALPHA"), completed("Alpha", "Beta"))

    def test_a_missing_name_is_refused(self):
        with pytest.raises(ValueError):
            _reconcile_top_picks([{"rank": 1, "reasoning": "x"}], completed("Alpha"))

    def test_an_empty_podium_is_allowed_through_unchanged(self):
        # Nothing to check. The route decides separately whether that is useful.
        assert _reconcile_top_picks([], completed("Alpha")) == []


class TestTheFinalistRoundReadsThePitch:
    """It used to see 500 characters, about a tenth of a real five minute pitch,
    and then decide the winner."""

    def test_the_default_covers_a_full_pitch(self):
        # Real transcripts in the wild run to roughly 4,700 characters.
        assert llm.FINALIST_TRANSCRIPT_CHARS >= 4700

    def _prompt_for(self, transcript, monkeypatch):
        captured = {}

        def fake(client, model, messages, max_tokens, what="response", **kw):
            captured["user"] = messages[1]["content"]
            return {"top_picks": [], "reasoning": ""}

        monkeypatch.setattr(llm, "complete_json", fake)
        llm.run_finalist_round(
            [{"team_name": "A", "transcript": transcript, "scores": [], "overall_score": 4.0}],
            {"categories": [{"name": "Impact"}], "scale_max": 5},
        )
        return captured["user"]

    def test_a_whole_pitch_is_sent_whole(self, monkeypatch):
        transcript = "word " * 900  # ~4,500 chars, a full pitch
        prompt = self._prompt_for(transcript, monkeypatch)
        assert transcript.strip()[-40:] in prompt

    def test_a_complete_transcript_is_not_labelled_an_excerpt(self, monkeypatch):
        prompt = self._prompt_for("a short pitch", monkeypatch)
        assert "Transcript:" in prompt
        assert "Transcript excerpt:" not in prompt
        assert "a short pitch..." not in prompt

    def test_an_overlong_transcript_is_cut_and_says_so(self, monkeypatch):
        prompt = self._prompt_for("x" * (llm.FINALIST_TRANSCRIPT_CHARS + 500), monkeypatch)
        assert "Transcript excerpt:" in prompt
        # Read the excerpt back out of the prompt rather than counting "x"
        # across the whole string, since the word "excerpt" carries one.
        body = prompt.split("Transcript excerpt:")[1].split("\n---")[0].strip()
        assert body.endswith("...")
        assert len(body[:-3]) == llm.FINALIST_TRANSCRIPT_CHARS

    def test_a_missing_transcript_does_not_crash(self, monkeypatch):
        prompt = self._prompt_for(None, monkeypatch)
        assert "Team 1: A" in prompt


class TestTheFinalistRoundScalesWithTheRoom:
    """SPEC.md R41.

    The round sends every team's scores and up to FINALIST_TRANSCRIPT_CHARS of
    each transcript in one request, so its input grows linearly with team count.
    Nothing had ever measured where that stops working, so "how many teams can
    one event hold" was an open question with no evidence either way.

    Measured 2026-08-23 against full five minute transcripts: about 4k tokens at
    3 teams, 24k at 20, 49k at 40 and 97k at 80. It is not the constraint. The
    constraint on an event is the thirty seconds of live judging per team.
    """

    def _prompt_chars(self, teams, monkeypatch):
        captured = {}

        def fake(client, model, messages, max_tokens, what="response", **kw):
            captured["chars"] = sum(len(m["content"]) for m in messages)
            return {"top_picks": [], "reasoning": ""}

        monkeypatch.setattr(llm, "complete_json", fake)
        transcript = "word " * 940  # about 4,700 characters, a real pitch
        rubric = {"categories": [{"name": n} for n in ("A", "B", "C", "D")], "scale_max": 5}
        subs = [{
            "team_name": f"Team {i}", "transcript": transcript,
            "scores": [{"category": c["name"], "score": 4} for c in rubric["categories"]],
            "overall_score": 4.0,
        } for i in range(teams)]
        llm.run_finalist_round(subs, rubric)
        return captured["chars"]

    def test_it_grows_linearly_rather_than_worse(self, monkeypatch):
        ten = self._prompt_chars(10, monkeypatch)
        forty = self._prompt_chars(40, monkeypatch)
        # Four times the teams, near enough four times the prompt, plus a fixed
        # system prompt that does not grow.
        assert 3.5 < forty / ten < 4.5

    def test_forty_teams_fits_a_modern_context_comfortably(self, monkeypatch):
        approx_tokens = self._prompt_chars(40, monkeypatch) / 4
        assert approx_tokens < 100_000, f"{approx_tokens:,.0f} tokens at 40 teams"

    def test_eighty_teams_still_fits(self, monkeypatch):
        """Far past any hackathon this is built for, and still not the limit."""
        approx_tokens = self._prompt_chars(80, monkeypatch) / 4
        assert approx_tokens < 180_000, f"{approx_tokens:,.0f} tokens at 80 teams"

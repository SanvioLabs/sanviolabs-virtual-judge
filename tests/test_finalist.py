"""The finalist round.

This is the highest-stakes output the tool produces: it is read aloud to a room
and it decides who won. The model hands back team names as free text, and until
these tests existed nothing checked them against the teams that actually
pitched.
"""

import pytest

from server import _reconcile_top_picks
from judge import llm


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

    def _prompt_for(self, transcript):
        captured = {}

        def fake(client, model, messages, max_tokens, what="response", **kw):
            captured["user"] = messages[1]["content"]
            return {"top_picks": [], "reasoning": ""}

        original = llm.complete_json
        llm.complete_json = fake
        try:
            llm.run_finalist_round(
                [{"team_name": "A", "transcript": transcript, "scores": [], "overall_score": 4.0}],
                {"categories": [{"name": "Impact"}], "scale_max": 5},
            )
        finally:
            llm.complete_json = original
        return captured["user"]

    def test_a_whole_pitch_is_sent_whole(self):
        transcript = "word " * 900  # ~4,500 chars, a full pitch
        prompt = self._prompt_for(transcript)
        assert transcript.strip()[-40:] in prompt

    def test_a_complete_transcript_is_not_labelled_an_excerpt(self):
        prompt = self._prompt_for("a short pitch")
        assert "Transcript:" in prompt
        assert "Transcript excerpt:" not in prompt
        assert "a short pitch..." not in prompt

    def test_an_overlong_transcript_is_cut_and_says_so(self):
        prompt = self._prompt_for("x" * (llm.FINALIST_TRANSCRIPT_CHARS + 500))
        assert "Transcript excerpt:" in prompt
        # Read the excerpt back out of the prompt rather than counting "x"
        # across the whole string, since the word "excerpt" carries one.
        body = prompt.split("Transcript excerpt:")[1].split("\n---")[0].strip()
        assert body.endswith("...")
        assert len(body[:-3]) == llm.FINALIST_TRANSCRIPT_CHARS

    def test_a_missing_transcript_does_not_crash(self):
        prompt = self._prompt_for(None)
        assert "Team 1: A" in prompt

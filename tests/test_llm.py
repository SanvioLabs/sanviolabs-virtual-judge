"""Tests for the LLM judge module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from judge import llm
from judge.llm import run_finalist_round, score_submission

MOCK_RUBRIC = {
    "name": "Test",
    "categories": [
        {"name": "Impact", "description": "Real-world impact", "weight": 1.0},
        {"name": "Innovation", "description": "Creative", "weight": 1.0},
    ],
    "scale_min": 1,
    "scale_max": 5,
    "calibration": "Score strictly.",
    "judge_persona": "You are a judge.",
}


def _mock_response(text: str):
    """Create a mock OpenRouter (OpenAI-compatible) chat completion response."""
    mock = MagicMock()
    mock.choices = [MagicMock(message=MagicMock(content=text))]
    return mock


class TestScoreSubmission:
    @patch("judge.llm._get_client")
    def test_parses_clean_json(self, mock_client):
        response_json = json.dumps({
            "scores": [
                {"category": "Impact", "score": 4, "rationale": "Good problem."},
                {"category": "Innovation", "score": 3, "rationale": "Decent."},
            ],
            "summary": "Solid work.",
        })
        mock_client.return_value.chat.completions.create.return_value = _mock_response(response_json)

        result = score_submission("We built a thing.", MOCK_RUBRIC)
        assert len(result["scores"]) == 2
        assert result["scores"][0]["score"] == 4
        assert result["summary"] == "Solid work."

    @patch("judge.llm._get_client")
    def test_parses_json_in_code_block(self, mock_client):
        response_text = '''Here's my evaluation:

```json
{
  "scores": [
    {"category": "Impact", "score": 5, "rationale": "Excellent."},
    {"category": "Innovation", "score": 4, "rationale": "Novel."}
  ],
  "summary": "Outstanding pitch."
}
```'''
        mock_client.return_value.chat.completions.create.return_value = _mock_response(response_text)

        result = score_submission("Amazing product.", MOCK_RUBRIC)
        assert result["scores"][0]["score"] == 5
        assert result["summary"] == "Outstanding pitch."

    @patch("judge.llm._get_client")
    def test_parses_json_in_bare_code_block(self, mock_client):
        response_text = '''```
{"scores": [{"category": "Impact", "score": 2, "rationale": "Weak."},{"category": "Innovation", "score": 2, "rationale": "Seen before."}], "summary": "Needs work."}
```'''
        mock_client.return_value.chat.completions.create.return_value = _mock_response(response_text)

        result = score_submission("Basic app.", MOCK_RUBRIC)
        assert result["scores"][0]["score"] == 2


class TestFinalistRound:
    @patch("judge.llm._get_client")
    def test_parses_finalist_result(self, mock_client):
        response_json = json.dumps({
            "top_picks": [
                {"rank": 1, "team_name": "Alpha", "reasoning": "Best overall."},
                {"rank": 2, "team_name": "Beta", "reasoning": "Strong second."},
                {"rank": 3, "team_name": "Gamma", "reasoning": "Creative."},
            ],
            "reasoning": "Strong cohort.",
        })
        mock_client.return_value.chat.completions.create.return_value = _mock_response(response_json)

        submissions = [
            {"team_name": "Alpha", "transcript": "We built X.", "scores": [{"category": "Impact", "score": 5}], "overall_score": 4.5},
            {"team_name": "Beta", "transcript": "We built Y.", "scores": [{"category": "Impact", "score": 4}], "overall_score": 4.0},
            {"team_name": "Gamma", "transcript": "We built Z.", "scores": [{"category": "Impact", "score": 3}], "overall_score": 3.5},
        ]

        result = run_finalist_round(submissions, MOCK_RUBRIC)
        assert len(result["top_picks"]) == 3
        assert result["top_picks"][0]["team_name"] == "Alpha"
        assert result["reasoning"] == "Strong cohort."


class TestTheRubricDoesNotFightThePrompt:
    """SPEC.md R32.

    The rubric's persona and the product's scoring prompt are concatenated into
    one system prompt. The shipped rubric used to say "always close with three
    specific next steps" while the prompt asked for one improvement, a close on
    the score, and 150 to 170 words. Both instructions reached the model
    together, and the most visible output of the product was the result of that
    argument.

    The prompt owns shape. A persona owns tone. These hold the boundary.
    """

    def _shipped_persona(self):
        import yaml
        path = Path(__file__).parent.parent / "rubrics" / "example-hackathon.yaml"
        return yaml.safe_load(path.read_text())["judge_persona"]

    def test_the_prompt_is_the_one_that_fixes_the_shape(self):
        import inspect
        source = inspect.getsource(llm.score_submission)
        assert "150 to 170 words" in source
        assert "Close by saying the overall score" in source

    def test_the_shipped_persona_does_not_set_the_closing(self):
        persona = self._shipped_persona().lower()
        for directive in ("close with three", "always close with", "three specific next steps"):
            assert directive not in persona, f"the shipped rubric dictates the closing: {directive!r}"

    def test_the_shipped_persona_does_not_set_a_length(self):
        persona = self._shipped_persona().lower()
        for directive in ("60 seconds", "words", "sentences long"):
            assert directive not in persona, f"the shipped rubric dictates length: {directive!r}"

    def test_the_shipped_persona_still_sets_tone(self):
        persona = self._shipped_persona().lower()
        assert "warm" in persona
        assert "honest" in persona

    def test_the_persona_says_where_the_boundary_is(self):
        """So the next person editing it does not put the shape back."""
        assert "Set the tone here, not the format" in self._shipped_persona()

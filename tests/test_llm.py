"""Tests for the LLM judge module."""

import json
from unittest.mock import MagicMock, patch

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

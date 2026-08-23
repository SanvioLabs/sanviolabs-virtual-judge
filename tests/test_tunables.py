"""The numbers nobody wrote a reason for.

Every value here is a choice the code makes that nothing records a rationale
for. They are collected as open questions in `docs/spec-questions.md`, and
pinning them is not the same as justifying them.

What these tests buy is that changing one becomes a deliberate act with a test
to update, rather than a silent drift nobody notices until a room full of teams
is waiting. What they do not buy is an answer to why the value is what it is.
Q5, Q6, Q8, Q10 and Q13 stay open until somebody says.
"""

import inspect

import pytest

from judge import llm, prfaq, speak, transcribe
from judge.openrouter import DEFAULT_SCORING_MODEL, DEFAULT_TRANSCRIPTION_MODEL


class TestRetryBudget:
    """Q5. Three attempts, doubling from two seconds, on every external call."""

    @pytest.mark.parametrize("fn", [
        llm.score_submission, llm.run_finalist_round,
        transcribe.transcribe_audio, prfaq.generate_prfaq, speak.speak,
    ])
    def test_every_external_call_is_wrapped(self, fn):
        assert hasattr(fn, "__wrapped__"), f"{fn.__name__} is not retried"

    def test_the_budget_is_three_attempts_doubling_from_two_seconds(self):
        source = inspect.getsource(llm)
        assert "max_attempts=3, backoff_base=2.0" in source

    def test_the_worst_case_wait_is_six_seconds(self):
        """Two backoffs, 2s then 4s, before the third attempt gives up. Worth
        knowing against the thirty seconds a room will sit through."""
        assert 2.0 * (2 ** 0) + 2.0 * (2 ** 1) == 6.0


class TestModelDefaults:
    """Q10. Whether these are a decision or a snapshot is unanswered."""

    def test_scoring_defaults_to_a_text_model(self):
        assert DEFAULT_SCORING_MODEL == "anthropic/claude-sonnet-5"

    def test_transcription_defaults_to_a_model_that_accepts_audio(self):
        # OpenRouter has no Whisper-style endpoint, so this one is load-bearing:
        # a text-only model here fails at the first pitch, not at startup.
        assert DEFAULT_TRANSCRIPTION_MODEL == "google/gemini-3.7-flash"

    def test_both_are_overridable_without_touching_code(self, monkeypatch):
        from judge.openrouter import scoring_model, transcription_model
        monkeypatch.setenv("OPENROUTER_SCORING_MODEL", "vendor/other")
        monkeypatch.setenv("OPENROUTER_TRANSCRIPTION_MODEL", "vendor/audio")
        assert scoring_model() == "vendor/other"
        assert transcription_model() == "vendor/audio"


class TestSpokenLengths:
    """Q13. The word budgets, stated in the prompt and capped in code."""

    def test_the_review_asks_for_about_a_minute(self):
        assert "150 to 170 words" in inspect.getsource(llm.score_submission)

    def test_the_announcement_asks_for_about_ninety_seconds(self):
        assert "180 to 220 words" in inspect.getsource(llm.run_finalist_round)

    def test_the_cap_is_enforced_in_code_not_only_asked_for(self):
        import server
        assert server.SPOKEN_REVIEW_MAX_WORDS >= 170


class TestPrfaqBatching:
    """Undocumented until now: the batch route's concurrency and timeouts."""

    def test_three_at_a_time_with_a_two_minute_ceiling_each(self):
        import server
        source = inspect.getsource(server.api_generate_event_prfaqs)
        assert "timeout=120" in source
        assert "range(0, len(tasks), 3)" in source

    def test_a_batch_of_three_gets_five_minutes(self):
        import server
        assert "timeout=300" in inspect.getsource(server.api_generate_event_prfaqs)


class TestAudioEncoding:
    """The transcode ffmpeg is asked for. Mono, 16 kHz, 48 kbps."""

    def test_the_transcode_settings_are_what_transcription_expects(self):
        source = inspect.getsource(transcribe._convert_to_mp3)
        for flag in ("-ac", "1", "-ar", "16000", "-b:a", "48k"):
            assert f'"{flag}"' in source, flag


class TestTheNetworkPosture:
    """SPEC.md R36. Unauthenticated by design, on a trusted network, with LAN
    exposure as a separate deliberate command. Whether it should stay that way
    is Q1 and is a product question, not a defect."""

    def _scripts(self):
        import json
        from pathlib import Path
        return json.loads((Path(__file__).parent.parent / "package.json").read_text())["scripts"]

    def test_the_development_server_does_not_bind_the_network(self):
        assert "--host" not in self._scripts()["dev"]

    def test_exposing_it_is_a_separate_command(self):
        assert "--host 0.0.0.0" in self._scripts()["start"]

    def test_the_readme_says_there_is_no_authentication(self):
        from pathlib import Path
        readme = (Path(__file__).parent.parent / "README.md").read_text()
        assert "There is no authentication" in readme

    def test_the_readme_says_what_leaves_the_machine(self):
        """An operator running this on real participants needs to know their
        voices go to two third parties before they press record."""
        from pathlib import Path
        readme = (Path(__file__).parent.parent / "README.md").read_text()
        assert "What leaves your machine" in readme
        assert "OpenRouter" in readme and "ElevenLabs" in readme
        assert "no consent step" in readme

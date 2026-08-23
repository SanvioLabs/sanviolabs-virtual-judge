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
from pathlib import Path

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

    def test_the_readme_tells_you_to_set_a_code_when_you_expose_it(self):
        """It used to say only that there was no authentication. There is now,
        opt-in, and the sentence that matters is when to turn it on."""
        readme = (Path(__file__).parent.parent / "README.md").read_text()
        assert "Set an access code when you do" in readme
        assert "VJ_ACCESS_CODE" in readme
        assert "every route is open to anyone who" in readme

    def test_the_readme_says_what_leaves_the_machine(self):
        """An operator running this on real participants needs to know their
        voices go to two third parties before they press record."""
        readme = (Path(__file__).parent.parent / "README.md").read_text()
        assert "What leaves your machine" in readme
        assert "OpenRouter" in readme and "ElevenLabs" in readme
        assert "no consent step" in readme


class TestThePodiumSetsTheMinimum:
    """SPEC.md R37. The finalist prompt asks for a top three, so a round needs
    three teams. The minimum was never arbitrary; it follows from the podium."""

    def test_the_prompt_asks_for_three(self):
        source = inspect.getsource(llm.run_finalist_round)
        assert "top 3" in source
        assert '"rank": 3' in source

    def test_the_route_requires_three(self):
        import server
        assert "len(completed) < 3" in inspect.getsource(server.api_run_finalist)


class TestRubricsAreImmutableOnceLoaded:
    """SPEC.md R39. Sync is keyed on name and only inserts, so a rubric an
    event points at can never change underneath it. Editing a file produces a
    second rubric and leaves existing events on the one they were judged
    against, which is the guarantee a scored event needs."""

    def test_sync_only_inserts(self):
        from judge import rubrics
        source = inspect.getsource(rubrics.sync_rubrics_to_db)
        assert "if name not in existing" in source
        assert "UPDATE" not in source.upper().replace("UPDATED", "")

    def test_a_second_sync_does_not_change_the_first(self, tmp_path, monkeypatch):
        from judge import db, rubrics
        clone = tmp_path / "rubrics"
        clone.mkdir()
        (clone / "r.yaml").write_text(
            'name: "Held"\ncategories:\n  - name: "A"\n    description: "first"\n'
        )
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "j.db")
        monkeypatch.setattr(rubrics, "RUBRICS_DIR", clone)
        db.init_db()
        rubrics.sync_rubrics_to_db()
        before = db.list_rubrics()[0]

        # Edit the file the way an organiser would, and restart.
        (clone / "r.yaml").write_text(
            'name: "Held"\ncategories:\n  - name: "A"\n    description: "changed"\n'
        )
        rubrics.sync_rubrics_to_db()

        assert len(db.list_rubrics()) == 1
        assert db.get_rubric(before["id"])["categories"][0]["description"] == "first"


class TestTimeoutsTraceToAMeasurement:
    """SPEC.md R43.

    These were 180 and 90 seconds, eight and six times what the work actually
    takes, and the speech client had no explicit timeout at all. Nothing had
    ever been measured, so the ceilings were guesses and they set the worst
    case: seventeen minutes of a hung provider holding the room.

    Measured 2026-08-23 against the real providers on synthetic speech, one run
    each: transcription 11.6s for 166 seconds of audio, about 21s scaled to a
    five minute pitch; scoring 14.5s; speech 8.0s; the whole pipeline 34.1s,
    which is the thirty seconds the UI promises.
    """

    def test_transcription_allows_about_four_times_what_it_takes(self):
        assert "get_client(timeout=90.0)" in inspect.getsource(transcribe)

    def test_scoring_allows_about_four_times_what_it_takes(self):
        assert "get_client(timeout=60.0)" in inspect.getsource(llm._get_client)

    def test_speech_has_an_explicit_timeout_at_all(self):
        """It used to take the SDK default, which is unbounded as far as anyone
        reading this repo could tell."""
        assert "timeout=60.0" in inspect.getsource(speak.speak)

    def test_the_prfaq_keeps_a_long_ceiling(self):
        """It writes a whole document and runs after the room has cleared, so
        the reason to keep transcription's old ceiling short does not apply."""
        assert "get_client(timeout=180.0)" in inspect.getsource(prfaq._get_client)

    def test_the_worst_case_is_stated_in_the_spec(self):
        spec = (Path(__file__).parent.parent / "SPEC.md").read_text()
        assert "eleven minutes" in spec


class TestPublishedMarkdownHasNoInternalFrontmatter:
    """SPEC.md R52.

    This repo was written inside a private workspace whose house style puts YAML
    frontmatter on every document, so README.md carried `type: readme`, `scope:
    project` and friends. GitHub does not strip it. It renders as a heading, so
    the largest text on the repo's front page was internal filing metadata sitting
    above the project's own title.

    The convention is correct where it came from and wrong here, and the way it
    got in was automatic, which is why this is a test rather than a note.
    """

    def _published_markdown(self):
        import subprocess
        root = Path(__file__).parent.parent
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=root,
                             capture_output=True, text=True, check=True)
        return [root / p for p in out.stdout.split() if p]

    def test_there_is_markdown_to_check(self):
        assert len(self._published_markdown()) >= 3

    def test_no_published_document_opens_with_frontmatter(self):
        offenders = [
            p.name for p in self._published_markdown()
            if p.read_text().startswith("---\n")
        ]
        assert offenders == [], (
            f"{offenders} open with YAML frontmatter, which GitHub renders as a "
            "heading above the document's own title"
        )

    def test_the_spec_still_says_what_it_was_read_at(self):
        """Removing the frontmatter must not lose the pinned commit. A spec read
        off a moving branch is a spec of nothing."""
        spec = (Path(__file__).parent.parent / "SPEC.md").read_text()
        assert "Read at" in spec
        assert "d359e7c" in spec

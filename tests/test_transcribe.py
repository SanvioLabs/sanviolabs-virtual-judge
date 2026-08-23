"""Tests for OpenRouter-backed transcription and the shared client helpers."""

import base64
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from judge.openrouter import (
    TruncatedResponse,
    UnparseableResponse,
    complete_json,
    extract_json,
    message_content,
    scoring_model,
    transcription_model,
)
from judge.transcribe import _encode_audio, transcribe_audio


def _mock_response(text: str):
    mock = MagicMock()
    mock.choices = [MagicMock(message=MagicMock(content=text))]
    return mock


def _write_fake_mp3(path, size: int = 4096):
    path.write_bytes(b"\xff\xfb" + b"\x00" * (size - 2))
    return path


class TestEncodeAudio:
    def test_native_format_is_read_directly(self, tmp_path):
        mp3 = _write_fake_mp3(tmp_path / "pitch.mp3")
        data, fmt = _encode_audio(mp3)
        assert fmt == "mp3"
        assert base64.b64decode(data) == mp3.read_bytes()

    def test_webm_is_converted_to_mp3(self, tmp_path):
        webm = tmp_path / "pitch.webm"
        webm.write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 5000)
        converted = tmp_path / "pitch.mp3"

        def fake_ffmpeg(cmd, **kwargs):
            _write_fake_mp3(converted)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("judge.transcribe.shutil.which", return_value="/usr/local/bin/ffmpeg"), \
             patch("judge.transcribe.subprocess.run", side_effect=fake_ffmpeg):
            _data, fmt = _encode_audio(webm)

        assert fmt == "mp3"
        # The converted file is kept so the export bundle has playable pitch audio.
        assert converted.exists()

    def test_missing_ffmpeg_gives_actionable_error(self, tmp_path):
        webm = tmp_path / "pitch.webm"
        webm.write_bytes(b"\x00" * 5000)
        with patch("judge.transcribe.shutil.which", return_value=None), \
             pytest.raises(RuntimeError, match="ffmpeg is required"):
                _encode_audio(webm)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="Audio file not found"):
            _encode_audio(tmp_path / "nope.mp3")

    def test_empty_recording_raises(self, tmp_path):
        tiny = tmp_path / "pitch.mp3"
        tiny.write_bytes(b"\x00" * 10)
        with pytest.raises(RuntimeError, match="empty or too short"):
            _encode_audio(tiny)


class TestTranscribeAudio:
    @patch("judge.transcribe.get_client")
    def test_returns_transcript(self, mock_client, tmp_path):
        mp3 = _write_fake_mp3(tmp_path / "pitch.mp3")
        mock_client.return_value.chat.completions.create.return_value = _mock_response(
            "  We built an AI tool for radiologists.  "
        )

        assert transcribe_audio(mp3) == "We built an AI tool for radiologists."

    @patch("judge.transcribe.get_client")
    def test_sends_audio_as_input_audio_part(self, mock_client, tmp_path):
        mp3 = _write_fake_mp3(tmp_path / "pitch.mp3")
        mock_client.return_value.chat.completions.create.return_value = _mock_response("Hi.")

        transcribe_audio(mp3)

        kwargs = mock_client.return_value.chat.completions.create.call_args.kwargs
        parts = kwargs["messages"][-1]["content"]
        audio_part = next(p for p in parts if p["type"] == "input_audio")
        assert audio_part["input_audio"]["format"] == "mp3"
        assert base64.b64decode(audio_part["input_audio"]["data"]) == mp3.read_bytes()

    @patch("judge.transcribe.get_client")
    def test_silent_recording_raises(self, mock_client, tmp_path):
        mp3 = _write_fake_mp3(tmp_path / "pitch.mp3")
        mock_client.return_value.chat.completions.create.return_value = _mock_response("   ")

        with pytest.raises(RuntimeError, match="no text"):
            transcribe_audio(mp3)


class TestExtractJson:
    def test_bare_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_json_fence(self):
        assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}

    def test_bare_fence(self):
        assert extract_json('```\n{"a": 3}\n```') == {"a": 3}

    def test_prose_wrapped_json(self):
        assert extract_json('Sure! Here you go:\n{"a": 4}\nHope that helps.') == {"a": 4}

    def test_empty_response_raises(self):
        with pytest.raises(ValueError, match="empty response"):
            extract_json("")

    def test_unparseable_raises(self):
        with pytest.raises(UnparseableResponse, match="Could not parse JSON"):
            extract_json("I refuse to answer.")

    def test_a_document_cut_off_midway_reads_as_truncated(self):
        """The failure that used to surface as a syntax error hundreds of lines in.

        The old parser grabbed everything between the first `{` and the last `}`,
        which on a half-written document is some inner object's closing brace. The
        result was a JSON syntax error pointing at a line that was perfectly fine.
        """
        cut = '{"a": 1, "items": [{"q": "one", "b": "two"}, {"q": "three"'
        with pytest.raises(TruncatedResponse, match="stopped partway"):
            extract_json(cut)

    def test_a_brace_inside_a_string_does_not_look_like_truncation(self):
        assert extract_json('{"a": "a } and a { in prose"}') == {"a": "a } and a { in prose"}

    def test_trailing_prose_after_a_complete_object_still_parses(self):
        assert extract_json('{"a": {"b": 1}}\n\nLet me know if you want changes.') == {"a": {"b": 1}}


class _Choice:
    def __init__(self, content, finish_reason):
        self.message = type("M", (), {"content": content})()
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, content, finish_reason="stop", completion_tokens=None):
        self.choices = [_Choice(content, finish_reason)]
        self.usage = type("U", (), {"completion_tokens": completion_tokens})()


class TestMessageContent:
    def test_returns_the_text_on_a_normal_finish(self):
        assert message_content(_Response("hello")) == "hello"

    def test_refuses_a_response_that_hit_the_token_ceiling(self):
        """finish_reason is the only honest signal that the budget ran out.

        Reasoning models spend part of max_tokens before emitting anything, so a
        ceiling that clears the finished document can still cut it off.
        """
        with pytest.raises(TruncatedResponse, match="ran out of output budget"):
            message_content(_Response('{"a": 1', finish_reason="length"), "PRFAQ")

    def test_the_truncation_message_names_what_was_being_written(self):
        with pytest.raises(TruncatedResponse, match="PRFAQ"):
            message_content(_Response("x", finish_reason="length"), "PRFAQ")

    def test_the_truncation_message_reports_the_spend(self):
        with pytest.raises(TruncatedResponse, match="used 8000 completion tokens"):
            message_content(_Response("x", "length", completion_tokens=8000))


class TestCompleteJson:
    def _client(self, response):
        client = MagicMock()
        client.chat.completions.create.return_value = response
        return client

    def test_parses_a_good_response(self):
        client = self._client(_Response('{"a": 1}'))
        assert complete_json(client, "m", [], 100) == {"a": 1}

    def test_passes_the_budget_through(self):
        client = self._client(_Response('{"a": 1}'))
        complete_json(client, "m", [{"role": "user", "content": "hi"}], 16000)
        assert client.chat.completions.create.call_args.kwargs["max_tokens"] == 16000

    def test_a_truncated_completion_raises_rather_than_returning_half(self):
        client = self._client(_Response('{"a": 1, "b": ', finish_reason="length"))
        with pytest.raises(TruncatedResponse):
            complete_json(client, "m", [], 100, what="PRFAQ")


class TestModelSelection:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_SCORING_MODEL", raising=False)
        monkeypatch.delenv("OPENROUTER_TRANSCRIPTION_MODEL", raising=False)
        assert scoring_model() == "anthropic/claude-sonnet-5"
        assert transcription_model() == "google/gemini-3.7-flash"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_SCORING_MODEL", "openai/gpt-5.4")
        monkeypatch.setenv("OPENROUTER_TRANSCRIPTION_MODEL", "google/gemini-2.5-flash")
        assert scoring_model() == "openai/gpt-5.4"
        assert transcription_model() == "google/gemini-2.5-flash"

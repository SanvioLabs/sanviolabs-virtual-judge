"""Speech-to-text via OpenRouter.

OpenRouter has no Whisper-style `/audio/transcriptions` endpoint — audio goes
through chat completions as an `input_audio` content part, against a model that
accepts audio input (Gemini Flash by default).

The browser records WebM/Opus, which is not an accepted `input_audio` format, so
recordings are transcoded to mono 16 kHz MP3 with ffmpeg first. The converted
MP3 is kept alongside the original so the export bundle has playable pitch audio.
"""

import base64
import shutil
import subprocess
from pathlib import Path

from .openrouter import RETRYABLE, get_client, message_content, transcription_model
from .retry import retry

# Formats OpenRouter accepts directly as input_audio.
NATIVE_FORMATS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".aiff"}

TRANSCRIPTION_SYSTEM_PROMPT = (
    "You are a transcription engine. Transcribe the audio verbatim into plain text. "
    "Output only the transcript — no preamble, no commentary, no speaker labels, "
    "no timestamps, no markdown. If the audio contains no intelligible speech, "
    "output nothing at all."
)


def _convert_to_mp3(audio_path: Path) -> Path:
    """Transcode a recording to mono 16 kHz MP3 next to the original."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            f"ffmpeg is required to convert {audio_path.suffix} recordings for "
            "transcription. Install it with: brew install ffmpeg"
        )

    out_path = audio_path.with_suffix(".mp3")
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio_path),
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        # The return code is inspected below, with ffmpeg's own stderr, which
        # says more than a CalledProcessError would.
        check=False,
    )
    if result.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"Audio conversion failed: {result.stderr.strip()[:300]}")

    return out_path


def _encode_audio(audio_path: str | Path) -> tuple[str, str]:
    """Return (base64 audio, format) ready for an input_audio content part."""
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise RuntimeError(f"Audio file not found: {audio_path}")

    if audio_path.suffix.lower() not in NATIVE_FORMATS:
        audio_path = _convert_to_mp3(audio_path)

    if audio_path.stat().st_size < 1024:
        raise RuntimeError("Recording is empty or too short to transcribe")

    data = base64.b64encode(audio_path.read_bytes()).decode()
    return data, audio_path.suffix.lower().lstrip(".")


@retry(max_attempts=3, backoff_base=2.0, retryable_exceptions=RETRYABLE)
def transcribe_audio(audio_path: str | Path) -> str:
    """Transcribe an audio file.

    Retries up to 3 times on transient failures (timeout, connection, rate limit,
    upstream 5xx).

    Args:
        audio_path: Path to the audio file (webm, mp3, wav, etc.)

    Returns:
        The transcribed text.
    """
    audio_b64, audio_format = _encode_audio(audio_path)

    client = get_client(timeout=180.0)
    response = client.chat.completions.create(
        model=transcription_model(),
        max_tokens=8000,
        messages=[
            {"role": "system", "content": TRANSCRIPTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this pitch recording verbatim."},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": audio_format},
                    },
                ],
            },
        ],
    )

    # A truncated transcript is the quietest failure in the system: the pitch just
    # stops, and everything downstream scores a partial pitch without knowing it.
    transcript = message_content(response, "transcript").strip()
    if not transcript:
        raise RuntimeError(
            "Transcription returned no text — the recording may be silent or inaudible"
        )

    return transcript

"""Text-to-speech via ElevenLabs."""

import os
from pathlib import Path

from elevenlabs import ElevenLabs
from elevenlabs.core import ApiError

from .retry import retry


@retry(max_attempts=3, backoff_base=2.0, retryable_exceptions=(ApiError, ConnectionError, TimeoutError))
def speak(text: str, output_path: str | Path) -> Path:
    """Generate speech from text and save to file.

    Retries up to 3 times on transient failures.

    Args:
        text: The text to speak.
        output_path: Where to save the audio file.

    Returns:
        Path to the generated audio file.
    """
    # Explicit rather than the SDK default, which was unknown and therefore
    # unbounded as far as anyone reading this could tell. Measured at 8.0s for a
    # 160 word review.
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=60.0)
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Default: Rachel

    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.writelines(audio_generator)

    return output_path

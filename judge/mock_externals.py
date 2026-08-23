"""Mock external services for E2E testing.

When MOCK_EXTERNALS=true is set, the server uses these instead of real API calls.
Returns deterministic responses based on the test fixtures.

- Transcription: returns canned 5-minute pitch transcripts
- Scoring: returns canned LLM scores and rationale
- TTS: uses edge-tts (Microsoft Edge neural voices) for real playable audio
"""

import asyncio
from pathlib import Path

# Import fixtures from tests
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))
from fixtures.pitches import TEAMS, MOCK_FINALIST_RESULT


# Track which submission maps to which team (set by the mock transcriber)
_submission_team_map: dict[str, str] = {}


def mock_transcribe_audio(audio_path: str | Path) -> str:
    """Return a canned transcript and optionally generate TTS audio of it.

    The first submission gets NovaMind, second gets ContextCraft, third gets YOLOship.
    After that it cycles.

    With MOCK_TTS_FULL=true: also generates edge-tts MP3 of the pitch transcript
    so the export folder has listenable pitch recordings.
    Without: just returns the transcript text (fast, for Playwright/CI).
    """
    import os

    team_names = list(TEAMS.keys())
    index = len(_submission_team_map) % len(team_names)
    team_name = team_names[index]

    # Map this audio path to the team for later score lookup
    _submission_team_map[str(audio_path)] = team_name

    transcript = TEAMS[team_name]["transcript"]

    # Generate TTS of the pitch only in full mode
    if os.environ.get("MOCK_TTS_FULL"):
        audio_path = Path(audio_path)
        mp3_path = audio_path.with_suffix(".mp3")
        try:
            _edge_tts_generate(
                transcript.strip(),
                mp3_path,
                voice="en-US-AriaNeural",  # Different voice for pitches
                max_chars=5000,
            )
        except Exception as e:
            import sys
            print(f"Warning: pitch TTS failed for {team_name}: {e}", file=sys.stderr)

    return transcript


def mock_score_submission(transcript: str, rubric: dict) -> dict:
    """Return canned scores based on which transcript this matches."""
    for team_name, data in TEAMS.items():
        # Match on a distinctive phrase from each pitch
        if team_name == "NovaMind" and "MedScribe" in transcript:
            return data["scores"]
        elif team_name == "ContextCraft" and "ThreadWeaver" in transcript:
            return data["scores"]
        elif team_name == "YOLOship" and "VibeCoder" in transcript:
            return data["scores"]

    # Fallback — return the first team's scores
    return list(TEAMS.values())[0]["scores"]


def mock_speak(text: str, output_path: str | Path) -> Path:
    """Generate speech audio.

    - With MOCK_TTS_FULL=true: Uses edge-tts for real playable MP3 files (for export/sharing)
    - Without: Generates a minimal silent WAV (fast, for Playwright/CI tests)
    """
    import os

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if os.environ.get("MOCK_TTS_FULL"):
        _edge_tts_generate(text, output_path, voice="en-US-GuyNeural", max_chars=5000)
    else:
        _write_silent_wav(output_path)

    return output_path


def _edge_tts_generate(text: str, output_path: Path, voice: str = "en-US-GuyNeural", max_chars: int = 5000):
    """Generate real speech via edge-tts in a background thread."""
    import edge_tts
    import threading

    tts_text = text[:max_chars]
    if len(text) > max_chars:
        tts_text += "... End of review."

    async def _generate():
        communicate = edge_tts.Communicate(tts_text, voice)
        await communicate.save(str(output_path))

    exception_holder = [None]
    def _run():
        try:
            asyncio.run(_generate())
        except Exception as e:
            exception_holder[0] = e

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=120)

    if exception_holder[0]:
        raise exception_holder[0]


def _write_silent_wav(output_path: Path):
    """Write a minimal valid audio file (0.5s silence) for fast tests."""
    import struct
    import wave

    sample_rate = 22050
    n_samples = int(sample_rate * 0.5)
    with wave.open(str(output_path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))


def mock_run_finalist_round(submissions: list[dict], rubric: dict) -> dict:
    """Return canned finalist results."""
    result = {
        "top_picks": [],
        "reasoning": MOCK_FINALIST_RESULT["reasoning"],
        "spoken_announcement": MOCK_FINALIST_RESULT["spoken_announcement"],
    }

    # Use actual team names in order of their overall scores (descending)
    sorted_subs = sorted(submissions, key=lambda s: s["overall_score"], reverse=True)
    for i, sub in enumerate(sorted_subs[:3]):
        result["top_picks"].append({
            "rank": i + 1,
            "team_name": sub["team_name"],
            "reasoning": MOCK_FINALIST_RESULT["top_picks"][i]["reasoning"],
        })

    return result


def mock_generate_prfaq(team_name: str, transcript: str, event_name: str = "") -> dict:
    """Return a canned PRFAQ shaped exactly like the real generator's output.

    Deliberately grades every assumption Untested — that is the honest outcome for
    a pitch, and a fixture that grades generously would let a regression in the
    real prompt's calibration slip through the export tests. `team_quote` is null
    for the same reason: most pitches carry no founding account, the placeholder
    is the correct output, and a fixture that always supplies a quote would never
    exercise it.
    """
    product = team_name.strip() or "The Product"
    return {
        "product_name": product,
        "one_liner": f"{product} gives its users back the hours they were losing to manual work.",
        "press_release": {
            "headline": f"{product} launches, cutting a nightly two-hour task to minutes",
            "subheadline": f"{product} is for practitioners who spend their evenings on work a machine should have done.",
            "summary": f"{product} takes the raw material of the job and turns it into the finished artifact automatically.",
            "problem": "Practitioners lose hours every night to work that is necessary, repetitive, and unrewarding.",
            "solution": "The product watches the work as it happens and produces the artifact from it directly, rather than asking the user to re-enter what they already did.",
            "differentiators": [
                {
                    "name": "It runs during the work, not after it.",
                    "why": "Every incumbent starts from a finished record and reconstructs what happened. Starting during the task is what removes the re-entry step rather than speeding it up.",
                },
                {
                    "name": "It reads the systems the practitioner already uses.",
                    "why": "No new place to type. The integration is the product, and it is the reason adoption does not depend on changing anybody's habits.",
                },
            ],
            "getting_started": "Sign in, connect the system you already use, and run one real task through it.",
            "launch_timing": "March 2027",
            "closing": "Practitioners can start with one real task from the account they already have.",
            "team_quote": None,
            "customer_quote": {
                "name": "Dana Ruiz",
                "role": "Practitioner, mid-sized practice",
                "quote": "I finished at the time I was supposed to finish. That had not happened in a year.",
            },
        },
        "customer_faq": [
            {"question": "What does it cost?", "answer": "Pricing scales with the volume of work it handles."},
            {"question": "What happens to my data?", "answer": "Data stays in your account and is not used to train anything."},
            {"question": "What happens when it gets something wrong?", "answer": "Every output is editable before it is committed, and corrections are kept."},
            {"question": "What does it not do?", "answer": "It does not make the judgement call. It prepares the artifact and hands it back."},
            {"question": "How is this different from the incumbent?", "answer": "The incumbent starts after the work is done. This starts during it."},
            {"question": "How do I try it?", "answer": "Run one real task through it end to end before committing to anything."},
        ],
        "hard_faq": [
            {
                "question": "What happens the first time the output is wrong in a way the user does not catch?",
                "why_it_bites": "A single uncaught error in front of a paying customer ends the account and the reference.",
                "what_settles_it": "An error-rate measurement on real work, with the method and sample size written down.",
            },
            {
                "question": "Why will not the incumbent ship this in a quarter?",
                "why_it_bites": "An acquirer or investor asks this before any term sheet.",
                "what_settles_it": "A named, defensible reason — data access, workflow position, or a switching cost the incumbent cannot replicate.",
            },
            {
                "question": "Does anyone actually pay for this, or do they just like the demo?",
                "why_it_bites": "Demo enthusiasm and purchase intent look identical until an invoice is sent.",
                "what_settles_it": "One signed paid contract, or a letter of intent with a price on it.",
            },
        ],
        "assumptions": [
            {
                "assumption": "The task really does take users two hours a night.",
                "grade": "Untested",
                "evidence": "Stated in the pitch. Nobody has timed a real user.",
            },
            {
                "assumption": "The output is accurate enough to be used without full review.",
                "grade": "Untested",
                "evidence": "Demonstrated once on a prepared example. No error rate on real work exists.",
            },
            {
                "assumption": "Users will connect the system that holds their existing data.",
                "grade": "Untested",
                "evidence": "Asserted. No user has completed the connection outside the team.",
            },
            {
                "assumption": "There is a price at which this is worth buying.",
                "grade": "Untested",
                "evidence": "No price was named and no purchase intent has been tested. Nothing else in this ledger about demand can be tested until a number exists to test against.",
                "cheapest_to_close": True,
            },
            {
                "assumption": "The incumbent will not close this gap quickly.",
                "grade": "Untested",
                "evidence": "Inferred from the incumbent's current product, not from anything they have said or done.",
            },
            {
                "assumption": "The approach holds up outside the demo case.",
                "grade": "Untested",
                "evidence": "One case shown. Scale, edge cases, and failure behaviour are unestablished.",
            },
        ],
        "would_change_our_mind": [
            {
                "signal": "Fewer than one in four users who connect their data run a second task within a week.",
                "how_measured": "Across the first forty accounts that complete the connection, counted over the seven days after their first task.",
                "why_it_matters": "A first task is curiosity and a second is intent. Below that line the product is a demo people enjoyed rather than a tool they adopted, and the fix is the workflow, not the funnel.",
            },
            {
                "signal": "Measured error rate on real work exceeds one in twenty outputs.",
                "how_measured": "A sample of one hundred real outputs, checked against what the user would have produced by hand, scored by someone who did not build the product.",
                "why_it_matters": "Above that rate a user has to review everything, which restores the work the product exists to remove. The claim to abandon is unattended use, not accuracy.",
            },
            {
                "signal": "The incumbent ships an equivalent feature before the first paid contract is signed.",
                "how_measured": "Their public release notes, checked at the point the first invoice would go out.",
                "why_it_matters": "It would mean the gap was a roadmap item rather than a moat, and the remaining advantage has to come from somewhere other than being first.",
            },
        ],
    }


def reset():
    """Reset mock state between test runs."""
    _submission_team_map.clear()

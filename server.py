"""Virtual Judge — FastAPI server."""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from pydantic import BaseModel

from judge import db, openrouter
from judge.rubrics import sync_rubrics_to_db, get_default_rubric_id

# Mock mode: when MOCK_EXTERNALS=true, use canned responses instead of real API calls.
# This enables full E2E testing without API keys or network access.
if os.environ.get("MOCK_EXTERNALS", "").lower() in ("true", "1", "yes"):
    from judge.mock_externals import (
        mock_transcribe_audio as transcribe_audio,
        mock_score_submission as score_submission,
        mock_speak as speak,
        mock_run_finalist_round as run_finalist_round,
        mock_generate_prfaq as generate_prfaq,
    )
else:
    from judge.transcribe import transcribe_audio
    from judge.llm import score_submission, run_finalist_round
    from judge.speak import speak
    from judge.prfaq import generate_prfaq

# Rendering is deterministic either way — the disclaimer and provenance blocks are
# written in Python, so mock mode exercises the same document the event produces.
from judge.prfaq import prfaq_model, render_markdown as render_prfaq_markdown

# Load .env file if present
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            # Strip inline comments (# after the value)
            if "#" in value:
                value = value[:value.index("#")]
            value = value.strip()
            # Remove surrounding quotes if present
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if value:
                os.environ.setdefault(key, value)


logger = logging.getLogger(__name__)

# A five minute pitch is a couple of megabytes. This is a ceiling against a
# runaway or hostile upload, not a limit anyone should meet.
MAX_UPLOAD_BYTES = int(os.environ.get("VJ_MAX_UPLOAD_MB", "100")) * 1024 * 1024

AUDIO_DIR = Path(__file__).parent / "audio_recordings"
AUDIO_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and load rubrics on startup."""
    db.init_db()
    sync_rubrics_to_db()
    yield


app = FastAPI(title="Virtual Judge", version="0.2.0", lifespan=lifespan)

# Serve static files (frontend)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")


# --- Models ---

class NewEvent(BaseModel):
    name: str
    rubric_id: str | None = None
    description: str = ""


class NewSubmission(BaseModel):
    team_name: str
    event_id: str


# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main UI."""
    index_path = Path(__file__).parent / "static" / "index.html"
    return index_path.read_text()


_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(value: str, fallback: str = "unnamed") -> str:
    """Reduce a caller-supplied name to one safe path or filename segment.

    Team and event names are typed by whoever is running the room, and they reach
    both the filesystem and the Content-Disposition header. A name carrying a
    slash, a "..", or a newline would write outside the export folder or split the
    response header. Anything outside a conservative allowlist becomes "_".
    """
    cleaned = _UNSAFE_PATH_CHARS.sub("_", (value or "").strip()).strip("._-")
    if not cleaned:
        return fallback
    return cleaned[:80]


# Excel and Sheets treat a leading =, +, - or @ as the start of a formula, and
# a team name is typed by whoever is at the keyboard, or posted by anyone on the
# network since the API has no auth. The results CSV gets mailed around after
# the event, so a cell has to stay a cell.
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value):
    """Neutralise a spreadsheet formula without changing what the text says."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if text.startswith(_FORMULA_LEADERS):
        return "'" + text
    return text


def _norm_category(name: str) -> str:
    """Fold a category name for matching. The model retypes the name rather than
    echoing an id, so case and spacing drift."""
    return " ".join(str(name or "").split()).lower()


def _overall_score(scores: list[dict], rubric: dict) -> tuple[float, list[str]]:
    """Weighted average over the categories the model actually returned.

    The numerator and the denominator have to describe the same set of
    categories. Dividing the scores that came back by the sum of *every* rubric
    weight reports a team that scored full marks in each category it was given
    as having scored less than that, and a model that invents a fifth category
    pushes the result above the scale's own maximum. Neither is visible in the
    output: the number just comes out wrong, and it is read to the room.

    Returns the score and the names of any categories that matched no rubric
    entry, so the caller can say so rather than silently discarding them.
    """
    weights = {_norm_category(c["name"]): c.get("weight", 1.0) for c in rubric["categories"]}

    weighted = 0.0
    total_weight = 0.0
    unmatched: list[str] = []

    for s in scores:
        weight = weights.get(_norm_category(s.get("category")))
        if weight is None:
            unmatched.append(s.get("category", ""))
            continue
        weighted += s["score"] * weight
        total_weight += weight

    if total_weight == 0:
        raise ValueError(
            "The judge returned no category matching the rubric "
            f"(got {[s.get('category') for s in scores]}, "
            f"expected {[c['name'] for c in rubric['categories']]})"
        )

    return weighted / total_weight, unmatched


def _key_present(name: str) -> bool:
    """True only if the key is set to something that isn't a placeholder.

    `.env` starts life as a copy of `.env.example`, so a bare presence check
    reports "ok" while every API call 401s. Reject the example values.
    """
    value = (os.environ.get(name) or "").strip()
    if not value:
        return False
    return "..." not in value and not value.lower().startswith("your")


@app.get("/api/health")
async def health(verify: bool = False):
    """Health check — verify the server is running and keys are configured.

    Pass `?verify=1` to make a live call against each provider. Do this once
    before an event: presence of a key says nothing about whether it works.
    """
    keys = {
        "openrouter": _key_present("OPENROUTER_API_KEY"),
        "elevenlabs": _key_present("ELEVENLABS_API_KEY"),
    }
    all_configured = all(keys.values())

    result = {
        "status": "ok" if all_configured else "missing_keys",
        "keys_configured": keys,
        "models": {
            "scoring": openrouter.scoring_model(),
            "transcription": openrouter.transcription_model(),
        },
        "rubrics_loaded": len(db.list_rubrics()),
        "events_count": len(db.list_events()),
    }

    if verify:
        result["verified"] = _verify_providers()
        if not all(v["ok"] for v in result["verified"].values()):
            result["status"] = "key_check_failed"

    return result


def _verify_providers() -> dict:
    """Make a minimal live call to each provider to confirm the keys work."""
    checks = {}

    try:
        client = openrouter.get_client(timeout=30.0)
        client.chat.completions.create(
            model=openrouter.scoring_model(),
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with: ok"}],
        )
        checks["openrouter"] = {"ok": True, "detail": openrouter.scoring_model()}
    except KeyError:
        checks["openrouter"] = {"ok": False, "detail": "OPENROUTER_API_KEY not set"}
    except Exception as e:
        checks["openrouter"] = {"ok": False, "detail": str(e)[:200]}

    try:
        # Synthesize two words rather than reading voice metadata — TTS is the
        # operation the app actually performs, and API keys are scoped per
        # permission, so a metadata read can pass while synthesis fails.
        from judge.speak import speak

        probe = AUDIO_DIR / "_healthcheck.mp3"
        speak("Judge ready.", probe)
        size = probe.stat().st_size
        probe.unlink(missing_ok=True)
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        checks["elevenlabs"] = {"ok": size > 100, "detail": f"voice {voice_id}, {size} bytes"}
    except KeyError:
        checks["elevenlabs"] = {"ok": False, "detail": "ELEVENLABS_API_KEY not set"}
    except Exception as e:
        checks["elevenlabs"] = {"ok": False, "detail": str(e)[:200]}

    return checks


# --- Events ---

@app.get("/api/events")
async def api_list_events():
    """List all events (hackathons)."""
    events = db.list_events()
    # One grouped query for every count, rather than a query per event. This
    # route fills the dropdown on every page load.
    counts = db.submission_counts_by_event()
    for e in events:
        c = counts.get(e["id"], {"submission_count": 0, "completed_count": 0})
        e["submission_count"] = c["submission_count"]
        e["completed_count"] = c["completed_count"]
    return events


@app.post("/api/events")
async def api_create_event(body: NewEvent):
    """Create a new event (hackathon)."""
    rubric_id = body.rubric_id or get_default_rubric_id()
    event_id = db.create_event(name=body.name, rubric_id=rubric_id, description=body.description)
    return {"id": event_id, "name": body.name, "rubric_id": rubric_id}


@app.get("/api/events/{event_id}")
async def api_get_event(event_id: str):
    """Get event details with submission summary."""
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    subs = db.list_submissions(event_id=event_id)
    rubric = db.get_rubric(event["rubric_id"])
    return {
        **event,
        "rubric": rubric,
        "submission_count": len(subs),
        "completed_count": len([s for s in subs if s["status"] == "complete"]),
    }


def _remove_audio_files(paths: list[str], *extra: Path) -> int:
    """Delete recordings for something that no longer exists.

    Best effort by design. A missing file is the desired end state, and a
    delete that half succeeds should not leave the row behind.
    """
    removed = 0
    candidates = [Path(p) for p in paths if p] + list(extra)
    for path in candidates:
        # The originals are .webm and the transcoded copies sit beside them.
        for candidate in {path, path.with_suffix(".mp3"), path.with_suffix(".webm")}:
            try:
                if candidate.is_file() and candidate.parent == AUDIO_DIR:
                    candidate.unlink()
                    removed += 1
            except OSError as e:
                logger.warning("Could not remove %s: %s", candidate, e)
    return removed


@app.delete("/api/submissions/{sub_id}")
async def api_delete_submission(sub_id: str):
    """Delete one submission, its scores, review, PRFAQ and recordings.

    Someone will start a recording on the wrong team. Until this existed the
    only remedy was editing the database by hand or resetting the event.
    """
    try:
        audio_paths = db.delete_submission(sub_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Submission not found")

    removed = _remove_audio_files(audio_paths, AUDIO_DIR / f"{sub_id}_review.mp3")
    return {"deleted": sub_id, "audio_files_removed": removed}


@app.delete("/api/events/{event_id}")
async def api_delete_event(event_id: str):
    """Delete an event and everything recorded under it.

    This is not recoverable. Export the bundle first if the results matter.
    """
    try:
        audio_paths = db.delete_event(event_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Event not found")

    removed = _remove_audio_files(audio_paths, AUDIO_DIR / f"finalist_{event_id[:8]}.mp3")
    return {"deleted": event_id, "audio_files_removed": removed}


# --- Rubrics ---

@app.get("/api/rubrics")
async def api_list_rubrics():
    """List all available rubrics."""
    return db.list_rubrics()


# --- Submissions ---

@app.post("/api/submissions")
async def api_create_submission(body: NewSubmission):
    """Start a new submission within an event."""
    event = db.get_event(body.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    sub_id = db.create_submission(
        team_name=body.team_name,
        event_id=body.event_id,
        rubric_id=event["rubric_id"],
    )
    return {"id": sub_id, "team_name": body.team_name, "event_id": body.event_id, "status": "recording"}


@app.post("/api/submissions/{sub_id}/audio")
async def api_upload_audio(sub_id: str, file: UploadFile):
    """Upload recorded audio for a submission."""
    submission = db.get_submission(sub_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Streamed with a ceiling rather than read whole. A pitch is a couple of
    # megabytes; the previous read() pulled whatever arrived into memory before
    # anything looked at its size.
    audio_path = AUDIO_DIR / f"{sub_id}.webm"
    written = 0
    try:
        with open(audio_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise ValueError("too large")
                f.write(chunk)
    except ValueError:
        audio_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"Recording is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    if written == 0:
        audio_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded recording is empty")

    db.update_submission(sub_id, audio_path=str(audio_path), status="transcribing")
    return {"status": "uploaded", "audio_path": str(audio_path)}


@app.post("/api/submissions/{sub_id}/judge")
async def api_judge_submission(sub_id: str):
    """Run the full judging pipeline: transcribe → score → generate review audio.

    Every external step runs on a worker thread. They are synchronous, they take
    roughly thirty seconds together, and retry backoff can stretch that into
    minutes. Called directly they would hold the event loop for the whole run,
    which freezes the UI and every other viewer on the network at exactly the
    moment the room is waiting on a result.
    """
    submission = db.get_submission(sub_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if not submission["audio_path"]:
        raise HTTPException(status_code=400, detail="No audio uploaded yet")

    rubric = db.get_rubric(submission["rubric_id"])
    if not rubric:
        raise HTTPException(status_code=400, detail="Rubric not found")

    # Step 1: Transcribe
    db.update_submission(sub_id, status="transcribing")
    try:
        transcript = await asyncio.to_thread(transcribe_audio, submission["audio_path"])
    except KeyError:
        db.update_submission(sub_id, status="error")
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured — check your .env file")
    except Exception as e:
        db.update_submission(sub_id, status="error")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    db.update_submission(sub_id, transcript=transcript, status="scoring")

    # Step 2: LLM scoring
    try:
        result = await asyncio.to_thread(score_submission, transcript, rubric)
    except KeyError:
        db.update_submission(sub_id, status="error")
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured — check your .env file")
    except Exception as e:
        db.update_submission(sub_id, status="error")
        raise HTTPException(status_code=500, detail=f"Scoring failed: {e}")

    db.save_scores(sub_id, result["scores"])

    # Overall score, averaged over the categories that were actually scored.
    try:
        overall, unmatched_categories = _overall_score(result["scores"], rubric)
    except ValueError as e:
        db.update_submission(sub_id, status="error")
        raise HTTPException(status_code=500, detail=str(e))
    if unmatched_categories:
        logger.warning(
            "Submission %s: judge returned categories not in the rubric, excluded from the "
            "overall score: %s", sub_id, unmatched_categories,
        )

    # Step 3: Generate spoken review
    review_text = _format_review_for_speech(
        submission["team_name"],
        result["scores"],
        overall,
        result["summary"],
        rubric,
        result.get("spoken_review"),
    )
    audio_out = AUDIO_DIR / f"{sub_id}_review.mp3"

    db.update_submission(sub_id, status="speaking")
    try:
        await asyncio.to_thread(speak, review_text, audio_out)
    except KeyError:
        db.update_submission(sub_id, status="error")
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY not configured — check your .env file")
    except Exception as e:
        db.update_submission(sub_id, status="error")
        raise HTTPException(status_code=500, detail=f"Text-to-speech failed: {e}")

    # Save review
    db.save_review(sub_id, overall, result["summary"], str(audio_out), review_text)
    db.update_submission(sub_id, status="complete")

    return {
        "status": "complete",
        "transcript": transcript,
        "scores": result["scores"],
        "overall_score": round(overall, 2),
        "summary": result["summary"],
        "spoken_review": review_text,
        "review_audio": f"/audio/{sub_id}_review.mp3",
        **({"unmatched_categories": unmatched_categories} if unmatched_categories else {}),
    }


@app.get("/api/events/{event_id}/submissions")
async def api_list_event_submissions(event_id: str):
    """List all submissions for an event with scores and reviews."""
    submissions = db.list_submissions(event_id=event_id)
    results = []
    for sub in submissions:
        scores = db.get_scores(sub["id"])
        review = db.get_review(sub["id"])
        results.append({
            **sub,
            "scores": scores,
            "review": review,
            # Flag only — the full document is several thousand words, and this
            # list renders after every team pitches.
            "has_prfaq": db.get_prfaq(sub["id"]) is not None,
        })
    return results


@app.get("/api/submissions/{sub_id}")
async def api_get_submission(sub_id: str):
    """Get a single submission with scores and review."""
    sub = db.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    scores = db.get_scores(sub_id)
    review = db.get_review(sub_id)
    return {**sub, "scores": scores, "review": review, "has_prfaq": db.get_prfaq(sub_id) is not None}


# --- PRFAQ ---

def _build_prfaq(sub: dict, event: dict) -> dict:
    """Generate and store the PRFAQ for one submission. Returns the stored row.

    Raises HTTPException — this runs inside request handlers for both the single
    and the batch route, and both want the same errors.
    """
    if not sub.get("transcript"):
        raise HTTPException(
            status_code=400,
            detail="No transcript yet — judge the submission before generating a PRFAQ",
        )

    try:
        content = generate_prfaq(sub["team_name"], sub["transcript"], event["name"] if event else "")
    except KeyError:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured — check your .env file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PRFAQ generation failed: {e}")

    model = prfaq_model()
    markdown = render_prfaq_markdown(
        content,
        sub["team_name"],
        event_name=event["name"] if event else "",
        model=model,
    )
    db.save_prfaq(sub["id"], content, markdown, model)
    return {"submission_id": sub["id"], "team_name": sub["team_name"],
            "content": content, "markdown": markdown, "model": model}


@app.post("/api/submissions/{sub_id}/prfaq")
async def api_generate_prfaq(sub_id: str, force: bool = False):
    """Write the Working Backwards PRFAQ for one team from their pitch transcript.

    Deliberately **not** part of the live judging pipeline. Generating this takes
    considerably longer than the ~30 seconds a room will sit through between
    teams, and nothing about it needs to happen while the team is standing there.
    Run it after the event, or between teams if you have the slack.

    Returns the existing document unless `force=1`.
    """
    sub = db.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    if not force:
        existing = db.get_prfaq(sub_id)
        if existing:
            return {
                "submission_id": sub_id,
                "team_name": sub["team_name"],
                "content": existing["content"],
                "markdown": existing["markdown"],
                "model": existing["model"],
                "cached": True,
            }

    event = db.get_event(sub["event_id"])
    try:
        # Timeout: 120 seconds (2 minutes)
        result = await asyncio.wait_for(asyncio.to_thread(_build_prfaq, sub, event), timeout=120)
        return {**result, "cached": False}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="PRFAQ generation timed out (>120s) — try again")


@app.get("/api/submissions/{sub_id}/prfaq")
async def api_get_prfaq(sub_id: str):
    """Get a previously generated PRFAQ."""
    sub = db.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    prfaq = db.get_prfaq(sub_id)
    if not prfaq:
        raise HTTPException(status_code=404, detail="No PRFAQ generated for this submission yet")
    return {
        "submission_id": sub_id,
        "team_name": sub["team_name"],
        "content": prfaq["content"],
        "markdown": prfaq["markdown"],
        "model": prfaq["model"],
        "created_at": prfaq["created_at"],
    }


@app.get("/api/submissions/{sub_id}/prfaq/download")
async def api_download_prfaq(sub_id: str):
    """Download a PRFAQ as a Markdown file."""
    from tempfile import NamedTemporaryFile

    sub = db.get_submission(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    prfaq = db.get_prfaq(sub_id)
    if not prfaq:
        raise HTTPException(status_code=404, detail="No PRFAQ generated for this submission yet")

    # Create a temporary file with the PRFAQ markdown content
    with NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write(prfaq["markdown"])
        temp_path = f.name

    # Return the file with proper headers for download
    return FileResponse(
        path=temp_path,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=PRFAQ-{_safe_component(sub['team_name'], 'team')}.md"}
    )


@app.post("/api/events/{event_id}/prfaqs")
async def api_generate_event_prfaqs(event_id: str, force: bool = False):
    """Generate PRFAQs for every judged team in an event.

    One team failing does not stop the rest — a run that dies on team three leaves
    the other teams with nothing, which is the wrong trade when this is being run
    once, after the event, to produce the handout.
    """
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    generated, skipped, failed = [], [], []
    tasks = []

    # Collect all tasks first (don't await in the loop to avoid blocking)
    for sub in db.list_submissions(event_id=event_id):
        if not sub.get("transcript"):
            skipped.append({"team_name": sub["team_name"], "reason": "no transcript"})
            continue
        if not force and db.get_prfaq(sub["id"]):
            skipped.append({"team_name": sub["team_name"], "reason": "already generated"})
            continue

        # Run each PRFAQ generation in a thread to avoid blocking the event loop
        async def generate_one(s=sub, e=event):
            try:
                # Timeout per individual PRFAQ: 120 seconds (2 minutes)
                await asyncio.wait_for(asyncio.to_thread(_build_prfaq, s, e), timeout=120)
                generated.append(s["team_name"])
            except HTTPException as ex:
                failed.append({"team_name": s["team_name"], "reason": ex.detail})
            except asyncio.TimeoutError:
                failed.append({"team_name": s["team_name"], "reason": "timeout (took >120s)"})
            except Exception as ex:
                failed.append({"team_name": s["team_name"], "reason": str(ex)})

        tasks.append(generate_one())

    # Run up to 3 PRFAQs in parallel to avoid overwhelming the API
    # but still be able to generate multiple at once
    if tasks:
        for i in range(0, len(tasks), 3):
            chunk = tasks[i:i+3]
            try:
                await asyncio.wait_for(asyncio.gather(*chunk), timeout=300)
            except asyncio.TimeoutError:
                pass  # Individual timeouts are already caught above

    return {"generated": generated, "skipped": skipped, "failed": failed}


# --- Finalist ---

def _reconcile_top_picks(top_picks: list[dict], completed: list[dict]) -> list[dict]:
    """Check the podium against the teams that actually pitched.

    The finalist round asks a model to compare teams and hand back names as
    free text. Nothing downstream checked them, so a misspelling or an invented
    team went straight into the spoken announcement, the leaderboard and the
    export. This is the highest-stakes output the tool produces and it is read
    to a room, so the two failures are handled differently.

    A name that matches a real team once case and spacing are folded is
    rewritten to the registered spelling, silently, because that is formatting.
    A name matching no team at all, or the same team appearing twice, means the
    comparison is not trustworthy and the caller is told rather than the room.
    """
    by_norm = {_norm_category(s["team_name"]): s["team_name"] for s in completed}

    reconciled: list[dict] = []
    seen: set[str] = set()
    for pick in top_picks:
        real = by_norm.get(_norm_category(pick.get("team_name")))
        if real is None:
            raise ValueError(
                f"The finalist round named a team that did not pitch: "
                f"{pick.get('team_name')!r}. Run it again."
            )
        if real in seen:
            raise ValueError(
                f"The finalist round placed {real!r} twice. Run it again."
            )
        seen.add(real)
        reconciled.append({**pick, "team_name": real})

    return reconciled


@app.post("/api/events/{event_id}/finalist")
async def api_run_finalist(event_id: str):
    """Run the finalist round for an event — compare all submissions and pick top 3."""
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    rubric = db.get_rubric(event["rubric_id"])
    if not rubric:
        raise HTTPException(status_code=400, detail="Rubric not found")

    submissions = db.list_submissions(event_id=event_id)
    completed = [s for s in submissions if s["status"] == "complete"]

    if len(completed) < 3:
        raise HTTPException(status_code=400, detail=f"Need at least 3 completed submissions, have {len(completed)}")

    # Build submission data for the LLM
    sub_data = []
    for sub in completed:
        scores = db.get_scores(sub["id"])
        review = db.get_review(sub["id"])
        sub_data.append({
            "team_name": sub["team_name"],
            "transcript": sub["transcript"] or "",
            "scores": [dict(s) for s in scores],
            "overall_score": review["overall_score"] if review else 0,
        })

    # Run finalist LLM
    result = await asyncio.to_thread(run_finalist_round, sub_data, rubric)

    # Never announce a team that did not pitch.
    try:
        result["top_picks"] = _reconcile_top_picks(result.get("top_picks") or [], completed)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Generate spoken announcement
    announce_text = _format_finalist_for_speech(result)
    audio_out = AUDIO_DIR / f"finalist_{event_id[:8]}.mp3"
    await asyncio.to_thread(speak, announce_text, audio_out)

    # Save
    db.save_finalist_run(
        event_id, event["rubric_id"], result["top_picks"], result["reasoning"],
        str(audio_out), announce_text,
    )

    return {
        "top_picks": result["top_picks"],
        "reasoning": result["reasoning"],
        "spoken_announcement": announce_text,
        "audio": f"/audio/finalist_{event_id[:8]}.mp3",
    }


@app.get("/api/events/{event_id}/finalist/latest")
async def api_get_finalist(event_id: str):
    """Get the latest finalist run results for an event.

    Returns the same shape as the POST that creates a run, so the UI can render
    a stored result and a fresh one through one code path.
    """
    run = db.get_latest_finalist_run(event_id)
    if not run:
        raise HTTPException(status_code=404, detail="No finalist run found")

    audio_file = AUDIO_DIR / f"finalist_{event_id[:8]}.mp3"
    return {
        "top_picks": run["top_picks"],
        "reasoning": run["reasoning"],
        "spoken_announcement": run.get("spoken_text") or "",
        "audio": f"/audio/{audio_file.name}" if audio_file.exists() else None,
    }


# --- Export ---

@app.get("/api/events/{event_id}/export/csv")
async def api_export_csv(event_id: str):
    """Export event results as a CSV file."""
    import csv
    import io

    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    rubric = db.get_rubric(event["rubric_id"])
    submissions = db.list_submissions(event_id=event_id)
    categories = [c["name"] for c in rubric["categories"]]

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    header = ["Team", *categories, "Overall", "Summary", "Status"]
    writer.writerow(header)

    # Rows
    for sub in submissions:
        scores = db.get_scores(sub["id"])
        review = db.get_review(sub["id"])
        scores_by_cat = {s["category"]: s["score"] for s in scores}

        row = [
            sub["team_name"],
            *[scores_by_cat.get(c, "") for c in categories],
            f"{review['overall_score']:.1f}" if review else "",
            review["summary"] if review else "",
            sub["status"],
        ]
        writer.writerow([_csv_cell(cell) for cell in row])

    # Add finalist results if available
    finalist = db.get_latest_finalist_run(event_id)
    if finalist:
        writer.writerow([])
        writer.writerow(["--- FINALIST RESULTS ---"])
        for pick in finalist["top_picks"]:
            writer.writerow([_csv_cell(c) for c in
                             (f"#{pick['rank']}", pick["team_name"], pick["reasoning"])])

    # Response, not JSONResponse. JSONResponse encodes its content, so the whole
    # file arrived as one JSON string with the line breaks escaped, which opens
    # in a spreadsheet as a single cell of nonsense.
    content = output.getvalue()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=results_{_safe_component(event['name'], 'event')}.csv"},
    )


@app.get("/api/events/{event_id}/export/json")
async def api_export_json(event_id: str):
    """Export event results as structured JSON."""
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    rubric = db.get_rubric(event["rubric_id"])
    submissions = db.list_submissions(event_id=event_id)

    results = []
    for sub in submissions:
        scores = db.get_scores(sub["id"])
        review = db.get_review(sub["id"])
        prfaq = db.get_prfaq(sub["id"])
        results.append({
            "team_name": sub["team_name"],
            "status": sub["status"],
            "scores": [{"category": s["category"], "score": s["score"], "rationale": s["rationale"]} for s in scores],
            "overall_score": review["overall_score"] if review else None,
            "summary": review["summary"] if review else None,
            "transcript": sub["transcript"],
            "prfaq": prfaq["content"] if prfaq else None,
        })

    finalist = db.get_latest_finalist_run(event_id)
    export = {
        "event": event["name"],
        "description": event["description"],
        "rubric": {
            "name": rubric["name"],
            "categories": rubric["categories"],
            "scale": f"{rubric['scale_min']}-{rubric['scale_max']}",
        },
        "submissions": results,
        "finalist": finalist["top_picks"] if finalist else None,
        "finalist_reasoning": finalist["reasoning"] if finalist else None,
    }

    return JSONResponse(
        content=export,
        headers={"Content-Disposition": f"attachment; filename=results_{_safe_component(event['name'], 'event')}.json"},
    )


@app.get("/api/events/{event_id}/export/bundle")
async def api_export_bundle(event_id: str):
    """Export full event results to a local folder for sharing.

    Creates a self-contained folder at `exports/{event_name}_{date}/` with:
    - README.md, leaderboard.md, results.json
    - Per-team transcripts and review breakdowns
    - Audio files (pitch recordings + review audio)
    - Finalist results (if run)

    Returns the folder path so you can AirDrop, USB copy, or share via Finder.
    """
    from datetime import datetime
    import shutil

    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    rubric = db.get_rubric(event["rubric_id"])
    submissions = db.list_submissions(event_id=event_id)
    finalist = db.get_latest_finalist_run(event_id)

    # Create export folder
    safe_name = _safe_component(event["name"], "event")
    date_stamp = datetime.now().strftime("%Y%m%d")
    export_dir = Path(__file__).parent / "exports" / f"{safe_name}_{date_stamp}"
    export_dir.mkdir(parents=True, exist_ok=True)

    # --- README ---
    readme_lines = [
        f"# {event['name']} — Judgement Results",
        f"",
        f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Rubric: {rubric['name']}",
        f"Scale: {rubric['scale_min']}-{rubric['scale_max']}",
        f"Teams: {len(submissions)}",
        f"",
        f"## Structure",
        f"",
        f"```",
        f"├── README.md              ← This file",
        f"├── results.json           ← Full structured results",
        f"├── leaderboard.md         ← Ranked leaderboard",
        f"├── transcripts/           ← Each team's pitch transcript",
        f"├── reviews/               ← Per-team score breakdown",
        f"├── prfaqs/                ← Per-team Working Backwards PRFAQ (if generated)",
        f"├── audio/                 ← Review audio (MP3) + pitch recordings",
        f"└── finalist/              ← Finalist results + audio (if run)",
        f"```",
        f"",
        f"## Handing back the PRFAQs",
        f"",
        f"`prfaqs/` holds one document per team, written from their own pitch. Each is a",
        f"Working Backwards press release and buyer FAQ — the product as though it had",
        f"already launched — followed by the questions they cannot answer yet and a ledger",
        f"grading every load-bearing assumption against what was actually demonstrated.",
        f"",
        f"Send each team their own file. They are meant to be read after the adrenaline",
        f"wears off, and the assumptions ledger is the part worth their time.",
        f"",
        f"Nobody reviewed these. Each carries a disclaimer saying so — leave it on.",
        f"",
    ]
    (export_dir / "README.md").write_text("\n".join(readme_lines))

    # --- results.json ---
    results = []
    for sub in submissions:
        scores = db.get_scores(sub["id"])
        review = db.get_review(sub["id"])
        prfaq = db.get_prfaq(sub["id"])
        results.append({
            "team_name": sub["team_name"],
            "status": sub["status"],
            "scores": [{"category": s["category"], "score": s["score"], "rationale": s["rationale"]} for s in scores],
            "overall_score": review["overall_score"] if review else None,
            "summary": review["summary"] if review else None,
            "transcript": sub["transcript"],
            "prfaq": prfaq["content"] if prfaq else None,
        })

    export_data = {
        "event": event["name"],
        "description": event["description"],
        "exported_at": datetime.now().isoformat(),
        "rubric": {
            "name": rubric["name"],
            "categories": rubric["categories"],
            "scale_min": rubric["scale_min"],
            "scale_max": rubric["scale_max"],
        },
        "submissions": sorted(results, key=lambda r: r["overall_score"] or 0, reverse=True),
        "finalist": finalist["top_picks"] if finalist else None,
        "finalist_reasoning": finalist["reasoning"] if finalist else None,
    }
    (export_dir / "results.json").write_text(json.dumps(export_data, indent=2))

    # --- Leaderboard markdown ---
    leaderboard = [
        f"# {event['name']} — Leaderboard",
        f"",
        f"| Rank | Team | Overall | " + " | ".join(c["name"] for c in rubric["categories"]) + " |",
        f"|------|------|---------|" + "|".join(["------" for _ in rubric["categories"]]) + "|",
    ]

    sorted_subs = sorted(
        [(sub, db.get_scores(sub["id"]), db.get_review(sub["id"])) for sub in submissions if db.get_review(sub["id"])],
        key=lambda x: x[2]["overall_score"],
        reverse=True,
    )

    for rank, (sub, scores, review) in enumerate(sorted_subs, 1):
        scores_by_cat = {s["category"]: s["score"] for s in scores}
        cat_scores = " | ".join(
            str(scores_by_cat.get(c["name"], "—")) for c in rubric["categories"]
        )
        leaderboard.append(
            f"| {rank} | {sub['team_name']} | **{review['overall_score']:.1f}** | {cat_scores} |"
        )

    if finalist:
        leaderboard.extend([f"", f"## 🏆 Finalist Results", f""])
        for pick in finalist["top_picks"]:
            medal = ["🥇", "🥈", "🥉"][pick["rank"] - 1] if pick["rank"] <= 3 else ""
            leaderboard.append(f"{medal} **#{pick['rank']} {pick['team_name']}** — {pick['reasoning']}")
        leaderboard.extend([f"", f"*{finalist['reasoning']}*"])

    (export_dir / "leaderboard.md").write_text("\n".join(leaderboard))

    # --- Per-team transcripts and reviews ---
    transcripts_dir = export_dir / "transcripts"
    transcripts_dir.mkdir(exist_ok=True)
    reviews_dir = export_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    audio_dir = export_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    # Created only if at least one PRFAQ exists — an empty `prfaqs/` folder in the
    # bundle reads as "generation failed" rather than "never run".
    prfaqs_dir = export_dir / "prfaqs"
    prfaq_count = 0

    for sub in submissions:
        team_slug = _safe_component(sub["team_name"], "team").lower()
        scores = db.get_scores(sub["id"])
        review = db.get_review(sub["id"])
        prfaq = db.get_prfaq(sub["id"])

        # PRFAQ — written at generation time, not re-rendered here. The team gets
        # exactly the document that was produced and stored.
        if prfaq:
            prfaqs_dir.mkdir(exist_ok=True)
            (prfaqs_dir / f"{team_slug}.md").write_text(prfaq["markdown"])
            prfaq_count += 1

        # Transcript
        if sub["transcript"]:
            (transcripts_dir / f"{team_slug}.md").write_text(
                f"# {sub['team_name']} — Pitch Transcript\n\n{sub['transcript']}\n"
            )

        # Review markdown
        if review and scores:
            review_md = [
                f"# {sub['team_name']} — Review",
                f"",
                f"**Overall Score: {review['overall_score']:.1f} / {rubric['scale_max']}**",
                f"",
                f"## Scores",
                f"",
            ]
            for s in scores:
                review_md.append(f"### {s['category']}: {s['score']}/{rubric['scale_max']}")
                review_md.append(f"")
                review_md.append(f"{s['rationale']}")
                review_md.append(f"")
            review_md.extend([f"## Summary", f"", review["summary"], f""])
            if review.get("spoken_text"):
                review_md.extend([
                    f"## Spoken Verdict",
                    f"",
                    f"*What the judge said out loud — see `audio/{team_slug}_review.mp3`.*",
                    f"",
                    review["spoken_text"],
                    f"",
                ])
            if prfaq:
                review_md.extend([
                    f"## PRFAQ",
                    f"",
                    f"Your idea written as though it had already launched, followed by an "
                    f"honest grade on everything it assumes: `../prfaqs/{team_slug}.md`",
                    f"",
                ])
            (reviews_dir / f"{team_slug}.md").write_text("\n".join(review_md))

        # Copy audio files
        pitch_audio_mp3 = AUDIO_DIR / f"{sub['id']}.mp3"
        pitch_audio_webm = AUDIO_DIR / f"{sub['id']}.webm"
        # Prefer MP3 (generated by edge-tts in mock mode), fall back to webm
        if pitch_audio_mp3.exists() and pitch_audio_mp3.stat().st_size > 100:
            shutil.copy2(pitch_audio_mp3, audio_dir / f"{team_slug}_pitch.mp3")
        elif pitch_audio_webm.exists() and pitch_audio_webm.stat().st_size > 100:
            shutil.copy2(pitch_audio_webm, audio_dir / f"{team_slug}_pitch.webm")

        review_audio = AUDIO_DIR / f"{sub['id']}_review.mp3"
        if review_audio.exists() and review_audio.stat().st_size > 100:
            shutil.copy2(review_audio, audio_dir / f"{team_slug}_review.mp3")

    # --- Finalist ---
    if finalist:
        finalist_dir = export_dir / "finalist"
        finalist_dir.mkdir(exist_ok=True)

        finalist_audio = AUDIO_DIR / f"finalist_{event_id[:8]}.mp3"
        if finalist_audio.exists():
            shutil.copy2(finalist_audio, finalist_dir / "announcement.mp3")

        finalist_md = [f"# {event['name']} — Finalist Results", f""]
        for pick in finalist["top_picks"]:
            finalist_md.append(f"## #{pick['rank']}: {pick['team_name']}")
            finalist_md.append(f"")
            finalist_md.append(f"{pick['reasoning']}")
            finalist_md.append(f"")
        finalist_md.extend([f"---", f"", finalist["reasoning"], f""])
        if finalist.get("spoken_text"):
            finalist_md.extend([
                f"## Spoken Announcement",
                f"",
                f"*What the judge said out loud — see `announcement.mp3`.*",
                f"",
                finalist["spoken_text"],
                f"",
            ])
        (finalist_dir / "results.md").write_text("\n".join(finalist_md))

    return {
        "status": "exported",
        "path": str(export_dir),
        "files": len(list(export_dir.rglob("*"))),
        "prfaqs": prfaq_count,
        "message": f"Results exported to: {export_dir}",
    }


# --- Helpers ---

# The judge writes its own spoken verdict — roughly a minute of warm, specific
# feedback addressed to the room. These caps are a runaway guard, not the target
# length: a model that ignores the word count shouldn't hold a live event hostage.
SPOKEN_REVIEW_MAX_WORDS = 260
SPOKEN_ANNOUNCEMENT_MAX_WORDS = 340

# Fallback lengths, used only when the model omits the spoken field entirely and
# the review has to be assembled from the score rationales.
SPOKEN_SUMMARY_SENTENCES = 3
SPOKEN_SUMMARY_WORDS = 90
SPOKEN_FINALIST_SENTENCES = 2
SPOKEN_FINALIST_WORDS = 45


# Periods that do not end a sentence. Splitting naively on "." cuts reviews in
# half at "vs." or "92.5%", which is audible — the voice stops mid-thought.
_DOT_SENTINEL = "\x00"
_ABBREVIATIONS = (
    "vs", "etc", "approx", "cf", "al", "est", "min", "max", "avg",
    "Dr", "Mr", "Mrs", "Ms", "Prof", "Inc", "Ltd", "Co", "Corp", "St", "No", "Fig", "Jr", "Sr",
)


def _split_sentences(text: str) -> list[str]:
    """Split into sentences, ignoring periods inside abbreviations and decimals."""
    protected = re.sub(
        rf"\b({'|'.join(_ABBREVIATIONS)})\.",
        lambda m: m.group(1) + _DOT_SENTINEL,
        text.strip(),
        flags=re.IGNORECASE,
    )
    # Dotted acronyms: e.g., i.e., U.S., a.m.
    protected = re.sub(
        r"\b(?:[A-Za-z]\.){2,}",
        lambda m: m.group(0).replace(".", _DOT_SENTINEL),
        protected,
    )
    # Decimals: 92.5, 4.0
    protected = re.sub(r"(\d)\.(\d)", rf"\1{_DOT_SENTINEL}\2", protected)

    parts = re.findall(r"[^.!?]+[.!?]*", protected)
    return [p.replace(_DOT_SENTINEL, ".").strip() for p in parts if p.strip()]


def _trim_for_speech(
    text: str, max_sentences: int, max_words: int, hard_cap: int | None = None
) -> str:
    """Trim text to whole sentences that fit a rough spoken-word budget.

    Models routinely overrun the "1-2 sentences" instruction in the rubric
    prompt, so the length of a spoken review can't be left to the prompt alone.

    Sentence boundaries win over the word budget: a review read aloud must never
    stop mid-clause. The first sentence is always kept whole, and the budget only
    decides whether later sentences join it. The hard cut is a backstop for a
    single runaway sentence.
    """
    if not text:
        return ""

    sentences = _split_sentences(text)
    if not sentences:
        return ""

    kept = [sentences[0]]
    for sentence in sentences[1:max_sentences]:
        if len(" ".join(kept + [sentence]).split()) > max_words:
            break
        kept.append(sentence)

    trimmed = " ".join(kept)

    # Backstop: one sentence far over budget still gets cut, at a clause break
    # where possible so it doesn't end on a dangling preposition.
    # By default allow a little headroom so one complete sentence just over the
    # budget survives whole. Callers enforcing a true ceiling pass hard_cap.
    ceiling = hard_cap if hard_cap is not None else int(max_words * 1.6)
    words = trimmed.split()
    if len(words) > ceiling:
        trimmed = _clip(" ".join(words[:ceiling]))

    # Character backstop. Counting words alone doesn't bound speaking time if the
    # model emits an unbroken wall of text with no spaces or sentence punctuation.
    char_cap = ceiling * 8
    if len(trimmed) > char_cap:
        trimmed = _clip(trimmed[:char_cap])

    return trimmed


def _clip(text: str) -> str:
    """End a truncated span at a clause break so it doesn't dangle."""
    clause_end = max(text.rfind(","), text.rfind(";"), text.rfind(" — "))
    if clause_end > len(text) // 2:
        text = text[:clause_end]
    return text.rstrip(",;:—- ") + "."


def _format_review_for_speech(
    team_name: str,
    scores: list[dict],
    overall: float,
    summary: str,
    rubric: dict,
    spoken_review: str | None = None,
) -> str:
    """Build the text read aloud after a team pitches (~1 minute).

    The judge writes this itself — warm, specific feedback addressed to the room,
    the way an investor gives notes in public. Assembling it here from score
    fragments produced a clipped readout that taught the audience nothing, so the
    mechanical version is only a fallback for when the model omits the field.
    """
    written = _spell_for_speech((spoken_review or "").strip())
    if written:
        return _cap_words(written, SPOKEN_REVIEW_MAX_WORDS)

    # Fallback: assemble from the scores and summary.
    score_list = " ".join(
        f"{_spell_for_speech(s['category'])}, {s['score']}." for s in scores
    )
    return " ".join([
        f"Review for team {team_name}.",
        score_list,
        f"Overall, {overall:.1f} out of {rubric['scale_max']}.",
        _trim_for_speech(summary, SPOKEN_SUMMARY_SENTENCES, SPOKEN_SUMMARY_WORDS),
    ]).strip()


def _cap_words(text: str, max_words: int) -> str:
    """Guard against a model that badly overruns its word budget."""
    if len(text.split()) <= max_words:
        return text
    return _trim_for_speech(text, max_sentences=99, max_words=max_words, hard_cap=max_words)


def _spell_for_speech(text: str) -> str:
    """Expand symbols a TTS voice reads badly or skips."""
    return text.replace("&", "and").replace("/", " or ")


def _format_finalist_for_speech(result: dict) -> str:
    """Build the spoken results reveal.

    Prefers the announcement the judge wrote; falls back to assembling one from
    the per-team reasoning if the model omitted it.
    """
    written = _spell_for_speech((result.get("spoken_announcement") or "").strip())
    if written:
        return _cap_words(written, SPOKEN_ANNOUNCEMENT_MAX_WORDS)

    lines = ["And now, the results of the finalist round."]
    for pick in reversed(result["top_picks"]):
        reason = _trim_for_speech(pick["reasoning"], SPOKEN_FINALIST_SENTENCES, SPOKEN_FINALIST_WORDS)
        lines.append(f"In {_ordinal(pick['rank'])} place: {pick['team_name']}. {reason}")
    lines.append("Congratulations to all teams!")
    return " ".join(lines)


def _ordinal(n: int) -> str:
    if n == 1:
        return "first"
    elif n == 2:
        return "second"
    elif n == 3:
        return "third"
    return f"{n}th"

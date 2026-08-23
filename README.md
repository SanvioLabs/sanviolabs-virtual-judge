---
type: readme
scope: project
project: virtual-judge
status: active
updated: '2026-08-14'
title: Virtual Judge
---

# Virtual Judge

AI-powered judging for hackathons and pitch events. Record a pitch, get it transcribed, scored against a rubric by an LLM, and hear the review spoken back — all in under a minute.

## What It Does

1. **Record** — Team walks up, you enter their name, hit record
2. **Transcribe** — an audio-capable model converts the pitch to text
3. **Score** — an LLM evaluates the transcript against your rubric (per-category scores + rationale)
4. **Speak** — ElevenLabs reads back the review in a natural voice
5. **Finalist** — After all teams present, one button compares everyone and picks the top 3
6. **PRFAQ** — After the event, generate each team a Working Backwards document from their own pitch

Everything persists in a local SQLite file. One person operates it. Works on a projector.

## Setup

```bash
# Install dependencies
npm run setup

# Add your API keys to .env
open .env
```

Required keys:

| Key | Service | What it does |
|-----|---------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter | Transcription **and** scoring |
| `ELEVENLABS_API_KEY` | ElevenLabs | Voice synthesis |
| `ELEVENLABS_VOICE_ID` | ElevenLabs | Which voice to use (optional — defaults to Rachel) |

Optional model overrides:

| Var | Default | Notes |
|-----|---------|-------|
| `OPENROUTER_SCORING_MODEL` | `anthropic/claude-sonnet-5` | Any text model on OpenRouter |
| `OPENROUTER_TRANSCRIPTION_MODEL` | `google/gemini-3.7-flash` | Must accept **audio input** |
| `OPENROUTER_PRFAQ_MODEL` | falls back to the scoring model | PRFAQ writing is a heavier task than scoring — point it at a stronger model if you want |

Optional behaviour overrides:

| Var | Default | Notes |
|-----|---------|-------|
| `VJ_MAX_UPLOAD_MB` | `100` | Ceiling on one recording. A five minute pitch is a couple of megabytes, so this is a guard, not a limit you should meet |
| `VJ_FINALIST_TRANSCRIPT_CHARS` | `6000` | How much of each pitch the finalist round reads. Enough for a full five minute pitch. Lower it if you point the round at a small-context model |
| `VJ_DB_PATH` | `judge.db` in the project root | Where the database lives. The test suite sets this so a run never touches your event data |

### The database

There is nothing to create. On first start the server builds `judge.db` in the
project root, creates every table, and loads every rubric in `rubrics/` into it.
Starting again reuses the file, and re-running the rubric sync does not duplicate
anything.

```bash
npm run dev          # first run creates judge.db and loads the rubrics
npm run db:reset     # delete it and start clean
npm run reset        # delete the database and every recorded audio file
```

If you open a database from before events existed, the schema migration drops
every submission, score, review and PRFAQ in it. It copies the file to
`judge.pre-migration-{timestamp}.db` first and logs where, so the old record is
recoverable, but the running database will be empty.

`judge.db` holds seven tables: `rubrics`, `events`, `submissions` (transcripts
included), `scores`, `reviews`, `finalist_runs`, and `prfaqs`. It is gitignored
and it never leaves the machine. It does not hold audio.

Confirm the tables and the rubric landed:

```bash
curl -s localhost:8000/api/health | python3 -m json.tool
```

`rubrics_loaded` should be at least 1. If it is 0, no rubric in `rubrics/` parsed,
and the server will start but nothing can be judged.

Also required: **ffmpeg** (`brew install ffmpeg`). The browser records WebM/Opus,
which OpenRouter does not accept as audio input, so recordings are transcoded to
MP3 before transcription. The converted MP3 is kept, so exports ship with
playable pitch audio.

### Verify before the event

```bash
curl 'http://localhost:8000/api/health?verify=1'
```

Without `verify=1` the health check only reports whether keys are *present*.
With it, the server makes a live call to each provider — do this before teams
start pitching, not after.

## Usage

```bash
# Start the server
npm run dev
```

Open http://localhost:8000

**How to use** in the top right opens a modal covering the whole run: what to
check before the first team, what to do for each one, the finalist round, and
the PRFAQs afterwards. It is the fastest way to hand the laptop to someone else.

### Live Event Flow

```
Enter team name → 🎙️ Record → ⏹️ Stop → ⏳ ~30s processing → 🔊 Review plays back → ➡️ Next team
```

The processing step counts elapsed time on screen. It is usually around thirty
seconds. If a provider hangs, retries can push a single team into minutes, so
the number on screen is the real one and the thirty is the typical one.

### When a provider is down

The only failure that can cost the whole event rather than one team. It cannot.

Tick **Record only, judge later** and keep going: each pitch is captured and the
room moves on at full speed. If judging fails mid-run instead, the recording is
still saved and the message says so.

Either way the Submissions tab shows how many recordings are waiting, with one
**Judge all** button. It runs them one at a time rather than in parallel, since
the reason you are here is that a provider was struggling.

After all teams have gone:

```
🏆 Finalist tab → Run Finalist Round → Top 3 announced via voice
```

Then, once the room has cleared:

```
📋 Submissions tab → Generate PRFAQs → Export to Folder → send each team their file
```

### Network Access

To let others on the same WiFi access the UI (phones, other laptops):

```bash
npm run start
```

This binds to `0.0.0.0:8000` — share your local IP (e.g., `http://192.168.1.42:8000`).

### What leaves your machine

Before you run this on real people, know where their voices go. Per pitch:

| Sent to | What |
|---|---|
| **OpenRouter** | The recording itself, as MP3, for transcription |
| **OpenRouter** | The transcript, again, for scoring and later for the PRFAQ |
| **ElevenLabs** | The review text, to be spoken |

Nothing else leaves. The scores, the reviews and the database stay on the
machine. The product has no consent step and no expiry: recordings, transcripts
and export bundles sit on disk until you delete them, with `npm run reset` or by
deleting an event in the UI. Telling teams their pitch is recorded and judged by
AI is the organiser's job, and this tool does not do it for you.

> **There is no authentication.** Every route is open to anyone who can reach the
> port. On `npm run start` that is everyone on the same network, and they can read
> every transcript, review and PRFAQ, and create submissions of their own. Run it
> on a network you trust, or stay on `npm run dev`, which binds to localhost only.
> Do not expose the port to the internet or put it behind a public tunnel.

## Commands

| Command | Description |
|---------|-------------|
| `npm run dev` | Start with hot-reload (development) |
| `npm run start` | Start on all interfaces (event/LAN mode) |
| `npm run lint` | Lint with ruff |
| `npm run lint:fix` | Lint and apply the safe fixes |
| `npm run test` | Run unit/API test suite (pytest) |
| `npm run test:e2e` | Run Playwright browser tests |
| `npm run test:e2e:headed` | Run E2E tests with visible browser |
| `npm run test:e2e:install` | Install the Chromium build Playwright uses |
| `npm run test:e2e:ui` | Run E2E tests in Playwright's interactive UI |
| `npm run test:all` | Run everything (pytest + Playwright) |
| `npm run setup` | Install deps + create .env |
| `npm run db:reset` | Wipe the database (fresh start) |
| `npm run audio:clean` | Delete all recorded/generated audio |
| `npm run exports:clean` | Delete every export bundle |
| `npm run reset` | Full reset: database, audio and exports |

## PRFAQs — what each team takes home

A score tells a team where they placed. A PRFAQ tells them what they actually
built and what they have not yet proven. This is the thing they read on the train
home, and it is worth more to them than the leaderboard.

Each one is generated from that team's pitch transcript and nothing else:

| Section | Written from | Holds |
|---|---|---|
| **1. Press release** | inside the launch | Their product as though it had already shipped, in the Amazon order: headline, subheadline, dateline, summary, problem, solution and its named mechanisms, the team's quote, getting started, a customer's quote, and a closing line |
| **2. Customer FAQ** | inside the launch | What a buyer asks in the first ten minutes, answered |
| **3. The Hard FAQ** | today | The questions they *cannot* answer yet, each with what would settle it |
| **4. Assumptions ledger** | today | Every load-bearing claim graded **Tested**, **Partly tested**, or **Untested** |
| **5. What would change our mind** | today | Checkable signals that would mean the thesis is wrong |

The rules the document is written to, the two voices that must not mix, strict
grading, the paired check, the Amazon section order, and no roadmap language in
the launch sections, are stated in the system prompt in `judge/prfaq.py`. Change
how the documents read by changing it there.

The disclaimer, the invented-customer label, the missing-quote placeholder, and
the provenance block are rendered in Python, not requested from the model, so a
bad generation cannot produce a document that reads as verified. The rendered file
opens with frontmatter carrying the grade tally and `reviewed_by_a_human: false`,
so the counts survive being pasted anywhere.

The ledger also names **one row as the cheapest to close** — the decision or the
number that costs least to settle and unblocks the most. It renders as `⬅ start
here`. For most teams that is the single most useful line in the document.

### Running it

Not part of the live judging pipeline — it takes far longer than the pause a room
will sit through between teams. Run it after the event.

```bash
# Every judged team in an event
curl -X POST localhost:8000/api/events/{event_id}/prfaqs

# One team, or re-write an existing one
curl -X POST localhost:8000/api/submissions/{sub_id}/prfaq
curl -X POST 'localhost:8000/api/submissions/{sub_id}/prfaq?force=true'
```

Or hit **Generate PRFAQs** on the Submissions tab. A team failing does not stop the
rest — the response names who succeeded, who was skipped, and who failed.

Then **Export to Folder**: each team's document lands at `prfaqs/{team}.md`, ready
to send.

## Rubrics

Rubrics live in `rubrics/` as YAML files. Every `*.yaml` in that directory is loaded
into the database on server start, so adding a rubric is dropping a file in and
restarting. Nothing else registers it.

One rubric ships: **`rubrics/example-hackathon.yaml`**. It is a general-purpose
hackathon rubric on a 1 to 5 scale with four equally weighted categories. On a fresh
install it is the only rubric present, so it is the one every event gets. Copy it,
rename it, and edit it for your event rather than starting from a blank file.

```yaml
name: "Example Hackathon"
description: "A general-purpose rubric for judging AI product builds at a hackathon"
scale_min: 1
scale_max: 5
calibration: |
  Score strictly. A 3 is average: competent but unremarkable. A 4 means genuinely
  impressive. A 5 is exceptional and rare, reserved for work that would impress
  seasoned professionals. Most teams should land between 2 and 4. Do not inflate
  scores to be encouraging.
judge_persona: |
  You are a panel of experienced builders and investors who genuinely enjoy watching
  new teams take their first swing.

  Your style:
  - Warm but honest. You can be encouraging and direct at the same time.
  - Lead with what excited you. Every team did something worth calling out.
  - Always close with three specific next steps for the team.
categories:
  - name: "Real-World Impact"
    description: "Does this solve a real problem? Could someone actually use this tomorrow? Is the target user clear?"
    weight: 1.0
  - name: "Innovation & Creativity"
    description: "Is this a fresh idea or a novel combination? Did the team push boundaries on what is possible with AI tools?"
    weight: 1.0
  - name: "Technical Execution"
    description: "Does it work? How complete is the prototype? How effectively did the team use AI in the build process?"
    weight: 1.0
  - name: "Presentation & Vision"
    description: "Did the pitch land? Is the story compelling? Can you see where this product goes next?"
    weight: 1.0
```

The judge persona above is trimmed. See the file for the full text.

**Fields:**

| Field | What it does |
|---|---|
| `name` | Rubric name. Rubrics are synced by name, so renaming creates a second rubric rather than editing the first |
| `description` | Free text. Shown in the UI |
| `scale_min` / `scale_max` | Scoring range, for example 1 to 5 or 1 to 10 |
| `calibration` | Instructions that hold the scores down. Without it an LLM clusters everything at 4 and 5, and a leaderboard where nobody is separated is not a leaderboard |
| `judge_persona` | Who the model is being. This sets the tone of the spoken review more than anything else in the file, so it is the field to change if the reviews sound wrong for your room |
| `categories` | What gets scored, each with a `name` and a `description` the model reads as the scoring instruction |
| `weight` | Relative importance of a category. Defaults to 1.0. Use 2.0 to double its pull on the overall score |

Three notes worth knowing before an event:

1. **Rubrics sync by `name`.** Editing a rubric that has already been loaded does not
   update the copy in `judge.db`. Change the name, or run `npm run db:reset` on a
   database you do not need.
2. **An event with no rubric gets the most recently created one**, unless a rubric
   file claims the default with `default: true`. On a one-rubric install this never
   comes up. The moment you add a second, set the flag or pick the rubric
   explicitly, because otherwise load order decides.
3. **A category `description` is the scoring prompt, not a label.** The model reads it
   as the instruction for that category, so it is worth writing in full sentences.

## Specification

[`SPEC.md`](SPEC.md) is the recovered specification: the boundary, every surface,
the core data path, the data model with the invariants the code assumes and does
not enforce, and thirty requirements each graded by what it rests on. It was
worked backwards from the code rather than written before it, so it also carries
what the code decides without recording a reason.

Those undecided items live in [`docs/spec-questions.md`](docs/spec-questions.md).
Seventeen of them, each addressed to whoever can settle it. A constant is not a
requirement, and the difference is what a rewrite would lose.

## Architecture

```
virtual-judge/
├── server.py              # FastAPI app — all routes
├── judge/
│   ├── db.py              # SQLite operations
│   ├── openrouter.py      # Shared OpenRouter client + model selection
│   ├── llm.py             # LLM scoring + finalist logic
│   ├── transcribe.py      # Audio → text via OpenRouter
│   ├── speak.py           # ElevenLabs TTS
│   ├── prfaq.py           # Working Backwards PRFAQ generation + Markdown rendering
│   └── rubrics.py         # YAML rubric loader
├── rubrics/               # Rubric definitions (YAML)
├── static/                # Web UI (no build step)
├── audio_recordings/      # Stored audio (gitignored)
├── judge.db               # SQLite database (gitignored)
└── tests/
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | The web UI |
| `GET` | `/api/health` | Health check — key presence, models, counts. Add `?verify=1` for a live provider check |
| `GET` | `/api/rubrics` | List available rubrics |
| `GET` | `/api/events` | List all events |
| `POST` | `/api/events` | Create event `{name, rubric_id?, description?}` |
| `GET` | `/api/events/:id` | Get event details |
| `DELETE` | `/api/events/:id` | Delete an event, every submission in it, and their audio. Not recoverable |
| `POST` | `/api/submissions` | Create a submission `{team_name, event_id}` |
| `POST` | `/api/submissions/:id/audio` | Upload recorded audio (multipart) |
| `POST` | `/api/submissions/:id/judge` | Run full pipeline (transcribe → score → speak) |
| `GET` | `/api/events/:id/pending` | Recordings that have not produced a review yet |
| `POST` | `/api/events/:id/judge-pending` | Judge every waiting recording, one at a time |
| `GET` | `/api/events/:id/submissions` | List all submissions for an event |
| `GET` | `/api/submissions/:id` | Get single submission detail |
| `DELETE` | `/api/submissions/:id` | Delete one submission, its scores, review, PRFAQ and audio. For the recording started on the wrong team |
| `POST` | `/api/submissions/:id/prfaq` | Write the team's PRFAQ. Returns the stored one unless `?force=true` |
| `GET` | `/api/submissions/:id/prfaq` | Get a previously generated PRFAQ |
| `GET` | `/api/submissions/:id/prfaq/download` | Download the PRFAQ as a Markdown file |
| `POST` | `/api/events/:id/prfaqs` | Write PRFAQs for every judged team. Returns generated / skipped / failed |
| `POST` | `/api/events/:id/finalist` | Run finalist comparison, pick top 3 |
| `GET` | `/api/events/:id/finalist/latest` | Get most recent finalist results |
| `GET` | `/api/events/:id/export/csv` | Export results as CSV |
| `GET` | `/api/events/:id/export/json` | Export results as JSON |
| `GET` | `/api/events/:id/export/bundle` | Export results to local `exports/` folder for sharing |

## Data

Scores, transcripts, reviews, PRFAQs and finalist rounds live in `judge.db`
(SQLite). **The recordings do not.** They sit in `audio_recordings/`, and the
database refers to them by absolute path, so a backup is both directories or it
is not a backup. Restoring `judge.db` alone gives you every score and every
transcript, and every audio player in the UI pointing at a file that is not
there.

Every export writes a new dated folder under `exports/` holding full transcripts,
PRFAQs and audio. Nothing removes them, so they accumulate one copy of the event
per export. `npm run exports:clean` clears them once you have sent them on.

`judge.db`, `audio_recordings/` and `exports/` are all gitignored, and they must
stay that way. They hold recordings of real people pitching, their transcripts,
and their scores. Treat that directory as participant data: back it up somewhere
private, and never commit it or attach it to a public issue.

**Tables:** `rubrics`, `submissions`, `scores`, `reviews`, `finalist_runs`, `prfaqs`

To inspect directly:

```bash
sqlite3 judge.db "SELECT team_name, overall_score FROM submissions s JOIN reviews r ON s.id = r.submission_id ORDER BY overall_score DESC;"
```

## Tips for Event Day

- **Test beforehand** — hit `/api/health?verify=1`, then record a 30-second test pitch and run the full flow
- **External mic** — laptop mics pick up room noise; a USB mic pointed at the presenter helps
- **Quiet moment** — the 30s processing time is a natural pause; use it for applause or transition
- **Consent** — mention to teams that pitches are recorded and AI-judged (event organizers handle this)
- **Backup** — copy `judge.db` **and** `audio_recordings/` after the event. The database alone is the scores without the pitches
- **PRFAQs come after** — don't run them between teams. Generate them once the room has cleared, then export and send

## Stack

- **Python 3.11+** with FastAPI
- **OpenRouter** — single gateway for both speech-to-text and LLM evaluation
- **ffmpeg** — transcodes browser recordings for transcription
- **ElevenLabs** — text-to-speech
- **SQLite** — local persistence
- **Vanilla HTML/CSS/JS** — no frontend build step

## License

MIT. See [LICENSE](LICENSE).

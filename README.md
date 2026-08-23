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

`judge.db` is the whole event record. Seven tables: `rubrics`, `events`,
`submissions` (transcripts included), `scores`, `reviews`, `finalist_runs`, and
`prfaqs`. It is gitignored, it never leaves the machine, and copying that one file
is a complete backup.

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
| `npm run test` | Run unit/API test suite (pytest) |
| `npm run test:e2e` | Run Playwright browser tests |
| `npm run test:e2e:headed` | Run E2E tests with visible browser |
| `npm run test:all` | Run everything (pytest + Playwright) |
| `npm run setup` | Install deps + create .env |
| `npm run db:reset` | Wipe the database (fresh start) |
| `npm run audio:clean` | Delete all recorded/generated audio |
| `npm run reset` | Full reset (DB + audio) |

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

Four rules make the document work, and all four are enforced in code rather than
left to the model:

**The two voices don't mix.** Sections 1 and 2 are confident and past tense. All
the doubt lives in 3 and 4. A caveat in the press release destroys the document
twice over — it stops reading like a launch, and it lets the writer feel a gap has
been handled when it has only been mentioned. The gaps are meant to become visible
by *contrast*.

**A claim made in a pitch is Untested.** Confidence is not evidence. Most rows in a
hackathon ledger will be Untested, and that is the correct outcome — it is what a
pitch *is*. Grading generously makes the ledger worthless.

**The paired check.** Every caveat kept out of sections 1 and 2 has to reappear as
a ledger row. A clean announcement above a short ledger is worse than a hedged
one, because the gaps were deleted rather than moved. No price in the FAQ means
"there is a price" is a row.

**The press release runs in the Amazon order, and the order is load-bearing.** The
team's quote sits straight after the mechanism, because a spokesperson says *why
this was built* before the reader is told how to use it. The customer quote sits
after Getting started, because it is someone reporting back from having done
exactly that. Quotes bunched at the end read as a product brief, not a launch. A
stated launch date becomes a dateline; an unstated one becomes a ledger row.

**No roadmap language in sections 1 and 2.** "Not yet," "planned," "in
development," and "we're working on it" turn an announcement back into a status
update. A real limit at launch is stated as a fact of the shipped product: "it
supports primary care and orthopedics," not "other specialties are planned."

**The founder quote is never invented.** Most pitches describe the product, not
the reason for it. When the transcript carries no founding account the generator
returns nothing and the document prints a production placeholder asking the team
for one. Writing a founding motivation for someone who never stated one is the
exact failure the format exists to prevent, and it is the one place a PRFAQ
becomes a lie rather than a draft.

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
2. **An event with no rubric gets the most recently created one.** If you keep several
   rubrics around, set the rubric explicitly when you create the event rather than
   trusting the default.
3. **A category `description` is the scoring prompt, not a label.** The model reads it
   as the instruction for that category, so it is worth writing in full sentences.

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
| `GET` | `/api/health` | Health check — key presence, models, counts. Add `?verify=1` for a live provider check |
| `GET` | `/api/rubrics` | List available rubrics |
| `GET` | `/api/events` | List all events |
| `POST` | `/api/events` | Create event `{name, rubric_id?, description?}` |
| `GET` | `/api/events/:id` | Get event details |
| `POST` | `/api/submissions` | Create a submission `{team_name, event_id}` |
| `POST` | `/api/submissions/:id/audio` | Upload recorded audio (multipart) |
| `POST` | `/api/submissions/:id/judge` | Run full pipeline (transcribe → score → speak) |
| `GET` | `/api/events/:id/submissions` | List all submissions for an event |
| `GET` | `/api/submissions/:id` | Get single submission detail |
| `POST` | `/api/submissions/:id/prfaq` | Write the team's PRFAQ. Returns the stored one unless `?force=true` |
| `GET` | `/api/submissions/:id/prfaq` | Get a previously generated PRFAQ |
| `POST` | `/api/events/:id/prfaqs` | Write PRFAQs for every judged team. Returns generated / skipped / failed |
| `POST` | `/api/events/:id/finalist` | Run finalist comparison, pick top 3 |
| `GET` | `/api/events/:id/finalist/latest` | Get most recent finalist results |
| `GET` | `/api/events/:id/export/csv` | Export results as CSV |
| `GET` | `/api/events/:id/export/json` | Export results as JSON |
| `GET` | `/api/events/:id/export/bundle` | Export results to local `exports/` folder for sharing |

## Data

Everything lives in `judge.db` (SQLite). This file is your complete event record — back it up after the event.

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
- **Backup** — copy `judge.db` after the event; it's the full history
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

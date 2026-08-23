---
doc: spec
skill: salvage
subject: Virtual Judge
read_at:
  repo: SanvioLabs/sanviolabs-virtual-judge
  sha: d359e7c
  branch: main
  tree: clean
  date: 2026-08-23
verdict: Salvaged
---

# Virtual Judge, recovered specification

## 1. What this system is

Virtual Judge scores live pitches at a hackathon. One operator runs it from one
laptop: a team walks up, the operator types their name and records the pitch, and
about thirty seconds later the room hears a spoken review read back by a
synthetic voice. After every team has presented, one action compares them all and
announces a top three. After the event, each team can be given a Working
Backwards PRFAQ written from their own pitch.

The unit of work is **one team's pitch**, from the moment recording starts to the
moment the room hears the verdict.

**How this document was produced.** It was recovered from the code at the SHA in
the frontmatter, not written before it. Every statement carries a grade, and the
grades mean exactly what the table below says. `[observed]` means the path was
read end to end or exercised. `[inferred]` means one reading supports it and
nothing proves it. `[intended: X]` means a document claims it and the code was
not read against the claim. `[undecided]` means the code makes a choice and
nothing records whether it was a decision. **Nobody has answered the undecided
items.** They are collected in `docs/spec-questions.md` and until they are
answered this document describes what the system does, not everywhere what it
must do.

**One limitation a reader should weigh.** A large share of the requirements
graded `observed` describe behaviour that was written or repaired in the week
before this reading, by the same author doing the reading. Grading your own
recent decisions as observed is accurate about the code and says nothing about
whether the decision was right. R7 through R10, R13, R14, R18, and R20 through
R25 are in that group. They are correctly graded and they are the requirements
most in need of a second opinion, because nobody has yet reviewed the judgement
that produced them.

## 2. Boundary

| In | Out | Undeclared |
|---|---|---|
| The FastAPI server, the judging pipeline, the SQLite store, the browser UI, the rubric loader, the PRFAQ generator, the export builders `[observed]` | OpenRouter, which performs both transcription and scoring. ElevenLabs, which performs speech. ffmpeg, invoked as a subprocess. The browser's `MediaRecorder` and `getUserMedia` `[observed]` | **The host machine's network position.** `npm run start` binds `0.0.0.0` and no route authenticates, so every surface below is reachable by anyone on the same network. Whether that is a requirement or an accident is undecided `[undecided]` |
| | | **The event's consent process.** The README assigns it to the organiser `[intended: README, "Tips for Event Day"]`. Nothing in the product records, gates on, or evidences consent `[observed]` |

## 3. Surfaces

Twenty-two HTTP routes, two static mounts, three outbound services, one
subprocess, and three stores. No scheduled work, no queues, and no streams exist
in this system `[observed]`.

### Entry points

None of them authenticate. The "Authenticated as" column is identical for every
row and is stated once here rather than repeated: **unauthenticated, and the
server trusts its caller completely** `[observed]`.

| Surface | Kind | Trusts | On bad input |
|---|---|---|---|
| `GET /` | HTML | nothing | n/a `[observed]` |
| `GET /api/health` | JSON | `?verify=1` triggers live billed calls to both providers | returns `missing_keys` or `key_check_failed` rather than failing `[observed]` |
| `GET /api/rubrics` | JSON | nothing | n/a `[observed]` |
| `GET`, `POST /api/events` | JSON | event name is free text, rendered later and written to filenames | name is not validated or length-capped `[undecided]` |
| `GET`, `DELETE /api/events/{id}` | JSON | id must exist | 404 `[observed]` |
| `GET /api/events/{id}/submissions` | JSON | id | empty list for an unknown event, not a 404 `[observed]` |
| `POST /api/submissions` | JSON | team name is free text, and two teams in one event may share a name | 404 on unknown event; name is not validated `[observed]` |
| `POST /api/submissions/{id}/audio` | multipart, field `file` | any bytes, any declared type | 413 past `VJ_MAX_UPLOAD_BYTES`, 400 when empty, 404 unknown submission. Content is never checked to be audio `[observed]` |
| `POST /api/submissions/{id}/judge` | JSON | that audio exists | 400 without audio, 500 per failed stage with the stage named. **No guard against running twice** `[observed]` |
| `GET`, `DELETE /api/submissions/{id}` | JSON | id | 404 `[observed]` |
| `POST`, `GET /api/submissions/{id}/prfaq` | JSON | a transcript exists | 400 without one, 502-equivalent 500 on generation failure `[observed]` |
| `GET /api/submissions/{id}/prfaq/download` | Markdown | id | 404 `[observed]` |
| `POST /api/events/{id}/prfaqs` | JSON | id | per-team outcome, three at a time, 120s each `[observed]` |
| `POST /api/events/{id}/finalist` | JSON | at least three completed submissions | 400 under three, 502 when the model names a team that did not pitch `[observed]` |
| `GET /api/events/{id}/finalist/latest` | JSON | id | null when never run `[observed]` |
| `GET /api/events/{id}/export/{csv,json,bundle}` | file, file, filesystem write | id | 404 `[observed]` |
| `/static/*` | static mount | path under `static/` | 404 `[observed]` |
| `GET /audio/{filename}` | audio file | only the four names the system writes, and only for a record that still exists | 404 for anything else, including a file no submission refers to. **Still unauthenticated: a caller who knows a submission id gets that team's pitch** `[observed]` |

### Request and response shapes

Everything is JSON except the audio upload, which is `multipart/form-data`, and
the three exports. Unlisted routes take no body `[observed]`.

| Route | Request | Success response |
|---|---|---|
| `POST /api/events` | `{name, rubric_id?, description?}` | `{id, name, rubric_id}` |
| `GET /api/events` | | `[{...event, submission_count, completed_count}]` |
| `GET /api/events/{id}` | | `{...event, rubric, submission_count, completed_count}` |
| `DELETE /api/events/{id}` | | `{deleted, audio_files_removed}` |
| `POST /api/submissions` | `{team_name, event_id}` | `{id, team_name, event_id, status: "recording"}` |
| `POST /api/submissions/{id}/audio` | multipart, one part named **`file`** | `{status: "uploaded", audio_path}` |
| `POST /api/submissions/{id}/judge` | | `{status, transcript, scores[], overall_score, summary, spoken_review, review_audio, unmatched_categories?}` |
| `GET /api/submissions/{id}` | | `{...submission, scores[], review, has_prfaq}` |
| `GET /api/events/{id}/submissions` | | the above, as a list |
| `DELETE /api/submissions/{id}` | | `{deleted, audio_files_removed}` |
| `POST /api/submissions/{id}/prfaq` | `?force=true` re-writes | `{submission_id, team_name, content, markdown, model}` |
| `GET /api/submissions/{id}/prfaq/download` | | `text/markdown`, `Content-Disposition` naming the team |
| `POST /api/events/{id}/prfaqs` | `?force=true` | `{generated[], skipped[], failed[]}` |
| `POST /api/events/{id}/finalist` | | `{top_picks[], reasoning, audio, spoken_announcement}` |
| `GET /api/events/{id}/finalist/latest` | | the above, or null |
| `GET /api/events/{id}/export/csv` | | `text/csv` |
| `GET /api/events/{id}/export/json` | | `application/json`, the full record |
| `GET /api/events/{id}/export/bundle` | | `{status, path, files, prfaqs, message}`, and a folder written to disk |
| `GET /api/health` | `?verify=1` bills a live call to each provider | `{status, keys_configured, models, rubrics_loaded, events_count, verified?}` |

Every failure is a FastAPI error object, `{"detail": "..."}`, at the status codes
in the table above `[observed]`. `unmatched_categories` appears on a judge
response only when the model returned a category the rubric does not contain
`[observed]`.

### Outbound, and what crosses the boundary

| Service | What leaves | Grade |
|---|---|---|
| OpenRouter, chat completions with `input_audio` | **The pitch recording itself**, base64 encoded, as MP3 | `[observed]` transcribe.py:90 |
| OpenRouter, chat completions | The transcript, the rubric, the judge persona | `[observed]` llm.py:71 |
| OpenRouter, chat completions | The transcript again, for the PRFAQ | `[observed]` prfaq.py:256 |
| ElevenLabs text to speech | The review text and the finalist announcement | `[observed]` speak.py:28 |
| ffmpeg, local subprocess | Nothing leaves the machine | `[observed]` transcribe.py:40 |

The recording is a voice sample of an identifiable person, and the transcript is
their speech. Both leave the operator's machine to two third parties. The
product provides no consent gate, no retention policy, and no deletion schedule
`[observed]`. What is required of an operator here is `[undecided]`.

### Stores

| Store | Holds | Retention |
|---|---|---|
| `judge.db`, SQLite in WAL mode | The complete event record | Nothing expires it on its own. Removal is the operator's: per submission, per event, or by age with `npm run purge` `[observed]` |
| `audio_recordings/` | Every pitch as `.webm`, its MP3 transcode, and every generated review MP3 | Nothing expires it. Removed only when its submission or event is deleted `[observed]` |
| `exports/` | Bundles written by `export/bundle` | Never cleaned `[observed]` |

## 4. The core data path

One team's pitch, end to end. This is the spine.

| # | Hop | Passed | Stored | Leaves boundary | Caller sees on failure |
|---|---|---|---|---|---|
| 1 | Operator types a team name, browser `POST /api/submissions` | team name, event id | `submissions` row, status `recording` | no | error text, Start re-enabled, and the row is deleted so a failed start leaves nothing behind `[observed]` |
| 2 | `getUserMedia`, `MediaRecorder` with a format the browser says it supports | audio chunks in memory | no | no | "Microphone unavailable" plus the browser's reason `[observed]` |
| 3 | `POST /api/submissions/{id}/audio` | the recording, field `file` | `audio_recordings/{id}.webm`, status `transcribing` | no | 413, 400, or 404, surfaced verbatim `[observed]` |
| 4 | ffmpeg transcodes to mono 16 kHz 48 kbps MP3 | the file | `audio_recordings/{id}.mp3`, kept so exports carry playable audio | no | "Audio conversion failed" with ffmpeg's stderr `[observed]` |
| 5 | OpenRouter transcription | base64 MP3 | `submissions.transcript`, status `scoring` | **yes, the voice recording** | 500 "Transcription failed", status `error` `[observed]` |
| 6 | OpenRouter scoring | transcript, rubric, persona, calibration | `scores` rows | **yes, the transcript** | 500 "Scoring failed", status `error` `[observed]` |
| 7 | `_overall_score` reconciles returned categories against the rubric | scores, rubric | `reviews.overall_score` | no | 500 when no returned category matches the rubric `[observed]` |
| 8 | ElevenLabs speech | the review text | `audio_recordings/{id}_review.mp3` | **yes, the review text** | 500 "Text-to-speech failed", status `error` `[observed]` |
| 9 | Browser renders scores, plays `/audio/{id}_review.mp3` | the JSON result | status `complete` | no | error text, Start re-enabled `[observed]` |

Hops 5 through 8 run on worker threads so the event loop stays free during the
roughly thirty seconds the pipeline takes `[observed]` server.py.

## 5. Data model

Seven entities `[observed]`.

| Entity | Key | Belongs to | Holds |
|---|---|---|---|
| `rubrics` | id | | categories as JSON, scale bounds, calibration, judge persona |
| `events` | id | a rubric | name, description, status |
| `submissions` | id | an event and a rubric | team name, audio path, transcript, status |
| `scores` | id | a submission | category, score, rationale |
| `reviews` | id, unique on submission | a submission | overall score, summary, audio path, spoken text |
| `finalist_runs` | id | an event | top picks as JSON, reasoning, audio path, spoken text |
| `prfaqs` | id, unique on submission | a submission | content as JSON, rendered markdown, model id |

Foreign keys are declared and enforced with `PRAGMA foreign_keys=ON` `[observed]`.
Deletion is explicit and ordered children first, because nothing cascades
`[observed]`.

### Invariants the code assumes and does not enforce

These are the requirements a rewrite loses. None is written down anywhere else.

| Invariant | Depended on by | What breaks |
|---|---|---|
| **One score row per category per submission.** `scores` still has no uniqueness on `(submission_id, category)`; `save_scores` clears the submission's rows before writing, which enforces it in code rather than in the schema | the UI's score grid, the CSV column mapping, the export | A second writer, or a direct insert, reintroduces duplicates. Until 2026-08-23 re-judging did exactly that: 8 rows for a 4-category rubric, all 8 rendered `[observed]` |
| **A team name is unique within an event** | export filenames, the finalist round matching names back to teams | Enforced at registration since 2026-08-23, and no longer an unenforced invariant. Before that an operator could register the duplicate in the morning and discover at the finalist round that it would not run `[observed]` |
| **`submissions.status` follows recording → transcribing → scoring → speaking → complete, or error** | the UI's view of what is judged, `completed_count`, the finalist round's eligibility filter | No column constraint and no transition check. Any status can be written at any time `[observed]` |
| **A rubric's categories do not change after submissions are scored against it** | the CSV's fixed column set, the leaderboard, `_overall_score` | Rubrics sync by name, so editing a rubric file creates a second rubric rather than mutating the first. The first is never re-pointed `[observed]` |
| **`audio_path` on a submission points at a file that exists, at the absolute path recorded when it was written** | transcription, the export bundle, the `/audio` mount | Deleting files by hand leaves the row and transcription fails with "Audio file not found". Because the path is absolute, moving the project directory or restoring onto another machine breaks every reference even with the audio present `[observed]` |

## 6. Trust boundaries and account topology

There is no cloud account topology. The system runs entirely on one operator's
laptop and holds no infrastructure `[observed]`. The standing model in
`.kiro/steering/project-setup.md` describes customer AWS Organizations and does
not apply here, which is itself worth stating so nobody looks for the gap.

Authority changes hands in exactly three places `[observed]`:

1. **Browser to server.** No authentication, no session, no CSRF token. In
   `npm run dev` the server binds localhost; in `npm run start` it binds
   `0.0.0.0` and the entire API, including delete, is open to the local network.
2. **Server to OpenRouter and ElevenLabs.** API keys read from the environment,
   loaded from `.env` at import. Keys are never logged `[observed]`.
3. **Server to ffmpeg.** Invoked as an argument list with no shell, and the only
   caller-influenced element is a path the server itself constructed
   `[observed]`.

## 7. Recovered requirements

| # | Requirement | Grade | Source | Test |
|---|---|---|---|---|
| R1 | An event groups submissions and fixes the rubric they are judged against | observed | `db.create_event`, `api_create_submission` | `TestEvents` |
| R2 | An event created without a named rubric takes the most recently created rubric | observed | `rubrics.get_default_rubric_id`, `db.list_rubrics` orders by `created_at DESC` | `TestTheDefaultRubric` |
| R3 | Every `*.yaml` in `rubrics/` loads into the database at startup, keyed by name, idempotently | observed | `rubrics.sync_rubrics_to_db` | `TestAFreshCloneComesUpUsable` |
| R4 | A fresh install with no database builds one on first start and can judge immediately | observed | lifespan, `db.init_db` | `TestAFreshCloneComesUpUsable` |
| R5 | A recording is transcribed, scored against the rubric, and read back aloud in one operation | observed | `api_judge_submission` | `TestJudging`, `judge.spec.ts` |
| R6 | Browser recordings are transcoded to MP3 before transcription, and the MP3 is kept | observed | `transcribe._convert_to_mp3` | `TestEncodeAudio` |
| R7 | The overall score is a weighted average over the categories the judge actually returned | observed | `_overall_score` | `tests/test_scoring.py` |
| R8 | A category the judge returns that is not in the rubric is excluded and named, never scored | observed | `_overall_score` | `tests/test_scoring.py` |
| R9 | A judge response matching no rubric category is an error, not a number | observed | `_overall_score` raises | `tests/test_scoring.py` |
| R10 | Category names are matched case and whitespace insensitively | observed | `_norm_category` | `tests/test_scoring.py` |
| R11 | The spoken review is the model's own prose, capped, with a mechanical fallback if it is absent | observed | `_format_review_for_speech` | `TestSpeechFormatting` |
| R12 | A finalist round needs at least three completed submissions | observed | `api_run_finalist` | `TestFinalist` |
| R13 | The finalist round may only name teams that pitched, and may not place one twice | observed | `_reconcile_top_picks` | `tests/test_finalist.py` |
| R14 | A finalist name differing only in case or spacing is corrected to the registered spelling | observed | `_reconcile_top_picks` | `tests/test_finalist.py` |
| R15 | Each team's PRFAQ is written from that team's transcript and nothing else | observed | `generate_prfaq` | `TestPrfaqApi` |
| R16 | The PRFAQ's disclaimer, invented-customer label, missing-quote placeholder and provenance are rendered in Python, never requested from the model | observed | `prfaq.render_markdown` | `tests/test_prfaq.py` |
| R17 | A founder quote absent from the transcript is never invented; a placeholder is printed instead | observed | `render_markdown` | `TestTheFounderQuoteIsNeverInvented` |
| R18 | The PRFAQ assumption tally always sums to the assumption total | observed | `normalize_grade`, `_grade_counts` | `TestGradeTallyAlwaysAddsUp` |
| R19 | PRFAQ generation runs after the event, never between teams | intended: README | README, "Running it" | none |
| R20 | Nothing typed by a person or written by a model may execute as script in the operator's browser | observed | `esc` at every interpolation | `e2e/escaping.spec.ts` |
| R21 | A cell in the results CSV is never a spreadsheet formula | observed | `_csv_cell` | `TestTheCsvIsSafeToOpen` |
| R22 | Two teams whose names reduce to the same slug get distinct files in the export bundle | observed | `_unique_slugs` | `TestExportFilenamesAreUnique` |
| R23 | An event or a submission can be deleted with its children and its audio | observed | `db.delete_event`, `db.delete_submission` | `TestDeleting`, `e2e/escaping.spec.ts` |
| R24 | A destructive schema migration copies the database aside first and says where | observed | `_backup_before_destructive_migration` | `TestTheDestructiveMigrationIsRecoverable` |
| R25 | An upload larger than the ceiling is refused and leaves no partial file | observed | `_write_upload` | `TestUploadLimits` |
| R26 | Every external call retries three times on a transient failure with exponential backoff | observed | `retry` decorator | `TestRetry` |
| R27 | A truncated model response is reported as a budget problem, not a syntax error | observed | `message_content`, `extract_json` | `TestExtractJson` |
| R28 | Judging holds the event loop for no part of its run | observed | `asyncio.to_thread` at every external step | `TestJudgingDoesNotBlockTheServer` |
| R29 | The operator is told what failed, at which stage, and can retry without reloading | observed | pipeline handlers, `resetToReady` | `e2e/recording-failures.spec.ts` |
| R48 | A judged team can be re-judged from the Submissions tab. The pitch runs through the whole pipeline again from the recording, and the new scores and review replace the old ones per R31. It confirms first, because it replaces a result that may already have been read out | observed | `rejudgeOne`, `_judge_submission` | `TestRejudgingAJudgedTeam`, `judge-later.spec.ts` |
| R47 | Events older than a given age, with their recordings, can be removed in one command. Never automatically, never on a timer, and never below an age of one day | observed | `purge_older_than`, `scripts/purge.py` | `tests/test_purge.py` |
| R46 | Setting `VJ_ACCESS_CODE` requires that code on every route carrying event data, by header or by cookie. Unset, which is the default and every existing install, nothing changes. `/`, `/static/*` and `/api/health` stay open so the page can load and be checked | observed | `require_access_code` | `tests/test_auth.py`, `e2e/access-code.spec.ts` |
| R45 | Every recording that has not produced a review can be judged in one action, one team at a time, and a team that fails does not stop the rest | observed | `api_judge_pending` | `TestRecordNowJudgeLater` |
| R44 | A recording survives a failed judging and can be judged at any later time. A provider outage costs the wait, not the pitch | observed | `api_upload_audio`, `_pending` | `TestRecordNowJudgeLater` |
| R43 | Every provider timeout is roughly four times a measured call, not a guess. Transcription 90s, scoring 60s, speech 60s, and the PRFAQ 180s because it writes a document after the room has cleared | observed, measured 2026-08-23 | `transcribe`, `llm`, `speak`, `prfaq` | `TestTimeoutsTraceToAMeasurement` |
| R42 | A rubric file may claim the default with `default: true`. Without one the most recently created wins, which is R2 unchanged | observed | `rubrics.get_default_rubric_id` | `TestARubricCanDeclareItselfTheDefault` |
| R41 | The finalist round's input grows linearly with team count and is not the limit on event size. Measured at roughly 4k tokens for 3 teams, 24k for 20, 49k for 40 and 97k for 80, against full five minute transcripts | observed, measured 2026-08-23 | `llm.run_finalist_round` | `TestTheFinalistRoundScalesWithTheRoom` |
| R40 | While judging runs the operator sees elapsed time, not a fixed promise. The pipeline is usually about thirty seconds and its worst case, every provider call hanging to its timeout across three retries, is roughly seventeen minutes | observed | `startJudgingClock`, the timeouts in `judge/` | `recording-failures.spec.ts` |
| R39 | A rubric is immutable once loaded. Sync is keyed on name and only inserts, so editing a rubric file produces a second rubric and leaves every scored event on the one it was judged against | observed | `rubrics.sync_rubrics_to_db` | `TestRubricsAreImmutableOnceLoaded` |
| R38 | Team names are distinct within an event, checked at registration, matched the same way the finalist round matches them | observed | `api_create_submission` | `TestTeamNamesAreUniqueWithinAnEvent` |
| R37 | A finalist round needs at least three completed submissions, because the podium it produces is three | observed | `api_run_finalist`, `llm.run_finalist_round` | `TestThePodiumSetsTheMinimum` |
| R36 | The product is unauthenticated by default and assumes a trusted network. `npm run dev` binds localhost; `npm run start` binds `0.0.0.0` and is an explicit, separate opt-in to exposing the event to the local network, which is when R46's access code is worth setting | observed | `package.json`, README | `TestTheNetworkPosture` |
| R35 | A submission moves `recording → recorded → transcribing → scoring → speaking → complete`. `recorded` means the audio is captured and judging has not started. `error` is reachable from any stage and is not terminal: a retry re-enters at `transcribing` | observed | `api_upload_audio`, `_judge_submission` | `TestTheStatusSequence` |
| R34 | A submission's status is one of the seven the system defines | observed | `db.SUBMISSION_STATUSES` | `TestStatusIsOneOfOurs` |
| R33 | Audio is served only under the four names the system writes, and only for a submission or event that still exists. Nothing else in `audio_recordings/` is reachable | observed | `api_audio` | `TestAudioIsServedOnlyForRecordsThatExist` |
| R32 | A rubric's `judge_persona` sets tone, emphasis and what the judge values. The **shape** of the spoken review, its length, how many improvements it names and how it closes, is fixed by the product prompt and is not a rubric's to set | observed | `judge/llm.py`, `rubrics/example-hackathon.yaml` | `TestTheRubricDoesNotFightThePrompt` |
| R31 | Re-judging a submission replaces its scores and its review rather than adding to them | observed | `db.save_scores`, `save_review`, `save_prfaq` | `TestRejudgingReplaces` |
| R30 | A backup of an event is `judge.db` **and** `audio_recordings/`. The database holds every score, transcript, review and PRFAQ, and no audio | observed | schema, `submissions.audio_path` | `TestWhatABackupActuallyCovers` |

Forty-seven of forty-eight are observed and one rests only on the README.
Forty-seven carry a test. The one without, R19, is a process instruction to
the operator rather than a behaviour of the system, so no test can hold it.

R31 through R34 were findings on the first pass rather than requirements. Each
was specified here, given a failing test, and then implemented, in that order.

R30 was `[intended: README]` on the first pass and is now `[observed]`, because
writing its test showed the README's claim was wrong: it told operators that
copying `judge.db` captured the full history, while every recording sat outside
it in a directory referenced by absolute path. The requirement was corrected
before the test was written.

## 8. Operations

The operator is the monitoring. There is no metrics endpoint, no error
reporting, no alerting, and no structured logging: failures surface as an HTTP
error in the browser and a Python warning on the terminal the server was started
from `[observed]`. For a tool run by one person watching one screen for two
hours that may be correct, but it is a choice nothing records, and it means an
overnight or unattended run has no way to report anything.

| Concern | What exists | Grade |
|---|---|---|
| Readiness | `GET /api/health?verify=1` makes a live billed call to each provider and reports per-provider `ok` with a detail string. Without `verify=1` it reports only whether keys are present, which says nothing about whether they work | observed |
| Failure visibility | Each pipeline stage sets `submissions.status` to `error` and returns a 500 naming the stage. The browser prints it and re-enables recording | observed |
| Retry | Three attempts with exponential backoff on transient provider failures, on transcription, scoring, speech and PRFAQ generation | observed |
| Logging | `logging` at warning and error only, unconfigured, so it inherits uvicorn's handler | observed |
| Backup | `judge.db` plus `audio_recordings/`. The database refers to recordings by **absolute path**, so a restore into a different directory or onto a different machine breaks every audio reference even when the files were copied | observed |
| Reset | `npm run db:reset`, `npm run audio:clean`, `npm run reset` | observed |
| Schema change | A pre-events database is copied aside before the destructive migration and the location is logged | observed |
| Capacity | Measured. The finalist prompt is about 24k tokens at 20 teams and 97k at 80, so it is not the constraint. The constraint is the roughly thirty seconds of live judging per team, which is a property of the room rather than of the software | observed |

**A provider outage no longer costs the event.** Retry covers a transient
error. For a sustained one the recording is kept and the room moves on: the
operator can tick "record only" to skip the wait entirely, or let judging fail
and be told the pitch is safe. The Submissions tab shows the backlog and clears
it in one action, one team at a time because the provider is already struggling
`[observed]`. R44 and R45.

What is still not handled is the outage that lasts past the end of the event,
which is now a matter of when the operator comes back rather than of losing
anything.

**How long that failure takes to become visible** is measured rather than
guessed. On 2026-08-23 the pipeline was run against the real providers on
synthetic speech: transcription 11.6s for 166 seconds of audio, scoring 14.5s,
speech 8.0s, and the whole run 34.1s, which is the thirty seconds the UI
promises. The timeouts were 180 and 90 seconds against that, eight and six
times the work, and the speech client had no explicit timeout at all.

They are roughly four times observed now, which puts the worst case, every call
hanging through all three retries, at about eleven minutes rather than
seventeen. Four times rather than tighter because a timeout that fires on a
slow but healthy response costs a team their judging, and that is worse than
waiting.

Nothing still bounds the total and nothing cancels it: the operator's remedy is
to reload, and the status line counts elapsed so they can see the difference
between slow and dead `[observed]`.

## 9. Subsystems

No subsystem specs exist. `docs/specs/` has not been created `[observed]`. The
three candidates, if this system grows enough to need them, are the judging
pipeline, the PRFAQ generator, and the export builders.

## 10. Known defects and unowned behavior

Findings, not requirements. Nobody should preserve these by reading this
document. Four of the six recorded on the first pass have since been specified
and closed, and are now requirements R31 through R34 rather than defects. What
follows is what is left.

| Finding | Evidence | Grade |
|---|---|---|
| **A recording is served to anyone who can reach the port and has the code**, or to anyone at all when no code is set. The directory-wide exposure is gone and the code closes the open-network case. There are still no accounts and no per-team access | `api_audio`, `require_access_code` | observed |
| **`exports/` still accumulates.** Nothing expires it; `npm run exports:clean` removes them by hand and the README says so. Whether the product should own that lifecycle is Q14 | `api_export_bundle` | observed |
| **`api_list_event_submissions` issues three queries per submission.** Measured against the largest real event, 15 teams and 46 queries, at 85ms. It is called on a tab switch and not on the live judging path. Left alone deliberately: no requirement constrains it, and grouping the queries would be code no test justifies | measured 2026-08-23 | observed |
| **The order of statuses is held by a test, not by the database.** R35 pins the sequence the pipeline produces. `update_submission` will still accept any of the six in any order, which is deliberate: the pipeline is the only production writer, so a check there would buy nothing and would make every test that arranges state walk five steps | `db.update_submission` | observed |

---

The undecided items and the contradiction above are collected, each addressed to
whoever can settle it, in `docs/spec-questions.md`. **A requirement in this
document that is graded anything other than observed has not been agreed by
anyone.**

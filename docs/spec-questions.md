---
doc: analysis
skill: salvage
subject: Virtual Judge, undecided requirements
read_at:
  repo: SanvioLabs/sanviolabs-virtual-judge
  sha: d359e7c
  branch: main
  tree: clean
  date: 2026-08-23
verdict: Open
---

# Virtual Judge, the questions the code cannot answer

Every item here is a choice the code makes that nothing records a reason for. A
constant is not a requirement. `max_attempts=3` is an observed behaviour and an
undecided requirement, and the difference is the whole point of working
backwards: one of those must survive a rewrite and the other must not, and
reading the code will never tell you which.

Ordered by what the answer changes, not by where it was found. The first four
are a call agenda. The rest is the backlog.

**Where this stands.** Two of the seventeen are closed, and one is half
closed, because the answer turned out to be already in the design rather than
in someone's head. Those are marked. The rest split into two kinds, and the
difference matters:

- **Choices about what the product should be.** Q1 on authentication and the
  remaining half of Q2 on expiry. These are decisions, not defects. The current
  posture for each is now stated as a requirement with a test, so the system is
  no longer silently undecided; what remains is whether to change it.
- **Rationales nobody recorded.** Q5 through Q17, mostly of the form "why is
  this number three". These cannot be answered by reading anything. Writing a
  plausible reason next to `max_attempts=3` would destroy the only signal that
  line carries, which is that nobody knows.

**Pinned, not answered.** `tests/test_tunables.py` holds every value in the
second group to what it currently is, so changing one is a deliberate act with
a test to update rather than a drift nobody notices until a room is waiting.
That is a guard against accident. It is not an answer.

---

Q1. Should the product gain authentication?
   Status:   **Narrowed.** The current posture is no longer undecided: R36
             states it. Unauthenticated by design, trusted network assumed,
             `dev` on localhost, `start` an explicit opt-in to LAN exposure,
             and the README warns in as many words. That is now a requirement
             with a test rather than an accident nobody had named.
   Found:    `package.json`, R36
   Remains:  Whether to add a shared secret or an access code, which would let
             the tool run on a conference network rather than a trusted one.
             That is a feature decision, not a defect. Today anyone who can
             reach the port can read every transcript and delete an event
   Ask:      Pat

Q2. Should the product hold participant recordings to a retention rule?
   Status:   **Half closed.** The disclosure half is done: the README now names
             exactly what leaves the machine and to whom, says there is no
             consent step, and says nothing expires. An organiser can no longer
             run this on real people without being told. Deletion exists per
             event, per submission, and as `npm run reset`
   Found:    README "What leaves your machine", `npm run exports:clean`
   Remains:  Whether the product should expire anything on its own rather than
             leaving it to the operator. That is a policy decision with legal
             weight and it is not mine
   Ask:      Pat, and whoever runs the next event

Q3. Should the operator be able to re-judge a submission, and what should happen if they do?
   Found:    `server.py` `api_judge_submission`, `db.save_scores`
   Behaviour: Nothing guards the route. A second run inserts a second set of
             score rows. Reproduced: eight rows for a four-category rubric, all
             eight rendered in the UI. The overall score is unaffected because
             numerator and denominator double together `[observed]`
   Status:   **Closed.** R31. Re-judging replaces, which is what reviews and
             PRFAQs already did; scores was the one table that never got the
             same treatment. R35 states the transition sequence, so a retry
             re-entering at `transcribing` is now specified rather than
             incidental
   Remains:  Nothing. Reopen it if replace is the wrong call
   Ask:      Pat, only to overturn it

Q4. Which instruction wins: the rubric's "three next steps" or the prompt's "one improvement"?
   Found:    `rubrics/example-hackathon.yaml:30` against `judge/llm.py:59,67,69`
   Behaviour: Both are concatenated into the same system prompt. The rubric
             persona says always close with three specific next steps. The
             scoring prompt asks for one honest improvement, to close by saying
             the score, and to fit 150 to 170 words `[contradiction]`
   Status:   **Closed.** R32. The prompt owns the shape of the spoken review;
             a rubric's persona owns tone. Our own example rubric was the one
             overstepping, so it changed, and it now says where the boundary is
   Remains:  Nothing, unless you want the three-next-steps close in the product
             prompt instead, which is a taste call
   Ask:      Pat, only to overturn it

---

Q5. Why three retries, and why exponential backoff from two seconds?
   Found:    `judge/retry.py`, applied in `llm.py:31,98`, `transcribe.py:75`, `speak.py:12`, `prfaq.py:240`
   Behaviour: Every external call retries three times `[observed]`. No stated
             reason `[undecided]`
   Depends:  Whether it was set against a provider rate limit, and if so which
             provider, because the default models have changed since
   Ask:      Pat

Q6. Why must a finalist round have at least three completed submissions?
   Found:    `server.py:813`
   Behaviour: Fewer than three is a 400 `[observed]`. The prompt also hardcodes
             a top three
   Depends:  Whether a two-team event is out of scope or merely unimplemented,
             and whether podium size should follow team count
   Ask:      Pat

Q7. How much of each pitch should the finalist round read?
   Found:    `judge/llm.py`, `FINALIST_TRANSCRIPT_CHARS`
   Behaviour: 6,000 characters, which covers a full five minute pitch. It was
             500 until 2026-08-23, which was about a tenth of one `[observed]`
   Depends:  Whether the round is meant to re-read the pitches or to arbitrate
             between scores it already trusts. The answer sets the number rather
             than the number implying the answer
   Ask:      Pat

Q8. What is the upload ceiling protecting against, and is 100 MB the right number?
   Found:    `server.py`, `VJ_MAX_UPLOAD_BYTES`
   Behaviour: 100 MB, overridable `[observed]`. Chosen on 2026-08-22 as a guard
             rather than from a measurement `[undecided]`
   Depends:  Nothing today. It matters the first time a long session is recorded
   Ask:      Pat

Q9. Should two teams in one event be allowed the same name?
   Found:    `db.create_submission`, no uniqueness on `(event_id, team_name)`
   Behaviour: Allowed by the schema `[observed]`. Export filenames de-duplicate
             with a numeric suffix, but the finalist round refuses a duplicate
             name, so such an event cannot complete a finalist round
   Depends:  Whether to reject the name at entry or to carry an internal
             identity through the pipeline instead of matching on the name
   Ask:      Pat

Q10. Are the default models a decision or a snapshot?
   Found:    `judge/openrouter.py`, `DEFAULT_SCORING_MODEL`, `DEFAULT_TRANSCRIPTION_MODEL`
   Behaviour: `anthropic/claude-sonnet-5` scores, `google/gemini-3.7-flash`
             transcribes `[observed]`. No stated reason `[undecided]`
   Depends:  Whether these need review as models change, and whether
             transcription needs a model chosen for audio quality rather than
             for being the cheap one that accepts audio
   Ask:      Pat

Q11. Should editing a rubric change how already-judged teams were scored?
   Found:    `judge/rubrics.py`, sync is keyed on `name`
   Behaviour: Editing a rubric file creates a second rubric rather than mutating
             the first, and existing events keep pointing at the old one
             `[observed]`. The README documents this as a gotcha
   Depends:  Whether the current behaviour is the intended immutability
             guarantee, in which case it should be stated as one, or an accident
             that reads like a bug
   Ask:      Pat

Q12. Should an event with no rubric named really take the most recent one?
   Found:    `rubrics.get_default_rubric_id`, `db.list_rubrics` orders `created_at DESC`
   Behaviour: The newest rubric wins `[observed]`. On a fresh install there is
             only one, so it never surfaces until a second rubric is added
   Depends:  Whether a rubric should be marked default explicitly instead
   Ask:      Pat

Q13. What is the spoken review's word budget for, and where did 150 to 170 come from?
   Found:    `judge/llm.py:59`, and 180 to 220 for the finalist announcement
   Behaviour: Stated in the prompt and capped in code `[observed]`. No reason
             recorded `[undecided]`
   Depends:  Whether the constraint is the room's patience, the TTS bill, or a
             judgement about how long a verdict should be. Only the first two
             scale with event size
   Ask:      Pat

Q14. Should `exports/` ever be cleaned up?
   Found:    `api_export_bundle`
   Behaviour: Every export writes a new dated folder containing full transcripts
             and audio. Nothing removes them `[observed]`
   Depends:  Whether the product owns the lifecycle of what it writes to disk,
             which is the same question as Q2 in a different place
   Ask:      Pat

Q15. Is serving every recording from an open static mount intended?
   Found:    `server.py:92`, `app.mount("/audio", ...)`
   Behaviour: The whole directory is served, so any caller who knows a submission
             id gets that team's pitch `[observed]`. The UI needs playback, which
             is presumably why
   Depends:  Whether playback should go through a route that at least checks the
             submission exists and belongs to the current event. Related to Q1
   Ask:      Pat

Q16. What should happen when a provider is down mid-event?
   Found:    `judge/retry.py` covers a transient failure; nothing covers a sustained one
   Behaviour: Three attempts, then a 500 naming the stage. The team is left
             unjudged with the room waiting. There is no degraded mode, no
             queue, and no way to record now and judge later `[observed]`
   Depends:  Whether "record now, judge later" is a requirement. It is the
             difference between an outage costing one team and costing the
             event
   Ask:      Pat

Q17. How many teams is one event expected to hold?
   Found:    nothing bounds it
   Behaviour: Untested above a handful. The finalist prompt sends every team's
             scores and up to 6,000 characters of each transcript in a single
             request, so input grows linearly with team count `[observed]`
   Depends:  Whether the finalist round needs to page or summarise above some
             size, and what the README should tell an organiser to expect
   Ask:      Pat

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

**Where this stands.** Eight of the seventeen are closed and two are half closed, because the answer turned out to be already in the design rather than
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
   Note:     The backoff is not the expensive part. Two attempts of waiting is
             six seconds; the call timeouts behind them are what produce the
             seventeen minute worst case in R40. If this number is revisited,
             the timeouts are the ones that matter
   Depends:  Whether it was set against a provider rate limit, and if so which
             provider, because the default models have changed since
   Ask:      Pat

Q6. Why must a finalist round have at least three completed submissions?
   Status:   **Closed.** R37. It was never arbitrary: the prompt asks for a top
             three, so a round needs three teams to fill it. The minimum
             follows from the podium
   Remains:  Whether the podium should shrink for a two-team event, which is a
             feature rather than an unexplained constant
   Ask:      Pat, only if you want that feature

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
   Status:   **Closed.** R38. No, and the system already required it: the
             finalist round refuses to place the same team twice. It was
             enforced at the wrong end, so an operator could register the
             duplicate in the morning and find out at the finalist round, with
             the room assembled, that it would not run. Checked at registration
             now, matched the way the finalist round matches
   Remains:  Nothing, unless you would rather carry an internal identity
             through the pipeline and allow the duplicate name
   Ask:      Pat, only to overturn it

Q10. Are the default models a decision or a snapshot?
   Found:    `judge/openrouter.py`, `DEFAULT_SCORING_MODEL`, `DEFAULT_TRANSCRIPTION_MODEL`
   Behaviour: `anthropic/claude-sonnet-5` scores, `google/gemini-3.7-flash`
             transcribes `[observed]`. No stated reason `[undecided]`
   Depends:  Whether these need review as models change, and whether
             transcription needs a model chosen for audio quality rather than
             for being the cheap one that accepts audio
   Ask:      Pat

Q11. Should editing a rubric change how already-judged teams were scored?
   Status:   **Closed.** R39. No, and the behaviour is the guarantee rather
             than the accident. Sync only inserts, so a rubric an event was
             judged against can never change underneath it. It read as a gotcha
             because nothing said it was deliberate. It is stated and tested now
   Remains:  Nothing
   Ask:      Pat, only to overturn it

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
   Status:   **Closed.** R33. The mount is gone. Audio is served by a route
             that admits only the four names this system writes, and only for a
             record that still exists
   Remains:  The route is still unauthenticated, which is Q1 and not this
   Ask:      Pat, under Q1

Q16. What should happen when a provider is down mid-event?
   Status:   **Half closed.** The invisible half is fixed. The worst case is
             quantified in the spec at roughly seventeen minutes, and the UI now
             counts elapsed time instead of repeating "about thirty seconds"
             while nothing happens, so a slow run is distinguishable from a dead
             one. R40
   Found:    the per-call timeouts in `judge/`, `startJudgingClock`
   Remains:  Whether "record now, judge later" should exist, and whether the
             pipeline should have a total deadline. Both are features and both
             pick a number I would be inventing
   Ask:      Pat

Q17. How many teams is one event expected to hold?
   Status:   **Closed by measurement.** R41. The finalist prompt is about 4k
             tokens at 3 teams, 24k at 20, 49k at 40 and 97k at 80, against
             full five minute transcripts. It grows linearly and is not the
             constraint. What bounds an event is the thirty seconds of live
             judging per team, which is a property of the room
   Remains:  Nothing. It needed a measurement, not a decision
   Ask:      Nobody

---

## Recommendations

Every question above that is still open is open for one of two reasons: nobody
recorded why a number is what it is, or somebody has to decide what the product
should be. Neither is recoverable by reading the code, and inventing a
rationale would destroy the only signal those lines carry.

What is recoverable is a recommendation. These are mine, they are not history,
and none of them is in the code. They exist so the decision is a yes or a no
rather than a blank page.

| # | Recommendation | Why |
|---|---|---|
| **Q1** authentication | A single shared access code, off by default, required when `--host 0.0.0.0` is used | The posture is already "trusted network". This makes the LAN opt-in safe without changing the default experience, and it is the smallest thing that stops a stranger deleting an event |
| **Q2 / Q14** retention | Do not add automatic expiry. Add a documented post-event step and keep deletion manual | Automatic deletion of a recording somebody may still need is worse than a directory that grows. The disclosure, which was the real gap, is done |
| **Q5** retry budget | Keep three attempts. Measure one real run, then set each call timeout to roughly three times what you observe, rather than the current 180 and 90 seconds | The retries are cheap: six seconds of backoff. The timeouts produce the seventeen minute worst case, and they were never measured against a real response |
| **Q7** finalist transcript | Keep 6,000 characters | It covers a full five minute pitch and costs about 24k tokens at twenty teams. R41 measured it |
| **Q8** upload ceiling | Keep 100 MB | A real pitch is about 2 MB, so this is fifty times headroom and still bounds a runaway. It has never been hit |
| **Q10** default models | Treat as a snapshot, not a decision. Review when a model is deprecated | The only structural requirement is that the transcription model accepts audio input, which is pinned. Which model is a cost and quality choice that ages |
| **Q12** default rubric | Add an explicit `default: true` in the rubric YAML | "Most recently created wins" is surprising the first time you add a second rubric, and the surprise lands on event day |
| **Q13** word budgets | Keep 150 to 170, and 180 to 220 | They produce the roughly sixty and ninety second reads the README describes, which is the constraint that matters: the room's patience |
| **Q16** outage handling | Build "record now, judge later" before anything else on this list | It is the only failure that can cost the whole event rather than one team. Everything else here degrades gracefully |

If you take all nine as written, say so and I will work them in spec, test,
code, in that order. If you take none, this section is the record of what was
considered and rejected, which is worth more than an empty question list.


"""PRFAQ generation — turns a pitch transcript into a Working Backwards document.

This is the artifact the team walks away with. Scoring tells them where they
placed; the PRFAQ tells them what they actually built and what they have not yet
proven.

Two rules carry the whole document. Both are instructions to the model, written
into SYSTEM_PROMPT below rather than validated here:

1. **The press release and customer FAQ are written from inside the launch** —
   confident, past tense, no hedging. The Hard FAQ and the assumptions ledger are
   written from today and carry every doubt. Mixing them destroys the document,
   because a caveat in the announcement lets the writer feel a gap has been
   handled when it has only been mentioned.
2. **A claim made in a pitch is Untested.** A team that says "this saves four
   hours a week" has asserted it, not measured it. Grading generously is the one
   failure mode that makes the ledger worthless.

The model returns structured JSON. The Markdown — disclaimer, provenance, the
invented-archetype label — is rendered in Python, so the parts that must never be
dropped cannot be dropped by a model having an off day.
"""

import os

from .openrouter import RETRYABLE, complete_json, get_client, scoring_model
from .retry import retry

# PRFAQ writing is a heavier task than scoring a rubric. Overridable on its own so
# you can point it at a stronger model without changing what judges the event.
PRFAQ_MODEL_ENV = "OPENROUTER_PRFAQ_MODEL"

# A finished PRFAQ runs 12,000 to 14,000 characters, roughly 4,500 tokens. The
# ceiling has to cover that plus the model's reasoning, which is invisible in the
# output and measured at 2,500 tokens and up on a normal run. Eight thousand left
# only a few hundred tokens of headroom, and a document that ran slightly long or
# a model that thought slightly harder came back cut in half.
MAX_TOKENS = 16000

GRADES = ("Tested", "Partly tested", "Untested")


def prfaq_model() -> str:
    return os.environ.get(PRFAQ_MODEL_ENV) or scoring_model()


def _get_client():
    # Longer than scoring — this generates several thousand tokens of prose.
    return get_client(timeout=180.0)


SYSTEM_PROMPT = """You write Working Backwards PRFAQs — the Amazon format — from
recorded product pitches.

You are writing this for the team that gave the pitch. They will read it after
the event. It is a gift and a mirror: it shows them their own idea written as
though it had already launched, and then it shows them, honestly, everything they
have not yet proven.

## The two voices — the rule that makes this document work

**The press release and the customer FAQ are written from inside the launched
future.** Past tense, clean, confident. No brackets, no caveats, no grading
language, no "this has not been measured." They read like a real announcement and
a real buyer FAQ, because a Working Backwards document only does its job when it
is written as though the thing exists.

**The Hard FAQ and the assumptions ledger are written from today**, and they
carry all of the doubt.

Do not mix them. The gaps become visible by *contrast* — by what the confident
announcement cannot honestly say — not by annotation sitting in the middle of it.

**Where the pitch did not settle a detail: omit it, do not annotate it.** Leave
the price, the onboarding time, the launch date out of the prose, then record the
undecided detail as a row in the assumptions ledger. Omission is not fabrication.
The ledger is where a reader goes to find what is missing.

**The paired check.** Every caveat you keep out of the press release and the
customer FAQ has to reappear as a row in the ledger. A clean announcement above a
short ledger is worse than a hedged one, because the gaps were deleted rather
than moved. If you omitted the price from the FAQ, "there is a price" is a ledger
row. If you left the onboarding time out of Getting started, that is a ledger row
too. Check the two against each other before you finish.

## The shape of the press release

An Amazon press release runs in a fixed order, and the order is most of what
makes it read like one rather than like a product brief:

1. **Headline.** Title case. Names the customer and what changed for them.
2. **Subheadline.** One sentence, under 25 words, the benefit in plain terms.
3. **Summary.** What the product is and does, for someone who has never heard of
   it. A reader who stops here should still know what was launched.
4. **The problem**, as the customer lives it.
5. **The solution**, then the named mechanisms.
6. **The quote from the team.** It comes here, straight after the mechanism,
   because a spokesperson explains *why this was built* before the reader is told
   how to use it.
7. **Getting started.** What a customer literally does first.
8. **The customer quote.** Someone who used it, saying what changed.
9. **The closing.** One sentence telling the reader what to do next.

Write every part as though the launch already happened. A press release does not
describe a roadmap, does not say "coming soon," and does not explain what is not
built yet. Where the product genuinely has a limit at launch, state the limit as
a fact of the shipped product: "It supports primary care and orthopedics" is a
launch fact, "other specialties are planned but not yet built" is a roadmap note
and belongs nowhere in sections 1 and 2. The same holds in the customer FAQ:
"not yet," "planned," "in development," and "we're working on it" are the four
phrases that turn an announcement back into a status update.

## What you may and may not invent

Every factual claim traces to something the team said in the pitch. Do not supply
a market-size figure, a customer count, a funding round, or a benchmark they did
not state. If they said "two hours every night," write two hours every night — do
not round it or inflate it.

**The founder quote is not yours to write.** If the pitch carries the team's own
account of why they built it, quote it. If it does not — and most pitches are
about the product rather than the motivation — set `team_quote` to null. The
document will carry a production placeholder asking them for it, and the missing
account becomes a ledger row. Writing a founding motivation for someone who never
stated one is the exact failure this format exists to prevent, and "we're excited
to revolutionize" is what invention always produces.

The customer quote is the one exception, and it is always fabricated. Give the
archetype a name and a role. It will be labelled as invented in the rendered
document, so write it as a real quote and let the label do its work.

**Name the team and the speaker. Do not name anyone else.** A pitch often names a
design partner, a pilot customer, a school, a clinic, or an individual who is not
on the team and did not consent to appear in a document the team will circulate.
Refer to them by role: "a pilot customer in logistics," "the clinician running the
sessions." The role carries the same information and does not put a third party's
name into a document nobody showed them.

## Grading

Grade strictly. A claim asserted in a pitch is **Untested**. Confidence is not
evidence. Being obviously true is not evidence.

- **Tested** — the team demonstrated it live, or described a specific measurement
  with its method and scale. Rare in a pitch.
- **Partly tested** — some evidence exists but the method, scale, or conditions
  are unestablished. "We tried it with a few users" is Partly tested.
- **Untested** — asserted, believed, or inferred. Most rows will be this, and
  that is the correct outcome for a pitch.

If your ledger is short and comfortable while the press release above it reads
confident, you have hidden the gaps rather than moved them. A confident
announcement should produce a long ledger.

**The ledger is a structure, not a list.** Rows depend on each other, and saying
so is most of the ledger's value. A price nobody has set blocks any test of
whether the waitlist converts. An unbuilt integration blocks every claim about
what the product does in a real workflow. Where one row cannot be tested until
another is answered, say which, in the evidence text. Then set `cheapest_to_close`
on the single row that costs the least to settle and unblocks the most — usually
a decision or a number somebody already has, not a study anybody has to run. That
row is where the team should start on Monday, and naming it is the most useful
sentence in the document.

## Output

Respond with JSON only — no preamble, no code fences. Use this exact shape:

{
  "product_name": "What the thing is called, as the team named it.",
  "one_liner": "One sentence: who it is for and what changed for them. Under 25 words.",
  "press_release": {
    "headline": "A headline a trade publication would actually run. Name the customer and what changed. Not a slogan.",
    "subheadline": "One sentence. Who the customer is and the benefit. Under 25 words.",
    "summary": "What the product is and does, in plain language, for someone who has never heard of it. Lead with the customer's experience, not the architecture.",
    "problem": "The problem as the customer lives it, in the team's own numbers and situations.",
    "solution": "One short paragraph: how it works, in the customer's terms. The named mechanisms go in `differentiators`, which renders immediately below this paragraph as part of the same section — so do not announce them, refer to them, or say anything like 'described below'. The reader sees one continuous section.",
    "differentiators": [
      {
        "name": "The mechanism, as a short complete sentence ending in a full stop. 'It is screen-free, deliberately.' not 'Innovative design.'",
        "why": "Why this is a design constraint the rest of the product follows from, rather than a feature on a list. This is the paragraph where a generic AI product and a real one diverge."
      }
    ],
    "getting_started": "What a customer literally does first, in order, and what they have at the end of it.",
    "launch_timing": "The launch date or window, ONLY if the team stated one. A dateline is printed from it. Null if they did not say — never guess a date.",
    "closing": "One sentence: what a reader does next, in the launched world. Written as the action, not as an advertisement. Null if the pitch never said how somebody would actually get it. Never invent a URL, a price, or an availability date to fill this.",
    "team_quote": {
      "speaker": "Name if the team gave one, otherwise a role like 'Founder'",
      "role": "Their role",
      "quote": "Why they built it, in their own words from the pitch. Set the whole object to null if the pitch does not carry this — do not invent it."
    },
    "customer_quote": {
      "name": "Invented archetype name",
      "role": "Their job title and context",
      "quote": "What the customer got. Concrete and specific to the mechanism above."
    }
  },
  "customer_faq": [
    {"question": "A question a buyer asks in the first ten minutes.", "answer": "The answer, still inside the launch."}
  ],
  "hard_faq": [
    {
      "question": "A question the team cannot comfortably answer today, stated the way an outsider would ask it.",
      "why_it_bites": "What breaks, when, and in front of whom. Name who asks and by what route — 'a hospital compliance office reaches this before the first paid contract' beats 'this is a risk'.",
      "what_settles_it": "The concrete evidence that would close the question — a test, a document, a benchmark, an agreement. Something someone could go and produce. Not 'further research'."
    }
  ],
  "assumptions": [
    {
      "assumption": "The assumption, stated as a claim that could be false.",
      "grade": "Tested | Partly tested | Untested",
      "evidence": "What evidence exists today and precisely what is missing. Name the gap, and name any other row this one blocks.",
      "cheapest_to_close": false
    }
  ],
  "would_change_our_mind": [
    {
      "signal": "The falsifier, with a number in it. 'Fewer than 10% of the waitlist finishes onboarding', not 'users do not like it'.",
      "how_measured": "What you count, across what population, over what window. 'Across the first twenty teams to sign up, measured over thirty days.'",
      "why_it_matters": "What it would mean about the thesis, and what the team should do instead. Turning, not pushing harder."
    }
  ]
}

Counts: 6-10 customer FAQ entries, 6-10 hard FAQ entries, 6-9 assumptions with
exactly one marked `cheapest_to_close`, and 2-4 things that would change their
mind. Cover at minimum in the customer FAQ: what it costs, what happens to
customer data, what happens when the product is wrong, what it explicitly does
not do, how it differs from the named incumbents, and how to try it. Give 2-4
differentiators, or an empty list if the pitch genuinely described only one
mechanism.

Before you answer, count what you have written. A Hard FAQ of four questions or a
ledger of five rows is the most common way this document comes out wrong, because
a short list of risks reads as *fewer risks* rather than as an incomplete
document. If either is under its minimum, go back and find the ones you skipped:
they exist, and the paired check above is where to look for them."""


@retry(max_attempts=3, backoff_base=2.0, retryable_exceptions=RETRYABLE)
def generate_prfaq(team_name: str, transcript: str, event_name: str = "") -> dict:
    """Write a PRFAQ from a pitch transcript.

    Args:
        team_name: The team as they registered.
        transcript: The transcribed pitch — the only source material.
        event_name: Event name, for context in the prose.

    Returns:
        The structured PRFAQ dict. See SYSTEM_PROMPT for the shape.
    """
    context = f"Team: {team_name}"
    if event_name:
        context += f"\nEvent: {event_name}"

    return complete_json(
        _get_client(),
        model=prfaq_model(),
        max_tokens=MAX_TOKENS,
        what="PRFAQ",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{context}\n\n"
                    f"Here is the pitch transcript. It is the only source — everything "
                    f"in the PRFAQ traces back to it.\n\n{transcript}"
                ),
            },
        ],
    )


DISCLAIMER = """> ## ⚠️ Read this first
>
> **An AI wrote this document from a recording of your pitch. Nobody reviewed it.**
>
> It is not professionally prepared work product. No lawyer, accountant, or
> licensed professional drafted, reviewed, or approved it, and it is not legal,
> financial, tax, or investment advice.
>
> Sections 1 and 2 are written as though the product has already launched. That
> is the format — it is not a claim that any of it is true today. Section 4 grades
> what has actually been demonstrated, and for a pitch the honest answer is
> usually "not much yet." That is the useful part.
>
> **Check every fact before you put any of this in front of an investor, a
> customer, or a grant committee.**"""


def normalize_grade(grade) -> str:
    """Fold whatever the model wrote into one of the three grades.

    A model that answers "Unproven" or "Not tested" used to be counted under
    its own key, which nothing reads. The frontmatter then printed a total that
    did not equal the sum of its three grades, in a document whose stated point
    is that the counts survive being pasted somewhere else.

    Anything unrecognised becomes Untested, which is the same direction the
    prompt's own rule points: a claim that has not demonstrably been tested is
    Untested.
    """
    if not grade:
        return "Untested"
    folded = " ".join(str(grade).split()).lower()
    for known in GRADES:
        if folded == known.lower():
            return known
    return "Untested"


def _grade_counts(assumptions: list) -> dict:
    counts = {g: 0 for g in GRADES}
    for a in assumptions:
        counts[normalize_grade(a.get("grade"))] += 1
    return counts


QUOTE_PLACEHOLDER = (
    "`[QUOTE TO COME FROM THE TEAM — in your own words, on why you built this.]`"
)

QUOTE_PLACEHOLDER_NOTE = (
    "*Production placeholder, not a caveat. Your pitch described the product "
    "rather than the reason, and writing a founding motivation for you is the "
    "exact failure this format exists to prevent. Recorded in the ledger.*"
)


def render_markdown(prfaq: dict, team_name: str, event_name: str = "",
                    transcript_note: str = "", model: str = "") -> str:
    """Render a PRFAQ dict as the Markdown document the team receives.

    The disclaimer, the invented-archetype label, the missing-quote placeholder,
    and the provenance block are written here rather than asked of the model —
    they are the parts that must survive every generation, and a model that omits
    one produces a document that reads as verified when it is not.

    Older stored PRFAQs are still renderable. `differentiators` may be absent, and
    `would_change_our_mind` may hold plain strings rather than objects.
    """
    pr = prfaq.get("press_release", {}) or {}
    name = prfaq.get("product_name") or team_name
    assumptions = prfaq.get("assumptions") or []
    counts = _grade_counts(assumptions)

    # --- Frontmatter: the grade tally, above the launch voice rather than inside it ---
    out = [
        "---",
        f'title: "PRFAQ — {name}"',
        f'team: "{team_name}"',
    ]
    if event_name:
        out.append(f'event: "{event_name}"')
    out.extend([
        f"assumptions_total: {len(assumptions)}",
        f"assumptions_untested: {counts.get('Untested', 0)}",
        f"assumptions_partly_tested: {counts.get('Partly tested', 0)}",
        f"assumptions_tested: {counts.get('Tested', 0)}",
        "reviewed_by_a_human: false",
    ])
    if model:
        out.append(f'written_by: "{model}"')
    out.extend(["---", ""])

    out.extend([
        f"# PRFAQ — {name}",
        "",
        DISCLAIMER,
        "",
        f"**Team:** {team_name}",
    ])
    if event_name:
        out.append(f"**Event:** {event_name}")
    out.extend([
        "**Prepared by:** Virtual Judge (Sanvio Labs)",
        "**Source:** your recorded pitch, and nothing else",
        "",
    ])
    if prfaq.get("one_liner"):
        out.extend([f"> {prfaq['one_liner']}", ""])
    out.append("---")
    out.append("")

    # --- 1. Press release (written from inside the launch) ---
    # The order below is the Amazon press release order and is not arbitrary: the
    # team quote sits after the mechanism because a spokesperson says why the thing
    # was built before the reader is told how to use it, and the customer quote
    # sits after Getting started because it is someone reporting back from having
    # done exactly that.
    timing = (pr.get("launch_timing") or "").strip()
    date_note = (
        f"as of {timing}, the launch the team described."
        if timing else
        "as of a launch date nobody has set. The date is an assumption and is "
        "recorded as one in the ledger."
    )
    out.extend([
        "## 1. Press Release",
        "",
        f"*Written as though the product has already launched, {date_note} That is the "
        "point of the format: it is the fastest way to find out which parts of an idea "
        "are still vague.*",
        "",
    ])
    if pr.get("headline"):
        out.extend([f"### {pr['headline']}", ""])
    if pr.get("subheadline"):
        out.extend([f"**{pr['subheadline']}**", ""])
    # The summary opens bare. It carries the dateline and reads as the lead
    # paragraph of a wire story, so a heading above it would break the opening.
    # The problem and the solution are headed, the way Getting started and the
    # quotes below them are, so a team can scan straight back to either one. The
    # headings are written here rather than accepted from the model, which is why
    # any the model supplies is stripped first.
    headings = {"problem": "### The problem", "solution": "### The solution"}
    for key in ("summary", "problem", "solution"):
        if pr.get(key):
            body = pr[key].strip()
            # Remove any embedded section headers the model might have added
            if body.startswith("### "):
                body = body.split("\n", 1)[1].strip()
            # The dateline belongs at the head of the opening paragraph, the way a
            # wire story carries it, rather than stranded on a line of its own.
            if key == "summary" and timing:
                body = f"**{timing.upper()}** — {body}"
            if key in headings:
                out.extend([headings[key], ""])
            out.extend([body, ""])

    # The named mechanisms. This is where a generic AI product and a real one
    # diverge, so each one gets its own bold lead rather than a bullet.
    for d in pr.get("differentiators") or []:
        if d.get("name"):
            # The lead has to close before the explanation starts, or the bold run
            # crashes into the sentence after it.
            lead = d["name"].strip()
            if lead and lead[-1] not in ".!?":
                lead += "."
            out.extend([f"**{lead}** {d.get('why', '')}".strip(), ""])

    tq = pr.get("team_quote") or {}
    if tq.get("quote"):
        speaker = ", ".join(p for p in (tq.get("speaker"), tq.get("role")) if p)
        out.extend([f"### Quote — {speaker or team_name}", "", f"> {tq['quote']}", ""])
    else:
        # No founding account in the pitch. A placeholder is the honest output;
        # an invented motivation is the failure the format exists to prevent.
        out.extend([
            f"### Quote — {team_name}",
            "",
            f"> {QUOTE_PLACEHOLDER}",
            "",
            QUOTE_PLACEHOLDER_NOTE,
            "",
        ])

    if pr.get("getting_started"):
        out.extend(["### Getting started", "", pr["getting_started"], ""])

    cq = pr.get("customer_quote") or {}
    if cq.get("quote"):
        who = ", ".join(p for p in (cq.get("name"), cq.get("role")) if p)
        out.extend([
            f"### Quote — {who or 'Customer'}",
            "",
            f"> {cq['quote']}",
            "",
            "**[INVENTED ARCHETYPE — not a real customer, not a reference.]**",
            "",
            "*Every customer quote in a pre-launch PRFAQ is fabricated. Leave this label "
            "on it. Without the label it becomes a fake testimonial the moment the "
            "document leaves your hands.*",
            "",
        ])

    if pr.get("closing"):
        out.extend([pr["closing"], ""])

    out.extend(["---", ""])

    # --- 2. Customer FAQ (still inside the launch) ---
    faq = prfaq.get("customer_faq") or []
    if faq:
        out.extend([
            "## 2. Customer FAQ",
            "",
            "*What a buyer asks in the first ten minutes. Answered as though they could "
            "buy it today.*",
            "",
        ])
        for i, item in enumerate(faq, 1):
            out.extend([f"### {i}. {item.get('question', '')}", "", item.get("answer", ""), ""])
        out.extend(["---", ""])

    # --- 3. Hard FAQ (written from today) ---
    hard = prfaq.get("hard_faq") or []
    if hard:
        out.extend([
            "## 3. The Hard FAQ",
            "",
            "*The section that earns the document — and the point where the voice changes.*",
            "",
            "These are written from today, not from the launch. They are the questions an "
            "investor, a customer, or a regulator reaches within ninety days, and the ones "
            "you cannot comfortably answer yet.",
            "",
        ])
        for i, item in enumerate(hard, 1):
            out.extend([f"### {i}. {item.get('question', '')}", ""])
            if item.get("why_it_bites"):
                out.extend([f"**Why it bites.** {item['why_it_bites']}", ""])
            if item.get("what_settles_it"):
                out.extend([f"**What settles it.** {item['what_settles_it']}", ""])
        out.extend(["---", ""])

    # --- 4. Assumptions ledger ---
    if assumptions:
        tally = " · ".join(f"**{counts.get(g, 0)}** {g.lower()}" for g in GRADES)

        out.extend([
            "## 4. Assumptions Ledger",
            "",
            "*The load-bearing assumptions — the ones where, if the assumption is wrong, "
            "the product is wrong.*",
            "",
            f"{len(assumptions)} assumptions: {tally}.",
            "",
            "| Grade | Means |",
            "|---|---|",
            "| **Tested** | Evidence exists, is documented, and would survive an outsider reading it |",
            "| **Partly tested** | Some evidence, but methodology, scale, or conditions are unestablished |",
            "| **Untested** | Asserted, believed, or inferred — never measured |",
            "",
            "A claim made in a pitch is Untested. That is not a criticism of the pitch — it "
            "is what a pitch is. The ledger exists so you know which claims to go and prove "
            "first.",
            "",
        ])
        for i, a in enumerate(assumptions, 1):
            heading = f"### {i}. {a.get('assumption', '')}"
            if a.get("cheapest_to_close"):
                heading += "  ⬅ start here"
            out.extend([
                heading,
                "",
                f"**Grade:** {normalize_grade(a.get('grade'))}",
                "",
                a.get("evidence", ""),
                "",
            ])
            if a.get("cheapest_to_close"):
                out.extend([
                    "*This is the cheapest row in the ledger to close and the one that "
                    "unblocks the most. It is where Monday starts.*",
                    "",
                ])
        out.extend(["---", ""])

    # --- 5. What would change our mind ---
    changes = prfaq.get("would_change_our_mind") or []
    if changes:
        out.extend([
            "## 5. What Would Change Our Mind",
            "",
            "*If you observe any of these in the next ninety days, the thesis is wrong and "
            "the right move is to turn, not to push harder.*",
            "",
        ])
        for i, c in enumerate(changes, 1):
            # Older documents stored these as plain sentences.
            if isinstance(c, str):
                out.extend([f"{i}. {c}", ""])
                continue
            out.extend([f"### {i}. {c.get('signal', '')}", ""])
            if c.get("how_measured"):
                out.extend([f"**How you would measure it.** {c['how_measured']}", ""])
            if c.get("why_it_matters"):
                out.extend([f"**What it would mean.** {c['why_it_matters']}", ""])
        out.extend(["---", ""])

    # --- Provenance ---
    out.extend([
        "## Provenance",
        "",
        "**Source.** " + (
            transcript_note
            or "A single recorded pitch, transcribed automatically. Nothing else."
        ),
        "",
    ])
    if model:
        out.extend([f"**Written by.** `{model}`, in one pass, without human editing.", ""])
    out.extend([
        "**How this document is most likely to mislead you.** Every number in "
        "sections 1 and 2 is your own claim, restated inside a confident "
        "announcement. Nothing was checked, and a figure does not become evidence "
        "by appearing in a press release. Section 4 is where those same numbers "
        "are graded, and that is the section to read twice.",
        "",
        "**Not verified.** No clinician, lawyer, regulator, auditor, or customer has "
        "reviewed anything in this document. It is a structured statement of what you "
        "said and what remains unproven. It is not diligence.",
        "",
    ])

    return "\n".join(out)

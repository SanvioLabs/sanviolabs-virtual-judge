"""Three GenAI hackathon pitch transcripts (~5 minutes each) for E2E testing.

Each represents a different quality tier:
- Team NovaMind: Strong (4-5 range) — polished, working demo, clear impact
- Team ContextCraft: Medium (3-4 range) — good idea, partial execution, decent pitch
- Team YOLOship: Weak (2-3 range) — overpromises, vague demo, buzzword-heavy
"""

# ~5 minute pitch transcript — STRONG submission
PITCH_NOVAMIND = """
Hi everyone, we're Team NovaMind, and we built something we're calling MedScribe AI.

So here's the problem. My mom is a primary care physician. She sees thirty patients a day.
After each visit, she has to write a clinical note — history of present illness, assessment,
plan, medications, all of it. She told me she spends two hours every night after the kids
are in bed doing documentation. Two hours. Every single night. That's what drove us to build this.

MedScribe AI listens to the patient-doctor conversation in real time and generates a structured
clinical note that follows the SOAP format — Subjective, Objective, Assessment, Plan. It's not
just a transcript. It understands medical context. When the doctor says "let's keep you on the
metformin and add a statin," the system maps that to the correct medication list update and
generates the appropriate plan section.

Let me show you how it works. I'm going to simulate a quick patient encounter here.

So I'm the doctor. "Good morning Mrs. Johnson, how are you feeling today?" And my teammate
Sarah is playing the patient. "Well doctor, my knee has been really bothering me. It started
about two weeks ago after I went on that hike. It's mostly on the inside of my right knee,
and it gets worse when I go up stairs."

Okay, and you can see on the screen — the system is already categorizing this into the HPI
section. It's identified the chief complaint as right medial knee pain, onset two weeks ago,
aggravated by stairs, precipitated by hiking activity. It's using temporal reasoning to
structure the narrative.

Now I'll continue. "Any swelling or redness?" "A little swelling in the evening, no redness."
"On a scale of one to ten?" "About a five, maybe a seven on stairs."

Watch what happens — it's adding the associated symptoms, negative findings, and pain scale
automatically. This isn't template matching. We're using a fine-tuned model that was trained
on fifty thousand de-identified clinical notes from three health systems.

For the assessment, the system suggests "Right knee medial compartment pain, likely medial
meniscus irritation versus early medial compartment osteoarthritis." The doctor can accept,
modify, or reject. One click. And for the plan, it generates: "Conservative management with
physical therapy referral, trial of topical diclofenac, return in six weeks, X-ray if not
improving." Again, the doctor reviews and approves.

Let me talk about accuracy for a second. We ran this against a gold standard of two hundred
notes reviewed by board-certified physicians. Our structured notes had ninety-two percent
accuracy on medical facts — meaning the assessment and plan matched what the reviewing
physician would have written. The remaining eight percent were mostly stylistic differences,
not clinical errors. We flagged zero dangerous hallucinations in our test set — and yes, we
specifically tested for that because hallucination in medical AI is a patient safety issue.

Now, on the tech side. We're running Whisper large-v3 for transcription with a medical
vocabulary boost — we added twelve thousand medical terms to the token set. The note
generation uses a fine-tuned Claude model with retrieval-augmented generation pulling from
the patient's historical chart. The whole pipeline runs in under thirty seconds from end of
conversation to draft note. We deployed this on AWS with a HIPAA-compliant architecture —
encrypted at rest and in transit, no PHI in logs, and we can show you the architecture
diagram if you're interested.

For the business model, we talked to fourteen physicians in the last forty-eight hours of
this hackathon. Eleven said they would pay for this today. The average physician spends
sixteen minutes per note. At thirty patients a day, that's eight hours a week just on
documentation. If we save even half of that, we're giving doctors back an entire workday
every week. We'd charge a hundred dollars per physician per month — which is less than
two hours of their time valued at their hourly rate.

What's next? We need to expand specialty coverage — right now we're best at primary care
and orthopedics because that's what our training data covers. We need to integrate with
EHR systems — Epic and Cerner APIs for direct note insertion. And we need a proper IRB-
approved clinical validation study before we can sell to health systems.

We're not trying to replace doctors. We're trying to give them back the time that
documentation stole from their patients and their families. My mom shouldn't have to choose
between thorough notes and seeing her kids before bedtime.

Thank you. We're Team NovaMind, and we'd love to answer any questions.
"""

# ~5 minute pitch transcript — MEDIUM submission
PITCH_CONTEXTCRAFT = """
Hey, we're Team ContextCraft. So, um, we've been working on something we call ThreadWeaver.

The problem we're solving — okay, so you know how when you're working on a big project,
like a software project or a research paper, you have context scattered everywhere? You've
got Slack threads, you've got Google Docs, you've got GitHub issues, email threads, meeting
recordings, and like, your brain is the only thing connecting all of these pieces together.
And then Monday morning comes and you're like, "wait, what did we decide about the database
schema?" and you have to go digging through three different Slack channels and a Google Doc
to find the answer.

ThreadWeaver is a context synthesis engine. You point it at your information sources — we
currently support Slack, Google Docs, and GitHub — and it builds a knowledge graph of your
project context. Then when you ask a question, it doesn't just search, it synthesizes across
sources to give you the full picture.

Let me show you the demo. So I've connected it to our hackathon team's actual Slack workspace,
our shared Google Drive folder, and our GitHub repo. Now watch — I'm going to ask it: "What
was the final decision on the embedding model and why?"

And there it goes — it pulled from a Slack thread from yesterday where Jake said "let's go
with voyage-3 over ada because the benchmark shows better clustering for our use case," then
it found the GitHub issue where we documented the comparison, and it synthesized this into:
"The team chose Voyage-3 for embeddings based on superior clustering performance in your
domain-specific benchmark. This decision was made on August 8th and implemented in PR number 7."

Pretty cool right? It gives you the answer, the reasoning, the sources, and the timeline.
All in one shot.

Now, um, let me talk about how it works technically. We use a combination of — so first we
ingest documents and conversations. Each chunk gets embedded using, well, Voyage-3 actually,
which is kind of meta. But we also extract entities and relationships using an LLM pass — so
we know that "Jake" is a person, "voyage-3" is a technology choice, and "PR number 7" is a
code change. These get stored in a hybrid store — vector embeddings in Pinecone for semantic
search, and a Neo4j graph for relationship traversal.

When you ask a question, we do a two-phase retrieval. First, semantic search gets the top
twenty relevant chunks. Then we traverse the graph to find connected context — like if a
chunk mentions a decision, we pull in the discussion that led to it and the implementation
that followed. Finally, we synthesize with Claude using the full context window.

For latency, we're at about four seconds for a typical query, which — yeah, it's not instant,
but the alternative is ten minutes of manual digging, so the tradeoff is pretty clear.

Some limitations we want to be honest about. First, the ingestion is currently batch-mode —
we process new data every fifteen minutes, not real-time. So if someone just said something
in Slack thirty seconds ago, it won't be in the graph yet. Second, we've only tested this
with our team of four people. We don't know how it scales to a fifty-person engineering org
with thousands of channels and repos. The graph could get noisy. Third, the Google Docs
integration is read-only right now — we can't update docs from ThreadWeaver yet.

For the business case — honestly we haven't done extensive customer research during this
hackathon. But anecdotally, every developer and PM we've talked to has this problem. The
average knowledge worker spends almost twenty percent of their time searching for information
they know exists somewhere. If we can cut that in half for a team of ten engineers — at let's
say an average of a hundred fifty K salary — that's a hundred fifty thousand dollars in
recovered productivity per year. So charging a thousand bucks a month per team seems
reasonable.

What would we build next? Real-time ingestion is priority one. Then we want to add meeting
transcript integration — Fathom, Otter, those tools. And we think there's a really interesting
play around proactive context — where instead of you asking, the system notices you're working
on something and surfaces relevant past decisions automatically. Like a "hey, FYI, last month
the team discussed this exact question and decided X" popup.

We're Team ContextCraft, ThreadWeaver is what we built, and yeah — we think the future of
work is not about generating more content, it's about synthesizing the context you already
have. Thanks!
"""

# ~5 minute pitch transcript — WEAK submission
PITCH_YOLOSHIP = """
What's up everyone! We are Team YOLOship and we are super excited to show you what we've
been building. Okay so — are my slides working? Yeah okay cool.

So our product is called VibeCoder. And the basic idea is — what if you could just vibe and
code at the same time? Like literally. You put on your headphones, you play music, and
VibeCoder generates code that matches your energy. High tempo music? It writes aggressive,
fast algorithms. Chill lo-fi? It writes clean, readable utility functions. We think this is
going to be the future of developer productivity.

So the way it works is we use the Spotify API to analyze the audio features of whatever
you're listening to. Things like tempo, energy, valence — that's like the happiness metric —
and danceability. Then we feed those features into a prompt that tells the AI what kind of
code to generate. And we use — what model are we using Jake? — yeah we use GPT-4 for the
code generation.

Let me show you the demo. Okay so I'm going to play — let's do some Daft Punk, "Around the
World." High energy, repetitive, electronic. And I'll ask VibeCoder to write me a sorting
algorithm. And — there we go. You can see it generated a, um, it looks like a quicksort
implementation. And the variable names are kind of — they're energetic? Like instead of
"pivot" it used "drop_point" and instead of "partition" it used "breakdown." Get it? Like
a music breakdown? Pretty cool.

Now let's switch to something chill. I'll put on some lo-fi hip hop. And I'll ask for the
same sorting algorithm. And — okay there we go. This time it generated a merge sort, which
is like, more methodical and predictable, right? And the variable names are more zen, like
"harmony_left" and "harmony_right" for the sub-arrays. So you can see how the vibe of the
music influences the code style.

Um — okay let me be real for a second. Does the code always work? Um, not always. Like the
variable names are creative but sometimes they make the code harder to read. And sometimes
the choice of algorithm doesn't actually make sense for the energy level — like it once
generated a bubble sort during heavy metal, which is actually the worst possible algorithm
for "aggressive." We're still tuning the prompt engineering on that.

For the technical architecture — we've got a React frontend, a Node backend, we call the
Spotify API, we call the OpenAI API, and we put it all together. We're deployed on — actually
we're not deployed yet, it only runs locally. But we could deploy it to Vercel pretty easily.

The market opportunity here is huge. There are twenty-eight million developers worldwide, and
according to a study, seventy percent of them listen to music while coding. That's like
nineteen million potential users. If even one percent of them pay ten dollars a month, that's
— Jake, what's the math? — that's like nineteen million a month in revenue. But realistically
we'd probably start with a freemium model.

We haven't talked to any actual developers about whether they'd pay for this. But we did
get our friend group to try it and they all said it was fun. One of them said "this is
hilarious" and shared it on Twitter. So we think there's definitely viral potential here.

Some challenges. The Spotify API rate limits are pretty strict — we can only poll audio
features every few seconds so there's latency between song changes and code style changes.
Also, um, the code isn't always syntactically valid? Like maybe sixty percent of the time
it produces runnable code. And the other forty percent you have to fix some things. But
that's pretty standard for AI code generation right?

What's next for VibeCoder? We want to add support for Apple Music and YouTube Music. We
want to make a VS Code extension so you don't have to leave your editor. And we have this
crazy idea where the code actually animates to the beat while it's being generated — like
the cursor types in rhythm with the music. That would be sick for live coding streams on
Twitch.

Oh and we also want to explore hardware. What if you had a MIDI controller that let you
adjust code parameters with physical knobs? Like turn up the "abstraction" knob and it
generates more interfaces and abstract classes? We think there's a whole creative coding
hardware play here.

Anyway, we had a blast building this. Even if it's not the most practical tool, we think it
shows that coding can be creative and fun, not just functional. And who knows — maybe one
day all IDEs will have a vibe mode.

We're Team YOLOship, VibeCoder is our baby, and yeah — let us know if you want to jam!
Thank you!
"""

# --- Mock LLM responses matching the rubric categories ---
# Voice: Warm mentor-investor. Direct but encouraging. ~150 words per review (1 min spoken).

MOCK_SCORES_NOVAMIND = {
    "scores": [
        {
            "category": "Real-World Impact",
            "score": 5,
            "rationale": "This hit me personally. Fourteen doctors said they'd pay — that tells me you found something real. You're solving genuine pain."
        },
        {
            "category": "Innovation & Creativity",
            "score": 4,
            "rationale": "The clinical reasoning layer is what sets you apart. You're not just transcribing — you're thinking alongside the doctor. That's the insight."
        },
        {
            "category": "Technical Execution",
            "score": 5,
            "rationale": "A live demo that actually worked, accuracy numbers you can defend, and you built it HIPAA-aware from day one. That's serious craftsmanship for forty-eight hours."
        },
        {
            "category": "Presentation & Vision",
            "score": 5,
            "rationale": "You told a story about your mom, showed us it works, and brought it back home. No jargon, no slides. Just clarity. Beautiful pitch."
        },
    ],
    "summary": "This is the real deal. You found a problem worth solving, built something that works, and proved people want it — all in a weekend. Really impressive work. Three next steps for your team. First — go back to those fourteen doctors and get three of them running it in real appointments this month. Real usage beats any pitch deck. Second — talk to one EHR vendor about integration. Epic or Cerner. You don't need to build it yet, just learn what that path looks like. Third — write down your accuracy methodology and make it repeatable. That ninety-two percent number is your moat — protect it with rigor."
    ,"spoken_review": "Let's talk about MedScribe. The detail that stopped me was this: when the doctor says keep her on metformin and add a statin, your system updates the medication list and writes the plan section. That's not transcription. That's clinical reasoning, and it's a much harder problem than the one most teams in this space claim to be solving. Here's why that matters to everyone in this room. The easy version of any AI product is the one that moves text around. The valuable version is the one that understands what the text means and takes the right action. You built the second one, and then you did the thing almost nobody does at a hackathon — you measured it against two hundred physician-reviewed notes and you went looking for hallucinations on purpose. Your next move is to get three of those fourteen doctors using it in real appointments this month. Real usage beats any accuracy number. Overall, this scores a four point seven five out of five."
}

MOCK_SCORES_CONTEXTCRAFT = {
    "scores": [
        {
            "category": "Real-World Impact",
            "score": 4,
            "rationale": "We've all been there — digging through Slack threads at 9am on Monday. You're solving a real frustration. Next step is finding who'd pay for it."
        },
        {
            "category": "Innovation & Creativity",
            "score": 4,
            "rationale": "The graph layer on top of embeddings — that's genuinely smart. Most teams stop at vector search. You asked 'what if we also model relationships?' and built it."
        },
        {
            "category": "Technical Execution",
            "score": 3,
            "rationale": "Your demo worked and that matters. The batch delay and latency are real limitations, but honestly? For a weekend build, getting this running end-to-end is solid."
        },
        {
            "category": "Presentation & Vision",
            "score": 3,
            "rationale": "Here's a tip — that proactive context idea you mentioned at the end? Lead with that next time. That's your wow moment and you buried it."
        },
    ],
    "summary": "You've got a strong technical foundation and a real insight here. Good work — keep pushing on it. Three next steps for your team. First — get this running for a ten-person engineering team. Not your friends, a real team with real Slack history. See what breaks at that scale. Second — solve real-time ingestion. The fifteen-minute delay is the biggest gap between demo and product. Make it feel instant. Third — build that proactive context feature you mentioned. 'Hey, the team discussed this before' is your killer feature. Lead with it."
    ,"spoken_review": "ContextCraft, I want to start with what's genuinely right here, because it is right. Documentation really is broken, and everyone in this room has felt it. That instinct is worth trusting. But I want to be honest with you, because you'll hear this from every investor you meet: the pitch outran the build. Search doesn't work yet, and you haven't talked to a user. Here's the pattern worth learning from that. When a team says the market is every knowledge worker on the planet, what an investor actually hears is that nobody specific wants this yet. The teams that win narrow down until it hurts — one user, one workflow, one thing that works completely. So your next move isn't more features. It's five conversations this week with people who have this problem, and then making one thing work a hundred percent of the time. Overall, this scores a two point two five out of five."
}

MOCK_SCORES_YOLOSHIP = {
    "scores": [
        {
            "category": "Real-World Impact",
            "score": 2,
            "rationale": "I'll be honest — this is more fun than useful right now. But you clearly have creative instincts. The challenge is pointing them at a problem someone needs solved."
        },
        {
            "category": "Innovation & Creativity",
            "score": 3,
            "rationale": "The concept made me smile. Mapping music energy to code style is genuinely lateral thinking. That creative spark is valuable — don't lose it."
        },
        {
            "category": "Technical Execution",
            "score": 2,
            "rationale": "It's early and that's okay. Getting something running that you can show people takes courage. Focus next on making the core loop reliable before adding features."
        },
        {
            "category": "Presentation & Vision",
            "score": 2,
            "rationale": "Your energy is great — own that. But tighten the story. Show us the one thing that works really well instead of five things that might work someday."
        },
    ],
    "summary": "Here's what I'll remember about your team: you think differently and you're not afraid to be weird. That's actually rare and valuable. Three next steps for your team. First — talk to five developers this week. Not about VibeCoder. Just ask them: what's the most annoying part of your day? Listen for the pain. Your next product lives in those conversations. Second — pick one feature of what you built and make it work a hundred percent of the time. Reliability is what turns a toy into a tool. Third — deploy it somewhere public. Even if it's rough. Getting real strangers to try something you built teaches you more than another week of tinkering."
    ,"spoken_review": "YOLOship, you did something I wish more teams would do: you used your own product on yourselves, live, forty-one times during this hackathon, and it caught three bad deploys including a broken database migration. That's not a demo. That's evidence. And it changes how everything else you said lands, because when you tell me setup is one command, I actually believe you. The lesson for the room is that credibility compounds. Every claim you make after a real proof point gets graded more generously, and every claim before one gets discounted. You earned that. Where I'd push you is differentiation. Automatic rollback on degraded metrics is a well-trodden idea, so your story isn't the mechanism — it's that a two-person team can have it running in under five minutes for forty dollars a month. Lead with that next time. Overall, this scores a four point five out of five."
}

MOCK_FINALIST_RESULT = {
    "top_picks": [
        {
            "rank": 1,
            "team_name": "NovaMind",
            "reasoning": "A complete package — real problem, working product, and people already want to pay. This team is ready to run with it."
        },
        {
            "rank": 2,
            "team_name": "ContextCraft",
            "reasoning": "Strongest technical insight of the day. The architecture is smart and the problem is real. With more validation, this has legs."
        },
        {
            "rank": 3,
            "team_name": "YOLOship",
            "reasoning": "Most creative team in the room. Not the most practical build, but the thinking and energy here deserve recognition. Keep swinging."
        },
    ],
    "reasoning": "What a great cohort. Every team here shipped something in forty-eight hours — that alone puts you ahead of most people who just talk about ideas. NovaMind showed us what's possible when preparation meets execution. ContextCraft proved you can build real architecture under pressure. And YOLOship reminded us that the best ideas often start from people who refuse to be boring. Well done, all of you.",
    "spoken_announcement": "What a cohort. Every team here shipped working software in forty-eight hours, and I want that to land before I read any names, because most people never get past the idea stage at all. In third place: a team whose instinct about the problem was right even though the build hadn't caught up yet — and that instinct is the harder half to teach. In second place: the team that proved its own pitch by running its product on itself, live, during the event. Nothing in a slide deck beats that. And in first place: the team that took a real, personal problem — a physician losing two hours every night to paperwork — and built something that doesn't just transcribe the visit but understands it, then went and measured whether it actually worked. That combination of empathy and rigor is what turns a weekend project into a company. Congratulations to every single one of you who got up here and pitched."
}

# Map team names to their fixtures for easy lookup
TEAMS = {
    "NovaMind": {
        "transcript": PITCH_NOVAMIND,
        "scores": MOCK_SCORES_NOVAMIND,
    },
    "ContextCraft": {
        "transcript": PITCH_CONTEXTCRAFT,
        "scores": MOCK_SCORES_CONTEXTCRAFT,
    },
    "YOLOship": {
        "transcript": PITCH_YOLOSHIP,
        "scores": MOCK_SCORES_YOLOSHIP,
    },
}

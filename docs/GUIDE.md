# The whole thing, from zero

This assumes you know nothing about the app. It explains what it is for, what
each screen does, how the pieces fit, and — as much as anything — what it
deliberately refuses to do and why.

---

## 1. The problem it exists to solve

People research the Qur'an and hadith in two very different ways, and software
usually serves neither well.

**The first way is counting.** How many times does the root ص-ب-ر appear? Which
surahs? Makki or Madani? Does it occur alongside صلاة more than chance would
predict? These are questions with exact answers. A database can give them, and
a wrong answer is checkable.

**The second way is judgement.** What did al-Ṭabarī think this verse meant, and
did al-Rāzī disagree? Is this chain of transmission sound? Does this reading
survive the objections a careful critic would raise? These have no single
answer, and the honest output is a structured argument with its sources
attached, not a verdict.

Most tools collapse these. A search engine gives you the "top 20 most relevant"
verses — useful for browsing, useless for counting, and dangerous because a
ranked list *looks* like a complete one. A chatbot gives you fluent paragraphs
that may contain a verse that does not exist.

This app keeps the two separate and refuses to let the second contaminate the
first.

### The premise underneath

The Qur'an is a **closed, finite, fully-structured corpus**: 114 surahs, 6,236
ayat, 77,429 words, 130,030 morphological segments, 1,651 roots. All of it fits
in an ordinary Postgres database with room to spare.

That means retrieval does not have to be probabilistic. When you ask for every
occurrence of ع-ل-م, the answer is **all 854 of them**, computed in SQL — not
the twenty that a vector search thought were most similar. The whole "retrieval
augmented generation" apparatus that modern AI tools are built on is solving a
problem this corpus does not have.

So the language model is given a much smaller job: **reason and write about
material a database already fetched with certainty**. It never recalls text
from its weights.

---

## 2. The four rules, enforced in code

These are not prompt instructions. They are enforced by the program, and the
tests fail if they stop holding.

### Rule 1 — Scripture is rendered from the database, never generated

An agent writing a draft cannot type Arabic. It emits a placeholder:

```
{{ayah:2:255}}
{{translation:2:255|ur-jalandhry}}
{{hadith:hadith-bukhari|1}}
```

A separate renderer resolves these against Postgres. If a reference does not
exist, the output shows a visible `[UNRESOLVED …]` failure — never plausible
text. And any Arabic in the output that neither came through a placeholder nor
appears verbatim in something the run actually retrieved is treated as a
**violation**, and the draft is rejected.

A fabricated ayah is treated as a catastrophic failure, not a bug to fix later.

### Rule 2 — Every number arrives with the number chance predicts

The statistics layer will not return a finding without a null model, an effect
size, and a multiple-comparison correction when a sweep tested more than one
hypothesis.

This matters more than it sounds. Testing all 1,651 roots at p < 0.05 produces
about **83 "significant" results from noise alone**. That is the machinery by
which numerological claims get manufactured, and the correction is applied
before results are returned — not offered as a checkbox.

In the interface, this shows up as: a count is never displayed without the
baseline next to it, at the same size.

### Rule 3 — Violations before support

A hypothesis result lists `violating` **before** `supporting` — in the API
response, in the internal ledger, and on screen.

An "always" claim with one counter-example comes back **refuted**, not "97%
supported". The wording is fixed in code so no interface can soften it.

### Rule 4 — Disagreement is preserved

When four commentators hold four positions, the output is four positions, each
with its holder and their death date. Nothing collapses into a consensus
paragraph that nobody actually held.

---

## 3. What is actually in the database

| | |
|---|---|
| Qur'an text | Uthmani and Imlaei scripts |
| Morphology | Full Quranic Arabic Corpus — root, lemma, part of speech, and segment breakdown for all 77,429 words |
| Translations | 4 editions |
| Tafsir | 5 classical commentaries, 14,840 entries |
| Hadith | 6 collections, 34,178 narrations |
| Structure | Mushaf pages, juz, revelation order, concept map |
| Transmission graph | 17,850 narrator names, ~50,000 edges, 168,434 chain positions |

Every edition is licence-gated: `qra licenses` prints what is loaded, under what
licence, and what is registered but **not** shipped because its licence does not
permit it. Nothing is included quietly.

**One important gap:** there is no Arabic lexicon loaded. That means questions
about *meaning differences* between words — عِلْم versus مَعْرِفة — report
"unavailable" rather than guessing. This is a real limitation and the app says
so rather than hiding it.

---

## 4. Every screen, and how to use it

The sidebar has nine entries. Here is what each is for.

### Search — the front door

Two tabs, deliberately not blended into one box:

**Root search** is *exhaustive*. You type a root (ع-ل-م) and get every single
occurrence, with a per-surah distribution chart and a Makki/Madani split. The
badge says **exhaustive**, which means the number is a count you can rely on.

**Text search** is a *ranked sample*. It finds phrases by lexical similarity and
orders them by relevance. The badge says **ranked sample**, which means the tail
is not shown and you must not count from it.

Keeping these apart is the single most important design decision in the
interface. Merging them into one relevance-ordered list would make a number that
cannot be counted look exactly like one that can.

*How to use it:* type a root in Arabic, or an English/Urdu concept word. Click
any verse to open it in context.

### Workbench — test a claim

This is what the app was built around. You type a claim in plain English or
Urdu:

> "Quran mein sabr hamesha salah ke saath aata hai"
> (In the Qur'an, patience always comes together with prayer.)

The app **compiles** it first — showing you its reading of your claim (subject,
object, scope, claim type) before it runs anything. You confirm that is what you
meant. Then it tests it against the whole corpus and returns:

```
verdict: refuted
Refuted by 86 counter-example(s). Patience occurs in 93 ayahs and Prayer is
absent from 86 of them (92.5%). An 'always' claim does not survive a single
exception.

  coverage 7.5%   ·   chance baseline 1.4%
  7 observed vs 1.3 expected — 5.2× baseline, p=8.4e-04
```

Read that carefully, because it shows the whole philosophy. The two roots *do*
co-occur 5.2× more than chance — a real effect. And the claim is still
**refuted**, because "always" is a universal claim and 86 counter-examples
destroy it. A tool that reported "strong association found!" would be telling
you something true and letting you believe something false.

*How to use it:* state a claim with a quantifier ("always", "only", "never",
"more often than"). Vague claims get flagged as vague rather than answered.

### Patterns — three things that are painful by hand

- **Narrative diff.** The same story told across several surahs, with the
  deltas: what this telling adds, what it omits, how the order changes.
- **Conditionals.** Every conditional construction in the corpus, split into
  condition → consequence.
- **Mutashabihat.** Clusters of near-identical verses, in two tiers
  (exact repetition and close variation).

Each view states its method on the view itself. An unexplained pattern is a
Rorschach test, and this subject attracts enough of those.

### Analysis — eight deeper tools

| Tab | What it does |
|---|---|
| **Fields** | Semantic neighbourhoods — which roots cluster with which |
| **Domains** | How vocabulary distributes across subject domains |
| **Transfer** | Where a word moves between domains (e.g. commerce language used for moral accounting) |
| **Balagha** | Rhetorical features, including *iltifāt* (grammatical person shifts) |
| **Nazm** | Structural coherence — ring composition candidates within a surah |
| **Ahkam** | Legal-ruling topics and where they are grounded |
| **I'jaz** | A registry of circulating "scientific miracle" claims, with the dossier on each |
| **Sandbox** | Write and run your own test against the corpus |

The **I'jaz** tab deserves a note. It does not endorse these claims. It holds
the ones that already circulate widely so that a researcher asked about one has
the evidence, the counter-evidence and the methodological problems to hand,
rather than meeting the claim cold.

### Isnad — the transmission graph

The newest screen, and the one with no real equivalent elsewhere.

Every hadith arrives as one undivided string: the chain of transmitters followed
by the text. The app splits them heuristically and builds a graph of
who-narrated-from-whom across all 34,000 narrations.

**Hubs** lists the names the corpus flows through, with a *structural role*
computed from the ratio of what a name receives to what it passes on:

- **source** — chains end here. A Companion, or the Prophet.
- **transmitter** — a middle link, receiving and passing on in balance.
- **collector** — receives from many, passes to almost none: the compiler of
  the book, the last link in every chain he records.

This falls straight out of the graph and checks out against what is
independently known — Ibn Abī Shayba scores 16.9 and reads "collector" because
he is an author, not a transmitter.

**Find a narrator** searches all 17,850 names. Click one to see their
transmission neighbourhood drawn as a directed graph — teachers flowing in,
students flowing out, edge thickness by narration count.

**Conflation** is the panel that makes the rest honest. A node in this graph is
a **name**, not a man. Two transmitters sharing a name are one node; one man
written two ways is two nodes. The conflation report finds names whose chain
positions span more generations than one lifetime could, and flags them. It also
states plainly what it *cannot* see: two contemporaries sharing a name are
invisible to it — including the most famous case in the literature, where سفيان
is both al-Thawrī (d. 161) and Ibn ʿUyayna (d. 198).

### Research — the agent pipeline

You ask a question in English or Urdu. A pipeline of specialist agents works on
it and produces a draft with citations. Section 5 below explains how.

The important interface decision: **the Critic's report renders above the
draft**, not below it. If citations failed to resolve or counter-examples were
found, that is the first thing you see. Putting it under a well-written answer
is how a qualified result gets quoted as an unqualified one.

If no language model is configured, the answer is labelled `undrafted` rather
than dressed up. The retrieval, counts, hypothesis verdicts and citation checks
all still ran — what is missing is prose, and the app says so.

### Grammar — structural search

Search by grammatical structure rather than by word. The compiled reading of
your query sits **above** the results, because a structural query is easy to
mistype into something that means almost the right thing, and an answer to the
wrong question looks exactly like an answer to the right one.

### Notes — your own work

Notes anchored to specific verses or roots, with backlinks. Open any verse and
you see every note anyone on your team anchored to it. Filter by language and
by provenance (retrieved vs your own).

### Commons and Groups — other people

**Commons** is a public feed of posts, each of which must carry its evidence —
a finding, a citation, a hypothesis result. **Groups** is private team space
with channels.

### Review — the gate

Nothing becomes public without a named reviewer, and nobody can approve their
own work. Both rules are enforced in the service layer, not in the interface.

---

## 5. How the research pipeline actually works

When you ask a question on the Research screen, this happens:

```
planner
  ├─ corpus     ┐
  ├─ lisan      │  specialists the planner chose,
  ├─ tafsir     │  running over one shared ledger
  ├─ hadith     │
  ├─ pattern    │
  └─ nazm       ┘
        ↓
     critic          ← adversarial pass over every claim and citation
        ↓
     scribe          ← drafts, using placeholders only
        ↓
     critic again    ← re-scans the rendered draft
        ↓
     librarian       ← saves it, dedupes, harvests what was learned
```

**The ledger** is the key object. Every agent reads and writes one shared
evidence ledger: the spans retrieved, the claims made, who made them, what
supports them, and what the critic said. The draft is generated *from* the
ledger, so every sentence has a traceable origin.

**The planner** resolves which corpus terms your question actually turns on, and
picks which specialists to run. It also consults **memory** (below).

**The specialists** each do one thing: `corpus` retrieves and counts, `lisan`
handles morphology and roots, `tafsir` gathers commentary *preserving
disagreement*, `hadith` searches narrations, `pattern` runs the statistics,
`nazm` looks at structure.

**The critic** runs twice. The first pass attacks the claims before a draft
exists. The second runs after the draft is rendered, because only then can it
check that every citation resolved and no unsourced Arabic appeared.

**The librarian** saves the finding and harvests durable lessons into memory.

### Cross-run memory

Runs used to start from nothing every time — the same null result recomputed,
the same question answered twice with no sign the first answer existed.

Memory fixes that, with one hard constraint: **a memory is never a source.** It
records that a conclusion was reached; the finding it points at holds the
evidence. Recalled memories enter the ledger as *open questions*, never as
citable spans, and a red-team attack asserts that separation holds.

It stores three kinds:

- **result** — a conclusion with numbers behind it
- **dead_end** — "we looked and there was nothing there"
- **caveat** — a methodological trap found the hard way

`dead_end` matters most. Nothing records null results, which is exactly why
teams re-run them forever.

Memories go stale on three signals and are never deleted: a reviewer rejecting
the finding behind them, a corpus re-ingest (every memory records which corpus
build it was learned from), and an explicit `forget` with a stated reason.

---

## 6. The honesty machinery

Four separate mechanisms, each testing something different.

**The statistics layer** refuses to emit a finding without a null model. Covered
above.

**The red team** — `qra redteam` — runs 16 attacks against the app's own
guarantees: can a fabricated verse reach a document? can injected text in a
tafsir passage become an instruction? can one organisation see another's
unpublished drafts? can a memory be cited as evidence for itself? A *skipped*
attack fails the suite, because an attack that could not be run has demonstrated
nothing.

**The audit** — `qra audit` — walks every analytic surface and checks that none
of them reports a number without something to read it against. 14 surfaces, all
clean.

**The golden eval** — `qra eval` — 302 cases with known-correct answers, checked
against published references. This is what catches a change that quietly breaks
a count.

**Evidence levels** run through the claim registry:

| | |
|---|---|
| **L0** | explicit in the text |
| **L1** | soundly transmitted |
| **L2** | scholarly consensus |
| **L3** | linguistically possible |
| **L4** | own inference |

L0 and L1 assert what the sources *say*, so the registry refuses them without a
citation — either cite it, or claim it at L3 or L4.

---

## 7. Running it

```bash
# 1. Database
docker compose up -d db

# 2. Backend
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
export QRA_DATABASE_URL="postgresql+psycopg://qra:qra@localhost:5432/qra"

.venv/bin/python -m qra.cli initdb
.venv/bin/python -m qra.cli licenses    # read this before ingesting
.venv/bin/python -m qra.cli ingest      # ~10 min
.venv/bin/python -m qra.cli rijal build # the transmission graph

# 3. API
.venv/bin/python -m qra.cli serve       # localhost:8000/docs

# 4. Frontend
cd ../frontend && npm install && npm run dev   # localhost:3000

# 5. Check it against known-correct answers
cd ../backend && .venv/bin/python -m qra.cli eval
```

**No API keys are required.** With no model configured the agents still
retrieve, count, test hypotheses and verify citations — only prose drafting
degrades. That ordering is deliberate: the parts you would otherwise have to
check by hand never depend on a model.

### Other ways in

- **REST API** at `localhost:8000/docs`, fully documented.
- **MCP server** — `qra mcp` — exposes 14 tools (`search_root`, `get_ayah`,
  `get_morphology`, `count_occurrences`, `cooccurrence`, `get_tafsir`,
  `search_phrase`, `search_translations`, `get_root_profile`, `test_hypothesis`,
  `find_conditionals`, `similar_ayat`, `root_distribution`, `narrative_diff`) so
  Claude or any MCP client can query the corpus directly.
- **Export** to Markdown, HTML, Word, PowerPoint, PDF and Obsidian, in English
  and Urdu, with citations intact.

---

## 8. What it will not do

This is as much the point as anything above.

**It will not prove scientific facts from the text.** The app holds a registry
of circulating "scientific miracle" claims precisely so they can be examined,
not endorsed. A text cannot be a source of new empirical facts about nature; the
method that claims otherwise is unfalsifiable in both directions, and its track
record — Ṭanṭāwī Jawharī in the 1920s, Bucaille in 1976 — is poor. What the app
*will* do is show you exactly what the text says, how often, in what
distribution, against what baseline, and let you argue from there with your
sources attached.

**It will not produce a verdict where there is disagreement.** Four positions
stay four positions.

**It will not let a ranked sample look like a count.**

**It will not treat a name in an isnad as a person**, and says so on every
screen that shows one.

**It will not report reliability of a narrator.** That is something a named
critic said in a named work, and the critics disagree. The graph is derived from
chains in the corpus; it carries no verdict on anyone, and an empty gradings
list means exactly that rather than a clean record.

---

## 9. Current state

524 tests passing. Red team 16/16. Audit 14/14. Golden eval 302/302.

Built and reachable in the UI: search, workbench, patterns, analysis (8 tabs),
isnad, research, grammar, notes, commons, groups, review.

Built but **not yet reachable in the UI** — API only for now: text-science
(entropy, rhyme, stylometry), the public portal, cross-run memory, the objection
engine and critic escalation, asbāb al-nuzūl.

Known gaps: no Arabic lexicon loaded, so meaning-difference questions report
unavailable. 17% of transmission chains contain an unresolvable kinship
reference (عن أبيه — "from his father") and are broken at that point rather than
bridged, because bridging would assert a transmission the text does not contain.

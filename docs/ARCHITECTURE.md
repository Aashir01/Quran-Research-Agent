# Architecture

## The thesis

The Qur'an is a closed, finite, fully-structured corpus. That single fact should
drive every technical decision, and mostly it drives them *away* from the
standard RAG playbook:

* **Retrieval is deterministic, not probabilistic.** "The top 20 most similar
  verses" is a wrong answer to "every occurrence of root ع-ل-م". Vector search
  is an optional fourth mode here, not the foundation.
* **Approximation buys nothing.** 6,236 ayat means brute-force cosine over the
  whole vector store takes milliseconds, an all-pairs similarity scan is
  tractable, and an exhaustive count is cheaper than an index lookup would be
  on a real corpus. Every place where a large-corpus system would approximate,
  this one does not have to.
* **The model reasons; the database remembers.** The moat is the data layer.

---

## Layer 1 — Data

Postgres is the single source of truth. `ayah.id` is the canonical 1..6236
mushaf index, so it doubles as the anchor for notes, hypotheses and agent
citations — no separate id space to keep in sync.

```
surah ──< ayah ──< word ──< segment >── root
                    │                └─ lemma
                    ├──< translation >── edition
                    ├──< tafsir_entry >── edition
                    ├──< concept_ayah >── concept >── concept_root
                    ├──< ayah_link (mutashabih | parallel)
                    ├──< conditional_structure
                    └──< note_anchor >── note
```

Two invariants the rest of the system relies on:

1. **Every searchable Arabic column has a normalised twin.** `text_search` is
   produced by `arabic.search_form()` — undiacritised, letter-folded. Without
   it, "with diacritics" and "without diacritics" silently return different
   answers and exhaustiveness becomes an unverifiable claim.
2. **Every text row carries a citation payload.** `citations.py` raises rather
   than emitting a span without one.

`ingest_log` records the source URL and SHA-256 of every payload consumed, so a
corpus can always be traced back to what produced it. `/meta/provenance` serves
it.

### pgvector is optional

Used when the extension exists; otherwise embeddings live in a float array and
cosine runs in Python. On this corpus the difference is imperceptible, so
requiring the extension would be gatekeeping rather than engineering.

---

## Layer 2 — Retrieval

Four modes, four separate tools. Never blended, because they have different
guarantees and a researcher must know which they are holding:

| Mode | Implementation | Guarantee |
|---|---|---|
| Deterministic | Pure SQL over morphology | **Exhaustive.** Totals are true even when the caller pages |
| Lexical | BM25 over a hand-built inverted index | Ranked |
| Semantic | Pluggable embeddings + brute-force cosine | Ranked; **off** unless configured |
| Graph | Recursive CTEs and joins | Exhaustive within the traversal |

**Why a hand-built BM25 index.** Postgres ships no Arabic or Urdu dictionary, so
`to_tsvector('simple', …)` would be a worse version of this with none of the
transparency. The `search_posting`/`search_term` tables make scores identical
across environments and let `/search` explain any hit term by term.

**Why Postgres and not Neo4j.** The whole edge set is ~130k segment→root edges
plus a few thousand concept and link rows. Recursive CTEs carry that
comfortably. Revisit if traversals get deep.

---

## Layer 3 — Agents

Orchestrated with LangGraph over a **shared evidence ledger** — a durable object
holding the plan, retrieved spans, confirmed claims, refuted claims and open
questions. Agents write to the ledger; they do not pass prose to each other.

That choice has a concrete payoff: a claim carries the ids of the spans
supporting it, so the Critic checks support *mechanically* rather than judging a
paragraph's tone.

```
planner → [corpus | lisan | tafsir | hadith | pattern | nazm]
        → critic → scribe → critic (recheck) → librarian
```

LangGraph is an optional dependency. Without it the same sequence runs through a
plain executor with identical semantics, because the state lives in the ledger
rather than in the framework. Installing it adds checkpointing and human
interrupts; removing it changes no result.

**The Critic is what makes the tool trustworthy.** Four jobs, ordered by how
often they catch something real:

1. Re-resolve every citation against the database.
2. Downgrade any claim with no supporting span to `needs_evidence`.
3. Re-run universal claims — including the researcher's own question — as
   hypotheses over the whole corpus, hunting counter-examples.
4. Flag counts presented without a baseline, and numbers with pre-existing
   cultural weight.

**The rendering rule.** `agents/render.py` is the enforcement point, not the
prompt. Scripture reaches a document only through a placeholder that resolves to
a database row. The scanner that catches a model typing Arabic works word by
word — Uthmani orthography (wasla, superscript alef) marks a word as scripture on
its own; Urdu-only letters mark it as the agent's own prose; three consecutive
plain-Arabic words is a quotation attempt. Urdu and Arabic share a script, so
this distinction has to be made carefully or the guard either blocks every Urdu
draft or misses fabricated verses inside one.

---

## Layer 4 — Pattern engine

The differentiator, and the part with the most opinions in it.

**Statistical honesty is structural.** `analytics/stats.py` requires a named
null model to produce a finding, returns an effect size alongside every p-value,
and applies Benjamini-Hochberg across any sweep. Numerology works by reporting
the numerator and hiding the denominator; the antidote is a system in which you
cannot obtain a number without also obtaining what it would have been by chance.

**Distribution is plotted on nuzul order.** Most patterns are invisible in
mushaf order. The Egyptian standard ordering is used, and the caveat that it is
a contested reconstruction travels with every series.

**The hypothesis workbench compiles before it tests.** A rule-based compiler
turns Urdu or English into a JSON query the researcher can read and correct; an
LLM may *propose* a compilation but it is validated against the schema and
executed by the same deterministic engine. The model never touches the counting.

**Conditional mining is grounded in the morphology, not regex.** `COND` marks
the particle and `RSLT` marks the ف of the apodosis, so the protasis/apodosis
split is the corpus annotators' judgement. Structures without an explicit ف are
still captured, at confidence 0.5, using a stated heuristic (split at the second
verb) that is labelled as ours.

**Mutashabihat has two tiers.** Word-shingle similarity finds near-identical
wording. But 2:58 and 7:161 tell the same episode with different verbs and score
0.08 on shingles — so a second tier compares content-root sets and finds them at
0.85. Both are lexical and reproducible; embeddings would add a third tier
without displacing either.

**Narrative diff derives its passages from data.** Every ayah whose morphology
carries the figure's lemma, merged into contiguous passages. That is why it
works for twelve figures rather than only for the stories someone typed up: Musa
resolves to 69 passages across 34 surahs, and each is diffed against the union
of motifs for what it adds, omits and reorders.

---

## Layer 5 — Workspace

Notes anchor to corpus ids, so backlinks are exact rather than textual: type
`[[2:255]]` and the anchor is created on save. Hypotheses version rather than
edit — believed → tested → abandoned, and abandoning **requires** a recorded
reason, enforced at the service layer, because that is how a team keeps its
memory. Findings need a reviewer who is not the author before they can be
public.

Provenance is a column with a check constraint (`retrieved` /
`system_suggested` / `own_note`), not a UI convention, so the distinction cannot
be lost in transit. The three states differ in hue *and* border treatment, so
they survive greyscale and colour-blindness.

---

## One implementation, three surfaces

`qra/tools.py` is called by the agents, wrapped by the HTTP API, and exposed
over MCP. A researcher running `search_root` inside Claude and the Corpus agent
running it inside a research run execute identical code against identical data.
Adding a capability there makes it available on all three at once.

---

## Build order

The spec's phasing was followed, and the ordering matters more than it looks:

1. **Data layer + deterministic search + anchored notebook.** No agents. This
   alone beats manual concordance work.
2. **Single research agent with mandatory citations.**
3. **Hypothesis workbench + statistical honesty layer.**
4. **Multi-agent orchestration, Critic, review workflow, team layer.**

Phases 1–3 are complete and verified against the real corpus. Phase 4 is built
and runs end to end; the team layer has models, services and endpoints but no
authentication in front of them.

## What is deliberately not done

Stated plainly so nobody discovers it at the wrong moment:

* **No authentication.** `author_id` and `reviewer_id` are passed by the caller.
  Put a real identity layer in front before multi-user deployment.
* **Semantic retrieval is unconfigured**, by choice. The code path is complete
  and tested against its interface, but no embedding provider is bundled, so it
  reports itself disabled rather than silently degrading to lexical.
* **No reranker.** `semantic.rerank()` is an explicit no-op with a marker rather
  than a fake implementation.
* **Arq is wired but the default job runner is a thread.** Fine for a single
  node; move to Redis before horizontal scaling.
* **LangFuse settings exist; tracing calls are not instrumented.**
* **The golden eval set is not built.** ~50 research questions with known-correct
  citations, run on every prompt change, is the right next investment — the
  scaffolding (`tools.py`, the ledger, the Critic report) is all in place for it.
* **Lexicons are unloaded.** Lane, Mufradat and Lisan are public domain; the
  loader exists and takes a root-keyed JSONL. The OCR cleanup is the work.

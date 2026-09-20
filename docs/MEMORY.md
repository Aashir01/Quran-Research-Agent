# Cross-run memory

Every research run used to start from nothing. The same null result got
recomputed, the same confound got re-discovered, and the same question got
answered twice with no sign the first answer existed. The Librarian noticed
duplicate *questions* after a run finished; nothing carried *conclusions* into
the next one.

`qra.agents.memory` is that carry. The planner consults it before choosing
specialists, so the run is spent on what is not yet known.

## What makes this a research tool and not a cache

### A memory is never a source

This is the whole design constraint. A memory records that a conclusion was
reached; the finding it points at is where the evidence lives. Every row comes
back `citable: false`, and the planner routes recalled memories into the
ledger's **open questions** — the one channel that does not feed the citation
list. Spans become citations; memories never become spans.

The failure this prevents is subtle and fatal. The planner recalls "an earlier
run concluded X", the scribe treats that as support, and X ends up cited to a
memory of itself, with no ayah, no isnad and no finding underneath. A citation
loop like that is indistinguishable from a result until someone tries to check
it. `redteam.memory-cited-as-evidence` asserts both halves of the guarantee:
that the recall lands in open questions, and that the ledger's spans and cited
refs stay empty.

### Memory goes stale, loudly

Three separate signals withhold a memory:

| Signal | Set by | Effect |
| --- | --- | --- |
| `stale_reason` | `forget()`, or a rejected finding | Withheld until someone clears it |
| `corpus_revision` mismatch | a re-ingest | Withheld until re-learned |
| — | — | Rows are never deleted |

The corpus revision is derived from the ingest log, so it changes exactly when
the corpus changes. A count learned from an earlier build is not *wrong*, it is
*unverified*, and withholding it is the honest response to that. Re-learning it
under the current corpus brings it back.

A memory a human forgot is different. Re-deriving something a reviewer judged
wrong does not overrule them, so the stale reason survives relearning under the
same corpus. Only a corpus change clears it, because only a corpus change means
the original judgement was made against different data.

### Retractions cascade

When a reviewer sends a finding back, `invalidate_for_finding` marks every
memory pointing at it stale. Without that cascade, a conclusion the reviewers
rejected keeps being recalled by a planner that never saw the rejection — which
is how a retracted result gets laundered into work downstream of it.

### Confirmations are counted, not scored

`confirmations` is the number of **independent runs** that reached the same
statement — a fact about the history, checkable against the run log. A run
re-asserting itself does not count; two runs agreeing is evidence about the
finding, one run saying it twice is evidence about the loop it is in.

A 0-to-1 confidence score would have been easier and would have meant nothing.

## The three kinds

| Kind | What it holds | Why it earns a row |
| --- | --- | --- |
| `result` | A conclusion with numbers behind it | Saves the recomputation |
| `dead_end` | "We looked and there was nothing there" | The most valuable and least recorded |
| `caveat` | A methodological trap found the hard way | Generalises past the question that found it |

`dead_end` is the one that matters most. No system records null results, which
is exactly why teams re-run them indefinitely. A recorded dead end turns
"nobody knows" into "we checked, here is the run, and re-running it needs a
reason".

## What gets harvested, and what deliberately does not

`harvest()` takes three things from a finished ledger:

- statistics that came back **null** — keyed by their subject;
- statistics with a reported effect;
- claims the critic **refuted**.

Claims the critic *supported* are not harvested. Those belong in the finding,
where the evidence sits next to them. Lifting a supported claim into memory
produces precisely the free-floating assertion this module exists to prevent.

A statistic with no significance block is not harvested either. No verdict
means *unmeasured*, not *null*, and recording it as either would put a claim in
memory that the run never made. In a real run this is what drops the
`conditionals` statistic, which reports a match count and never claims an
effect.

### Reading the verdict

The tools nest their result under `significance` and state it directly as
`within_chance`, having already applied whatever correction they judged
necessary. `harvest` reads that rather than re-deriving significance from a raw
p-value, because the number of comparisons is known to the tool and not to this
module. Where no `within_chance` is present it falls back to `corrected_p`
before `p_value` — comparing a raw p against alpha after a correction was
applied would report an effect the analysis itself had already discounted.

This mattered in practice. The first version of `harvest` read a flat
`payload["p_value"]`, and its tests were written against that invented shape.
They passed. Against a real run it would have harvested nothing at all, because
every statistic the pattern agent emits nests its verdict one level down. The
tests now build their payloads by calling the tools.

## Keys

A memory attaches to a key naming its subject: `root:صبر`, `pair:صبر+صلو`,
`surah:2`, `concept:patience`, `method:entropy`.

On the way in, `_stat_key` derives the key from the statistic's *label*, which
the pattern and nazm agents already write structurally — `distribution:<root>`,
`cooccurrence:<a>+<b>`, `nazm:surah:<n>`. The label is a better source than the
payload, which nests its subject differently in each tool's output. Pair keys
are sorted, so asking about صبر and صلو reaches the same memory as asking about
صلو and صبر; keying them apart would hide each run's answer from the other.

On the way out, `keys_for()` builds keys from the planner's resolved corpus
terms where it has them and the question's content words otherwise, dropping
tokens of three characters or fewer. It emits the pair keys too: a question
naming two roots is usually asking whether they go together, and without them
the co-occurrence result from the last run to ask stays invisible to the next.

This is deliberately conservative. A key that matches everything recalls
everything, which is the same as recalling nothing.

## Tenancy

Memory is scoped to the principal's organisation, the same rule the prior-work
search follows: surfacing another team's conclusions is a leak, not a feature.

Building this surfaced the write half of a bug whose read half was fixed
earlier. `search_prior_work` and `review_queue` were scoped by org, but nothing
*stamped* the org on agent-written rows — the Librarian created every `Finding`
with `org_id` NULL and `_checkpoint` did the same for every `ResearchRun`. The
result: a team's own agent findings were absent from their prior-work search and
present in every org-less account's. A scoped read over unstamped writes is a
no-op. `AgentContext` now carries the principal and both writers stamp it.

## API

| Route | Does |
| --- | --- |
| `GET /memory?q=…` | Recall by keys derived from a question |
| `GET /memory?key=…` | Recall by explicit keys |
| `POST /memory` | Record or confirm |
| `POST /memory/{id}/forget` | Mark stale, with a required reason |
| `GET /memory/stats` | Totals, and how much is withheld |

`stats` separates `stale` (a human judged it) from `outdated` (the corpus moved
under it). They are withheld for different reasons and conflating them would
hide how much of the memory is actually live.

## Degradation

Memory is an optimisation, never a gate. If recall raises, the planner logs
`memory_unavailable` and continues; if harvest raises, the run is already
complete and the bookkeeping failure is logged rather than propagated. A run
that cannot recall is a slower run, not a failed one.

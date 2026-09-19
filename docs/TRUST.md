# Track H — the trust machinery

Four things an operator can run against a live build:

```
qra eval        # 302 cases, 166 ground truth, 136 regression
qra redteam     # 14 attacks on the load-bearing promises
qra audit       # every analytic surface carries its baseline
pytest tests/test_perf.py    # performance budgets
```

## Evaluation — 302 cases

Two tiers, and blurring them would be the point of failure:

- **ground_truth (166)** — verifiable outside this corpus. All 114 surah ayah
  counts, against the published Hafs numbering; the corpus was spot-checked
  against fourteen of them before the set was generated.
- **regression (136)** — computed from this corpus. Catches drift in the tool
  layer and **cannot** catch an ingest error, because both sides would move
  together. Every one carries that disclaimer in its `source_of_truth`.

The generator obeys one rule: an expected value is produced by a *different*
code path from the one the case exercises. Root counts come from raw SQL on
`segment.root_id` while the case runs `count_occurrences`; grammar counts come
from raw SQL on the promoted morphology columns while the case runs the query
language. An eval whose expectation is produced by the thing it is testing
checks nothing.

The 30 grammar cases are the most valuable: two genuinely independent
implementations of the same question, which must agree. `V:IMPV` and
`WHERE pos_class='V' AND aspect='IMPV'` both return 1,872.

Building it turned up one wrong expectation of mine — I derived the rhyme of
`ٱلصَّمَد` as *ṣam* rather than *mad*. The tool was right and the test was
wrong, which is the correct way round for that to be discovered.

## Red team — 14 attacks

A guarantee nobody has attacked is a hope. Each attack states what a *breach*
would mean, so "held" is legible.

| Promise | Attacks |
|---|---|
| Scripture is rendered, never typed | plain fabrication, fabrication laundered through Urdu prose, zero-width joiners inside every word, RTL marks, placeholder-shaped wrappers, the verified channel as a wildcard, a correctly transcribed ayah typed by hand |
| Exhaustive and ranked are never blurred | a reranked list asked to present itself as complete; a capped count that does not admit the cap |
| Evidence levels do not drift upward | an i'jaz claim stored at L0, an abrogation claim with no claimant, a legal topic asked for a ruling |
| Injected instructions are inert | prompt injection inside a tafsir passage; a span that writes the closing delimiter verbatim, assuming the nonce leaked |
| One organisation's work stays its own | a reviewer in one organisation listing another's unpublished drafts |

**An attack that cannot run is reported as `skipped`, never as held**, and skips
fail the suite. Counting an unrun attack as a defence is how a red-team suite
gets greener as the code rots.

### Cross-tenant leak

Adding the fifteenth attack found a live one. `review_queue` and
`search_prior_work` both listed `Finding` rows with **no organisation filter**,
and neither function took a principal — so it could not have filtered even if a
caller had wanted it to. A reviewer in one organisation saw another's
unpublished drafts, and the Librarian's prior-work search surfaced a different
team's research.

Both are scoped now. A principal with no organisation sees only rows that also
have none, which is the strict reading on purpose: `org_id IS NULL` meaning
"everyone's" is how this kind of filter silently stops filtering.

### The placeholder crash

It found a real bug on the first run. `_parse_ref` raised a bare `ValueError`,
and `render` catches only `RenderError` — so a researcher typing
`{{ayah:foo}}` in a post got a **500** instead of the violation the guard
exists to produce. `{{ayah:}}` did not match the placeholder pattern at all and
passed through as literal braces into published text. Both fixed; every
placeholder-shaped thing now either resolves or reports.

## Uncertainty audit

Structural, not calibration — and the distinction is the honest part.
Calibration asks whether things labelled 80% confident are right 80% of the
time, and answering it needs labelled outcomes this corpus does not have.
Claiming to audit calibration without them would be the error the audit exists
to catch, one level up.

What it does check, across 14 analytic surfaces: every surface reporting counts
names the population to read them against, every retrieval declares whether it
is complete, every derived result is marked as derived.

The baseline rule is **pattern-based, not an enumerated key list**, because an
enumerated list is gameable in one direction: when a surface fails, the cheapest
fix is to add its key to the list, and after a few rounds the audit passes
everything.

Five genuine gaps found and fixed:

- `balagha.iltifat` reported shift counts with no baseline whenever scoped to a
  surah — the common case. A researcher saw 806 shifts with nothing saying 55%
  of all ayat contain one.
- `ahkam.topic` reported marked-verse counts without the 1,946-of-6,236
  corpus rate they should be read against.
- `rijal.hubs` returned a top slice with no `exhaustive: false` and no share of
  the 20,615 names.
- `textscience.prosody` reported ending counts without the total.
- `analytics.cooccurrence` returned PMI with nothing saying PMI inflates for
  rare pairs.

One subtler fix to the audit itself: a key present with a **null** value was
counting as a baseline. `iltifat` carried `share_of_scope`, which is `None`
whenever the query is scoped — the key was there and the baseline was not.

## Performance budgets

Budgets, not benchmarks: a benchmark records a time, a budget fails the build
when a change alters how the tool can be used. Set loose on purpose, because a
budget tuned to current timings fails on a noisy box and gets deleted.

Two guard regressions that already happened once: grammar search over a
multi-pattern query took **92 seconds** before the ayah ordinal was
materialised at ingest (now 0.08s), and the common-link null model rescanned
163k chain positions per call at **16 seconds** each (now cached).

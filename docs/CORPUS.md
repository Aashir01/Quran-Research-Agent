# Corpus expansion (Track C)

What is loaded, what is computed from it, and what is honestly missing.

## WP-19 — Grammar search

A structural query language over the 130,030 analysed segments. Exhaustive like
the other deterministic modes: the count is every match in the corpus.

```
V:IMPV P                      an imperative verb immediately governing a preposition
tag:COND > V:PERF @makki      a conditional particle, a perfect verb later, Makki only
root:صبر+V:IMPF               imperfect verbs from ص-ب-ر
tag:NEG V:IMPF:JUS            negation with a jussive
```

* **POS** — `N` noun, `V` verb, `P` particle, with features after colons in any
  order (`V:PERF:PASS:3:M:P`).
* **Keys** — `root:` `lemma:` `tag:` `form:`.
* **`+`** joins constraints on one segment; a space means *immediately
  adjacent*; **`>`** means *anywhere later in the same ayah*.
* **Scope** — `@makki` `@madani` `@surah:N` `@juz:N`.

A mistyped feature is a 422 explaining what to fix, never an empty result set.
An empty answer to a typo and an empty answer to a good question look identical,
and that difference is what separates a tool from a trap.

Twenty worked examples live in `grammar.EXAMPLES` and run as tests, so a
re-ingest that changes a count fails the build.

**One performance note that is really a correctness note.** `Segment.position`
counts within its *word*, so the last segment of one word and the first of the
next both read as position 1 — adjacency is inexpressible without a global
ordinal. Deriving it per query with a window function made `V:IMPV P` take **92
seconds**; `Segment.ayah_index` is materialised at ingest and the same query now
runs in 163ms.

## WP-20 — Asbab al-nuzul, as graded reports

An occasion of revelation is a *claim someone transmitted*, not a property of an
ayah. Filed as commentary it reads as settled context, which is the line the
interviewed researchers drew.

So `asbab_report` carries a claimant and a grade, and the grade is added during
**serialisation** — no caller can forget it. `ungraded` is stated to mean *nobody
in this corpus has graded it*, not *weak*.

**This work package uncovered a live corpus bug.** The 992 al-Wahidi entries
were served as ordinary tafsir, and the shipped edition is filed sequentially
rather than by verse:

| | |
|---|---|
| Entries citing their own verse in-text | 690 |
| …filed under a **different** verse | **673** |
| Withheld as commentary, not asbab | 770 |
| Published reports | 222, covering 216 ayat |

A researcher opening **2:9** (*"they deceive Allah"*) was shown a report about
**2:113** (*"the Jews say the Christians follow nothing"*). Reports are now
anchored to the verse each one cites inside itself; anything resting on the
upstream filing is marked `mapping_confidence: 0.25` and says so. Asbab no
longer leaks through the tafsir path, where it arrived mis-anchored *and*
stripped of its grade.

Coverage is **3.46%** and published as such. Most of the Qur'an has no
transmitted occasion of revelation, and implying otherwise would be inventing
history.

## WP-21 — Takhrij

The question worth asking of a narration is not "is this one sahih" but *where
else is this narrated, through whom, and how did each collector grade it*. That
is now computable over the 34,178 narrations already ingested.

**Compare matn, not rows.** The chain is what *differs* between two collections
carrying the same report. `qra/analytics/isnad.py` separates chain from matn
(89% of the corpus reliably) and every result reports how much to trust that
split. Where the split failed, the whole row is compared and the parallel is
capped at `possible` — a score computed over chain words is not evidence about
the report.

**Overlap, not Jaccard.** Collectors abridge differently; Jaccard punishes a
length difference and overlap does not.

**The threshold was calibrated, not guessed.** Sampling 1,500 narrations and
reading pairs at each score:

| Score | What the pairs actually are |
|---|---|
| 0.7+ | plainly the same report |
| 0.5 | the same report |
| 0.4 | often an abridgement or a *وذكر نحوه* cross-reference |
| 0.3 | shared formulaic phrasing |

So results are **banded** — `strong` ≥ 0.6, `probable` ≥ 0.45, `possible` below
— rather than cut at one number. Whether a weak match matters depends on whether
you are surveying or citing, and that is the researcher's call.

Bukhari 1825 and Muslim 2525 come back as a strong pair at 0.67, symmetrically.

Every parallel carries its own grade and grader. A narration sahih in one
collection and da'if in another is a fact about the transmission, reported
rather than reconciled.

## What is not built, and why

These need data the repo does not have and cannot lawfully bundle. The gap is
acquisition, not code.

| WP | Status |
|---|---|
| **WP-16** Classical lexicons | `lexicon_entry` is empty. Lane, Mufradat and Lisan need OCR and a human review pass — the spec itself says "the work is OCR cleanup, not code". |
| **WP-17** Diachronic semantics | Blocked on WP-16 and WP-25. |
| **WP-18** Qira'at | Needs a variants dataset with transmission chains. |
| **WP-22** Classical library | Spec calls for "a documented path plus a loader", not a bundle. |
| **WP-23** Document OCR | Needs an OCR runtime; the provenance separation is the real deliverable. |
| **WP-24/25** Comparative and pre-Islamic corpora | Licensing-gated. |

Reporting these as absent is deliberate. A lexicon endpoint returning nothing is
honest; one returning plausible glosses from a model would be the exact failure
this project exists to prevent.

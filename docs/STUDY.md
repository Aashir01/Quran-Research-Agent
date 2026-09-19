# Study series and the trainer

Two teaching surfaces over the corpus. Both obey the same rule as everything
else in this application, with the stakes moved one step further out: a mistake
here does not sit in a document, it sits in someone's memory.

## The trainer

Spaced repetition over three card kinds, each with an answer the corpus can
check:

- `reference_recall` — given 2:255, recall the verse
- `morphology` — given a word, name its root and part of speech
- `root_location` — given a root, name a surah it occurs in

**No card stores scripture.** A card row holds `2:255`; the text is rendered
from the database at review time. A stored copy is one that can drift, and here
the drift would be silent and in the learner.

**No meaning cards.** The obvious vocabulary card — root to gloss — cannot be
generated, because no lexicon is loaded and inventing a gloss would be the
scripture-fabrication failure with the consequence moved into the learner's
memory. `GET /study/trainer` lists it as unavailable and names what unlocks it.
Same gate as `fields.distinctions`, same reason.

**A card that points at nothing is refused at creation**, by rendering it once
before it joins the session. A card whose subject does not resolve otherwise
fails silently at review time, weeks later.

### Scheduling

SM-2, and it is described as what it is: a scheduling convention with modest
evidence behind it, not a finding about memory. The interval is a suggestion
about when to look again.

The ease floor of 1.3 matters more than it looks — without it a repeatedly
failed card gets a shorter and shorter interval until it appears every session,
which is the point at which people abandon a deck.

`GET /study/trainer/stats` reports the scheduler's own record: of the cards it
called due, how many were actually remembered. First sightings are excluded,
because they test the material rather than the interval. SM-2 aims for roughly
90% recall on scheduled reviews; well below means the intervals are too long for
this material, well above means they are too short and time is being wasted.
Either way it is a number about the schedule, not about the learner. A scheduler
that never reports this is asserting its intervals rather than testing them.

## Series

An ordered curriculum. A series is an **editorial** object in the way the life
domains are: deciding that the conditional structures come before the oath forms
is a teaching judgement, not a fact about the text, and `provenance` says so on
every row.

**Items point at corpus objects and never carry text.** A series that stored the
verse could disagree with the corpus, and a learner has no way to notice.

**Items are validated at authoring time.** A broken step discovered by a learner
mid-sequence is a broken sequence, so an ayah that does not exist, a root that
is not in the corpus, an unknown concept slug or an unparseable grammar query
are all refused when the series is written.

Three series ship, built from what the corpus already answers exhaustively:
the short Makki surahs in revelation order, the twenty commonest roots, and
conditional structure. They are starting points; the interesting series are the
ones a teacher writes.

A series can seed trainer cards. Concept and grammar-query steps are skipped —
those are things to read, not things to recall.

## One naming fix worth recording

`qra/study/__init__.py` originally re-exported a function called `series`
alongside the module `qra.study.series` that defines it. `from qra.study import
series` then handed back the function, and every attribute access on it failed.
The function is `get_series` now.

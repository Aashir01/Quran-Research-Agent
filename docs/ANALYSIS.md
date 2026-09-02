# Track D — the analysis engines

Nine engines. What they have in common is that each was designed backwards from
a way it could be misused, and the guard is structural rather than advisory.

| WP | Engine | Module | The failure it is built against |
|----|--------|--------|----------------------------------|
| 26 | Nazm and ring structure | `qra.analytics.nazm` | Chiastic readings can be constructed for almost any text |
| 27 | Balagha | `qra.analytics.balagha` | A segment-level person scan reads Arabic object suffixes as rhetorical shifts |
| 28 | Semantic fields | `qra.analytics.fields` | Distributional neighbours look like synonyms and are often opposites |
| 29 | Ayat al-ahkam | `qra.analytics.ahkam` | One stored position rendered as the answer turns a research tool into a fatwa engine |
| 30 | Naskh | `qra.analytics.naskh` | An `is_abrogated` boolean erases a millennium of disagreement |
| 31 | I'jaz claims | `qra.analytics.ijaz` | A generator of scientific-miracle claims |
| 32 | Life domains | `qra.analytics.domains` | A root list that silently loses an entry produces a wrong verse set that looks normal |
| 33 | Numerical sandbox | `qra.analytics.sandbox` | Forty hypotheses presented as two |
| 34 | Cross-corpus transfer | `qra.analytics.transfer` | A property of Arabic mistaken for a property of the Qur'an |

All routes are under `/analysis`.

## What ships empty, and why

Three tables ship with no rows. That is the design, not an unfinished feature.

- **`naskh_claim`** — abrogation is a claim with a claimant. `claimant` and
  `source_work` are non-nullable, so no code path can mark a verse abrogated on
  nobody's authority.
- **`madhhab_position`** — `ahkam.topic()` returns `ruling: null` until more
  than one school is on record, and says which case applies. Inventing four
  positions to fill a screen would be a fabrication with a jurisprudential
  consequence.
- **`lexicon_entry`** — see below.

`ijaz_claim` is the exception: `qra seed` loads ten claims that already
circulate, because the point of that module is to have the dossier ready when a
researcher is asked about one.

## The lexicon gap (WP-28)

The semantic-field engine computes distributional neighbours, antithesis
candidates by lift, and revelation-order spread. It does **not** compute the
*distinctions* between near-synonyms — `علم` against `معرفة`, `خوف` against
`خشية`. Those are lexicographic judgements with a citable source, and no
lexicon edition is loaded by default.

`fields.distinctions()` therefore reports `available: false` and says what is
missing. It never infers a distinction from frequency and prints it in the same
typeface as a citation. To close the gap, supply a root-keyed JSONL and load it:

```
qra ingest lexicon --slug mufradat   # expects data/raw/lexicon-mufradat.jsonl
```

See `docs/LICENSING.md`. The loader takes a file you provide rather than
pretending to fetch one, because the public-domain lexicons have no source this
project trusts for machine-readable accuracy.

## Results worth knowing

**Ring structure does not survive a null model.** Across the 60 surahs long
enough to test, one clears p<0.05 uncorrected — against 3.0 expected by chance —
and none survives correction. Ring readings of individual surahs are widely
published; this is what happens when the same claim meets a shuffled-passage
null. The null is conservative for a stated reason (real passages are more
vocabulary-distinct than shuffled ones, and mirror pairs are the most separated
pairs in the sequence), so a negative means this measurement finds no ring —
not that none is there.

**Person shifts are ordinary.** 3,449 of 6,236 ayat contain at least one, so
"this ayah shifts person" is close to no information. `balagha.hotspots()`
assesses per-surah density against that baseline instead.

**The economics vocabulary is Madani-weighted**, at 0.60× the corpus Makki
baseline (p≈3e-39) — uncontroversial history, and a check that the domain
machinery measures something real.

**`أنزل` is used of scripture, rain, cattle and clothing**, 183 times across the
corpus. The semantic-load check surfaces that next to any claim that needs it to
mean physical descent from space.

## Sandbox discipline (WP-33)

The session is the unit of correction, not the test. `summary()` puts
`headline` before `tests` — "You tested 40 hypotheses; 2.0 significant results
are expected by chance alone" — and running a forty-first test re-corrects the
previous forty, so an early striking result can be pulled back inside chance by
what came after it. Tests are pre-registered: the claim and null model are
written before the count exists, and a test cannot be run twice.

Results are watermarked and are not exportable as findings without reviewer
sign-off.

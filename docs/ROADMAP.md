# Roadmap

Where this application is strong, where it is behind real scholarship, and what
is being built to close the gap.

## What this tool will not do

It will not generate claims that the Qur'an anticipated modern science.

This is a design position, not a missing feature, and the reason is a matter of
evidence rather than of reverence. A text cannot be the source of a new fact
about nature. If a reading suggests something about physics, the only way to
know it is true is to test it against nature — and then nature established it,
not the text. If it comes out false, the conclusion drawn is always that the
*reading* was wrong. A method that cannot fail cannot confirm, and the whole
exercise sits outside the reach of evidence in either direction.

The historical record is unkind to the attempt. Tantawi Jawhari's tafsir read
electricity and wireless telegraphy into the text in the 1920s and now reads as
a period piece; Bucaille's 1976 book is the template for most modern i'jaz-ilmi
material and is taken seriously by neither scientists nor careful mufassirun.
The classical objection is the stronger one: binding an eternal text to
transient scientific theory subordinates the permanent to the temporary, and
every revision in the science forces a retraction in the exegesis.

`qra.analytics.ijaz` therefore *evaluates* circulating claims and cannot produce
one. Its semantic-load check is the honest instrument: أنزل appears 183 times
across the corpus, used of scripture, rain, cattle and clothing, so "iron
descended from space" is visibly one reading among several — demonstrated from
the morphology rather than argued.

**What replaces it** is more ambitious and produces findings that are actually
new. Real mathematics on this corpus yields real results about the text and its
transmission: isnad network science over 34,178 narrations, stylometry and
information theory across the revelation order, quantitative prosody, matn
variance at scale. Those are discoveries. The other thing is not.

## Scorecard

Genuinely ahead of the field:

- Exhaustive deterministic retrieval over 130,030 morphological segments, with a
  type-level guard that prevents a ranked result being returned where a complete
  one was promised
- No count is rendered without its chance baseline; every sweep is
  Benjamini-Hochberg corrected
- Scripture is template-rendered from the database and a fabricated ayah is
  structurally unrepresentable
- Registries that ship empty by design — abrogation claims require a claimant,
  legal topics refuse to render a ruling until more than one school is on record

Behind real scholarship:

| Gap | Status |
|---|---|
| Rijal — narrator biographies, reliability grading | **Track I** |
| Lexicons — Lane, Mufradat, Lisan all unloaded | **Track I** |
| Isnad analysed as a graph, not just parsed | **Track I** |
| Qira'at — variant readings | **Track K** |
| Quantitative text science — stylometry, information theory, prosody | **Track J** |
| Manuscript layer — Sanaa palimpsest, Birmingham folios | later |
| Tafsir breadth — no Razi, Zamakhshari, Ibn Ashur | later |

## How researchers actually work

The build order below follows the classical method rather than a feature list.

**Qur'an.** *Lugha* (what can the word bear?) → *i'rab* (syntax) → *asbab
al-nuzul* (occasion) → *qira'at* (variant readings) → *munasabat* (coherence
between verses) → *nasikh wa-mansukh* → then tafsir, transmitted before
reasoned. The discipline is to establish what the Arabic *can* mean before
proposing what it *does* mean, which is why the lexicon gap is the most damaging
one in the list above.

**Hadith.** *Takhrij* (trace every occurrence to its sources) → *isnad*
criticism → *rijal* (who met whom, who was reliable) → *'ilal* (hidden defects)
→ *matn* criticism. Modern academic work adds isnad network analysis: the common
link of Schacht and Juynboll, and Motzki's *isnad-cum-matn* method, which dates
a tradition by where its chains converge.

## Track I — hadith science at scale

The largest gap and the largest opportunity. The corpus already holds 34,178
narrations with parsed isnads and nothing analyses them.

- Narrator entities with generation, teachers, students, and the classical
  gradings, each attributed to the critic who gave it
- The transmission graph as a graph: centrality, community detection, path
  analysis between collections
- Common-link detection with a null model — a convergence that a randomised
  graph of the same shape reproduces is not a common link
- Matn variance across collections: where the wording drifts, computationally

## Track J — quantitative text science

Where mathematics genuinely applies, with the same null-model discipline as
everything else.

- Stylometry across the revelation order: lexical richness, hapax rates, register
- Information theory: entropy, conditional entropy, Zipf deviation, mutual
  information between roots
- Prosody: fasila modelling, syllable structure, quantitative saj'

## Track K — the lexical and variant layer

- Lane's Lexicon (public domain) loaded and keyed by root, unblocking the
  distinctions half of the semantic-field engine
- Qira'at: the canonical variant readings, because a claim about what a word
  means is unsound without them

## Tracks E–H

Carried over from the original specification: deep-research agent and objection
generation (E), workspace and export surfaces (F), institutional review and
multi-tenancy (G), evaluation expansion to 300 cases and the red-team suite (H).

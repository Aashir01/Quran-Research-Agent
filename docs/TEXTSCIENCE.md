# Quantitative text science

Mathematics applied to the Qur'an — which means mathematics applied to *a text*.
Information theory and stylometry measure how predictable a word sequence is,
how a vocabulary renews itself, how verses rhyme. They produce real, falsifiable
numbers, and none of them is a fact about physics or biology. A text can be a
source of facts about itself; it cannot be a source of facts about nature.

Everything below is computed from the corpus in this repository and reproducible
with `GET /analysis/text/...`.

## The measurement problem that governs the whole module

Three times in building this, the obvious statistic turned out to be a disguised
measure of **length**:

| Statistic | The flaw | What is used instead |
|---|---|---|
| Type-token ratio | Falls as text lengthens, so al-Baqara "scores lower" than al-Kawthar for being long | Yule's K and a moving-average TTR |
| Share of verses sharing the commonest rhyme | Falls as a surah lengthens | Entropy-based concentration, normalised to the surah's length |
| Entropy of a corpus | Grows with sample size | Control truncated to the Qur'an's exact token count |

Each would have produced a confident, publishable, wrong comparison. Tests
assert the robustness directly: over a tenfold change in length Yule's K moves
under 5% where the type-token ratio moves by a factor of ten.

## Information theory, against a control

The hadith corpus is the control — same language, same register, same period,
different author — **with the chains of transmission stripped**. An isnad is
formulaic by construction, the same two dozen names across tens of thousands of
narrations, and leaving it in depressed the control's vocabulary by a fifth and
would have made the Qur'an look varied for reasons of genre.

Both corpora truncated to 77,429 words:

| | Qur'an | Hadith (matn only) |
|---|---|---|
| Letter entropy | 4.117 bits | 4.112 bits |
| Word entropy | 11.014 bits | 9.945 bits |
| Conditional entropy H(next \| current) | 3.932 bits | 3.658 bits |
| Zipf slope | −0.933 | −0.988 |
| Distinct words | 14,636 | 11,095 |

Letter entropy is all but identical, as it must be for two texts in the same
script — a large gap there would mean the measurement was broken. Both corpora
sit near a Zipf slope of −1, which is why "the Qur'an follows Zipf's law" is a
fact about language and not about the Qur'an.

What the control does establish: at matched length the Qur'an carries **32% more
distinct words** and a higher conditional entropy, meaning the next word is less
determined by the current one. Read the differences; never the absolutes.

## The Makki/Madani distinction, measured

A commonplace of the literature — Makkan surahs short and rhythmic, Madinan ones
long and discursive — almost always asserted rather than measured. Six
length-robust measures, Welch's t (unequal variances and unequal group sizes),
Cohen's d beside every p, Benjamini-Hochberg across the family. 66 Makki and 26
Madani surahs of 60 words or more.

| Measure | Makki | Madani | d | p | Survives |
|---|---|---|---|---|---|
| Mean words per ayah | 9.34 | 17.81 | −1.72 | <1e-15 | yes |
| Mean word length | 4.17 | 4.32 | −1.10 | 6.0e-06 | yes |
| Hapax rate | 0.546 | 0.472 | 0.56 | 0.017 | yes |
| Lexical richness (MATTR) | 0.882 | 0.860 | 0.63 | 0.033 | yes |
| Vocabulary concentration (Yule's K) | 49.9 | 73.5 | −0.71 | 0.035 | yes |
| **Rhyme concentration** | **0.495** | **0.523** | **−0.13** | **0.52** | **no** |

Five of six survive, several at large effect sizes. The distinction is real and
quantifiable.

**The sixth is the interesting one.** Makkan surahs are widely held to be more
tightly rhymed. On a length-robust measure they are not — the difference is
negligible and nowhere near significance. A module that only ever confirms what
it was pointed at is not measuring anything, and this is the result that shows
it could have come out flat.

The caveat that bounds all of it: Makki and Madani are traditional attributions,
disputed at the margins, so a difference between the groups is a difference
between two *labelled sets*.

## Revelation-order trends

Spearman rank correlation, not Pearson: the Egyptian standard order is an
ordering, not a scale, and the gap between the 30th and 31st revealed surah is
not a quantity.

- Mean ayah length: ρ = **+0.583**, p < 1e-9 — rises strongly
- Lexical richness: ρ = −0.166, p = 0.11 — no reliable trend
- Rhyme concentration: ρ = +0.163, p = 0.12 — no reliable trend

## Prosody

The fasila is taken as the final two consonants of the last word. The commonest
endings are ون (1,756 verses), ين (1,323) and يم (649) — the known pattern.
Surah 114 scores a perfect 1.00; al-Mu'minūn holds its ون ending across 118
verses at 0.85.

This reads orthography as a proxy for sound. Qur'anic rhyme is a property of
recitation, and pausal forms change endings, so the measurement is one step
removed from the thing it is about.

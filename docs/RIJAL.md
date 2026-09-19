# Rijal and the transmission graph

The corpus has held 34,178 narrations with parsed chains since Track C and
analysed none of them. This is the largest gap between the tool and what a
hadith scholar does, and the place where computation has most to add: an isnad
corpus is a graph with tens of thousands of nodes, and questions that are
laborious by hand are graph queries.

```
qra rijal build      # project the hadith corpus into the graph
qra rijal            # sizes
```

Current projection: **20,615 names, 166,781 chain positions, 52,996 edges** from
33,966 usable chains.

## A node is a name, not a person

This is the load-bearing caveat and the reason most computational isnad studies
should be read sceptically. Names are obtained by segmenting chains on the
transmission particles, so two men called Sufyān are one node — and in this
corpus two men called Sufyān really are one node, al-Thawrī and Ibn ʿUyayna
both, with 2,530 narrations between them.

Rather than bury that, `/rijal/conflation` measures it.

**The metric is chain position, normalised.** Isnads are ordered by generation:
a Companion stands at the Prophet end, the collector at the far end, and one man
occupies a narrow band between them. A name found both beside a Companion and
beside a ninth-century collector is behaving like two men.

Two corrections were needed to make that number mean anything:

1. **Raw depth is confounded by chain length.** An isnad of four links and one
   of twenty put their collector at depth 3 and depth 19, so raw spread flagged
   every collector as conflated and measured nothing but chain length. Position
   is normalised per chain, 0.0 at the Prophet end and 1.0 at the collector.
2. **max − min saturates.** A name appearing 2,500 times lands at both extremes
   at least once, so every major transmitter scored 1.00 and the ranking was
   meaningless. The stored spread is the **interquartile range**.

With both fixes the median name spans 0.08 of the chain — as a single person
should — and the top of the suspect list is عبد الله, محمد, مسلم: the most
common names in the language.

### What this metric cannot see

**Same-generation homonyms.** The diagnostic is generational: it finds a name
appearing at chain positions no single lifetime spans. Two men of the *same*
generation sharing a name occupy the same positions and are invisible to it.

That blind spot includes the most famous case in the literature. سفيان is
al-Thawrī (d. 161 AH) and Ibn ʿUyayna (d. 198 AH), two major and distinct
transmitters, and its interquartile spread is **0.15** — comfortably inside the
range consistent with one man. The same goes for شعبة at 0.17.

Under the earlier max − min metric سفيان did head the suspect list, and an
earlier draft of this document cited it as the detector's textbook catch. That
was wrong: it ranked first because max − min saturates for any frequent name,
not because the metric had found anything. Replacing max − min with the
interquartile range was the right fix, and it cost this case.

So the report finds one kind of conflation and not the other. Names spanning
generations are caught; names shared within a generation need death dates, and
death dates need a rijal source.

## What is not computed

Gradings. Reliability is not a property of a man; it is something al-Bukhārī or
Ibn Ḥajar or al-Dhahabī said about him in a named work, and they disagree
constantly. `NarratorGrading` requires `critic` and `source_work`, both
non-nullable, and the table ships empty — the same discipline as the abrogation
registry.

A rebuild refuses to run while gradings are stored, rather than orphaning them.

## Common links, tested

Schacht and Juynboll argued that where the chains of a tradition converge on one
narrator, that is where the tradition enters the record. The argument is worth
exactly as much as the alternative it excludes, and the alternative that matters
is dull: a narrator appearing in thousands of chains will sit at the neck of a
small bundle for no reason at all.

`GET /hadith/{collection}/{number}/common-link` assembles the bundle with
takhrij, then resamples bundles of the same size and chain-length profile from
the whole corpus and asks how often a bottleneck this tight arises anyway.
The p-value uses add-one, so a finite resample never reports zero.

Two worked cases:

| Bundle | Common link | Coverage | Null mean | p | Verdict |
|---|---|---|---|---|---|
| Bukhari 1 (4 chains) | سفيان | 50% | 30.5% | 0.22 | **no weight** |
| Bukhari 35 (26 chains) | ابي سلمه | 38% | 13.9% | 0.0025 | beyond chance |

The first is the honest half. "Actions are by intentions" has a famous common
link, but a four-chain bundle around a prolific transmitter tells you nothing,
and the module says so instead of naming a founder.

The second recovers Abū Hurayra → Abū Salama → al-Zuhrī, with the two flanking
names reported as partial common links — a canonical transmission path, found
without being told to look for it.

## Known limits

- **Aliases split one man into two nodes.** الزهري and ابن شهاب are Ibn Shihāb
  al-Zuhrī; nothing here merges them. Conflation and aliasing are the same
  problem in opposite directions and both need biographical data.
- **16% of chains contain a kinship reference** (`عن أبيه`) that cannot be
  resolved without a rijal source. Those chains are **broken** at that point
  rather than bridged — bridging would assert a transmission the text does not
  contain.
- Nothing here dates anything. A bottleneck is a place to look.

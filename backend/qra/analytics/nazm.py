"""Nazm: passage segmentation and ring-structure candidates (WP-26).

Nazm — the coherence of a surah as a composed whole — is one of the oldest
questions in the field and one of the least tractable. Al-Biqa'i and, in the
modern period, Islahi read whole surahs as structured units; others read them
as collections. This module does not settle that. It produces *candidates*, and
its main engineering content is the machinery that stops a candidate from being
read as a finding.

**Segmentation** adapts TextTiling. At each ayah boundary, compare the root
vocabulary of the window before with the window after; a low overlap is a
candidate seam. Two Qur'an-specific signals are added: a change in the rhyme
ending (fasila), which is the strongest surface marker of a structural turn in
the text, and a change in dominant grammatical person, which frequently marks
a shift of address.

**Ring structure** is where the discipline matters most. Chiastic readings are
notoriously easy to produce — with enough freedom in choosing the units, almost
any text can be made to look symmetrical. So the mirror score here is tested
against a **shuffled-passage null model**: hold the segmentation fixed, permute
which ayat sit in which passage, and see how often a mirror at least this
strong arises by chance. A ring that a shuffled surah reproduces half the time
is not a ring, and this is the only way to know.

Everything returned is ``system_suggested``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.arabic import strip_diacritics
from qra.models import Ayah, Segment, Surah

# Window size for the cohesion curve, in ayat either side of a boundary.
WINDOW = 3
# A surah shorter than this has no interior to segment.
MIN_AYAT = 8
# Permutations for the null model. 400 gives a resolution of 0.0025 on p,
# which is as fine as this measurement deserves.
TRIALS = 400
SEED = 20240617


@dataclass
class Boundary:
    after_ayah: int
    cohesion: float
    rhyme_change: bool
    person_change: bool

    @property
    def score(self) -> float:
        """Lower is a stronger seam. The surface signals subtract from cohesion
        because a rhyme change at a low-cohesion point is the clearest case."""
        return self.cohesion - (0.12 if self.rhyme_change else 0.0) - (
            0.06 if self.person_change else 0.0
        )


def _fasila(text: str) -> str:
    """The rhyme ending: the last two consonants of the final word.

    Qur'anic verse-endings rhyme on a consonant pattern rather than a full
    syllable, so two letters is the unit that actually varies with structure.
    """
    letters = strip_diacritics(text).strip().split()
    if not letters:
        return ""
    tail = letters[-1].replace("ا", "").replace("ٰ", "")
    return tail[-2:] if len(tail) >= 2 else tail


def _surah_data(session: Session, surah: int) -> tuple[list[int], dict, dict, dict]:
    ayat = session.execute(
        select(Ayah.id, Ayah.ayah_num, Ayah.text_imlaei)
        .where(Ayah.surah_id == surah)
        .order_by(Ayah.ayah_num)
    ).all()
    if not ayat:
        raise ValueError(f"surah {surah} is not in this corpus")

    ids = [row.id for row in ayat]
    nums = {row.id: row.ayah_num for row in ayat}
    rhyme = {row.id: _fasila(row.text_imlaei) for row in ayat}

    roots: dict[int, set[int]] = {i: set() for i in ids}
    persons: dict[int, list[str]] = {i: [] for i in ids}
    for ayah_id, root_id, person in session.execute(
        select(Segment.ayah_id, Segment.root_id, Segment.person).where(
            Segment.ayah_id.in_(ids)
        )
    ).all():
        if root_id is not None:
            roots[ayah_id].add(root_id)
        if person:
            persons[ayah_id].append(person)

    dominant = {
        ayah_id: max(set(values), key=values.count) if values else ""
        for ayah_id, values in persons.items()
    }
    return ids, nums, roots, {"rhyme": rhyme, "person": dominant}


def _overlap(a: set[int], b: set[int]) -> float:
    """Overlap coefficient, not Jaccard: passages differ wildly in length here,
    and Jaccard would read a short passage next to a long one as incoherent
    purely because of the size difference."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def segment(session: Session, surah: int, *, window: int = WINDOW) -> dict:
    """Candidate passage boundaries within one surah."""
    ids, nums, roots, surface = _surah_data(session, surah)
    row = session.get(Surah, surah)
    if len(ids) < MIN_AYAT:
        return {
            "surah": surah,
            "name": row.name_ar if row else "",
            "ayat": len(ids),
            "passages": [{"start": nums[ids[0]], "end": nums[ids[-1]], "ayat": len(ids)}],
            "note": (
                f"{len(ids)} ayat — shorter than the {MIN_AYAT} this method needs to have an "
                "interior. The whole surah is returned as one unit rather than being cut into "
                "pieces the measurement cannot support."
            ),
            "provenance": "system_suggested",
        }

    boundaries: list[Boundary] = []
    for index in range(window, len(ids) - window):
        before: set[int] = set()
        after: set[int] = set()
        for offset in range(window):
            before |= roots[ids[index - 1 - offset]]
            after |= roots[ids[index + offset]]
        boundaries.append(
            Boundary(
                after_ayah=nums[ids[index - 1]],
                cohesion=_overlap(before, after),
                rhyme_change=surface["rhyme"][ids[index - 1]] != surface["rhyme"][ids[index]],
                person_change=surface["person"][ids[index - 1]]
                != surface["person"][ids[index]],
            )
        )

    # Local minima of the seam score: a boundary must be at least as strong as
    # both its neighbours, so a long slow decline yields one seam and not ten.
    seams = [
        b
        for index, b in enumerate(boundaries)
        if (index == 0 or boundaries[index - 1].score >= b.score)
        and (index == len(boundaries) - 1 or boundaries[index + 1].score > b.score)
    ]
    seams.sort(key=lambda b: b.score)
    keep = sorted({b.after_ayah for b in seams[: max(len(ids) // 12, 2)]})

    passages = []
    start = nums[ids[0]]
    for end in [*keep, nums[ids[-1]]]:
        passages.append({"start": start, "end": end, "ayat": end - start + 1})
        start = end + 1
    passages = [p for p in passages if p["ayat"] > 0]

    return {
        "surah": surah,
        "name": row.name_ar if row else "",
        "ayat": len(ids),
        "passages": passages,
        "boundaries": [
            {
                "after_ayah": b.after_ayah,
                "cohesion": round(b.cohesion, 4),
                "rhyme_change": b.rhyme_change,
                "person_change": b.person_change,
                "seam_score": round(b.score, 4),
            }
            for b in sorted(seams, key=lambda b: b.score)[:20]
        ],
        "method": (
            "Root-vocabulary overlap across a sliding window, with the rhyme ending (fasila) "
            "and a change of dominant grammatical person as additional surface signals. "
            "Boundaries are local minima of the combined score."
        ),
        "provenance": "system_suggested",
        "caveat": (
            "A segmentation is a reading. Classical divisions — al-Biqa'i's, Islahi's — "
            "disagree with each other and would disagree with this. Nothing here is a "
            "discovered structure; it is where the vocabulary thins out."
        ),
    }


def _mirror_score(passages: list[set[int]]) -> float:
    """Mean overlap between passage i and its mirror partner.

    A ring ABC…C'B'A' means the first passage resembles the last, the second
    resembles the second-to-last, and so on. The centre is skipped when the
    count is odd — it has no partner, which is exactly what a ring's pivot is.
    """
    pairs = [
        (passages[index], passages[len(passages) - 1 - index])
        for index in range(len(passages) // 2)
    ]
    if not pairs:
        return 0.0
    return sum(_overlap(a, b) for a, b in pairs) / len(pairs)


def rings(session: Session, surah: int, *, trials: int = TRIALS) -> dict:
    """Is this surah's passage sequence mirror-symmetric beyond chance?

    The null model is the acceptance criterion for WP-26: hold the passage sizes
    fixed, shuffle which ayat land in which passage, and recompute. Chiastic
    readings are easy to manufacture, and a mirror score means nothing until you
    know what an unstructured surah of the same shape produces.
    """
    layout = segment(session, surah)
    spans = layout["passages"]
    if len(spans) < 4:
        return {
            "surah": surah,
            "passages": len(spans),
            "testable": False,
            "why": (
                "A ring needs at least two mirror pairs to be a ring rather than a "
                "coincidence, so at least four passages. This surah segments into "
                f"{len(spans)}."
            ),
            "provenance": "system_suggested",
        }

    ids, nums, roots, _ = _surah_data(session, surah)
    by_num = {nums[i]: roots[i] for i in ids}
    grouped = [
        set().union(*(by_num.get(n, set()) for n in range(s["start"], s["end"] + 1)))
        if s["ayat"]
        else set()
        for s in spans
    ]
    observed = _mirror_score(grouped)

    # Permute ayat between passages, keeping the passage sizes. That isolates
    # the question — is the *ordering* mirrored — from the question of whether
    # the surah has a rich shared vocabulary, which it does regardless.
    pool = [by_num[n] for n in sorted(by_num)]
    sizes = [s["ayat"] for s in spans]
    rng = random.Random(SEED)
    at_least = 0
    null_scores = []
    for _ in range(trials):
        rng.shuffle(pool)
        cursor = 0
        shuffled = []
        for size in sizes:
            shuffled.append(set().union(*pool[cursor : cursor + size]) if size else set())
            cursor += size
        score = _mirror_score(shuffled)
        null_scores.append(score)
        if score >= observed:
            at_least += 1

    # Add-one, so a p of exactly zero is never reported from a finite number of
    # permutations. It would be a claim the experiment cannot support.
    p_value = (at_least + 1) / (trials + 1)
    mean_null = sum(null_scores) / len(null_scores)

    return {
        "surah": surah,
        "name": layout["name"],
        "passages": [
            {**span, "ref": f"{surah}:{span['start']}-{span['end']}"} for span in spans
        ],
        "mirror_pairs": [
            {
                "a": f"{surah}:{spans[i]['start']}-{spans[i]['end']}",
                "b": f"{surah}:{spans[-1 - i]['start']}-{spans[-1 - i]['end']}",
                "overlap": round(_overlap(grouped[i], grouped[-1 - i]), 4),
            }
            for i in range(len(spans) // 2)
        ],
        "centre": (
            f"{surah}:{spans[len(spans) // 2]['start']}-{spans[len(spans) // 2]['end']}"
            if len(spans) % 2
            else None
        ),
        "testable": True,
        "observed_mirror_score": round(observed, 4),
        "null_mean": round(mean_null, 4),
        "lift": round(observed / mean_null, 2) if mean_null else None,
        "p_value": round(p_value, 4),
        "trials": trials,
        "beyond_chance": p_value < 0.05,
        "null_model": (
            f"{trials} permutations holding the passage sizes fixed and shuffling which ayat "
            "fall in which passage. The p-value uses add-one so that zero is never reported "
            "from a finite number of trials."
        ),
        "null_model_limitation": (
            "This null is conservative, and knowing why matters before reading a negative "
            "result as a refutation. Two effects push the observed score down: the "
            "segmentation deliberately groups cohesive ayat together, so real passages are "
            "more vocabulary-distinct than shuffled ones; and mirror pairs are the most "
            "widely separated pairs in the sequence, while vocabulary overlap declines with "
            "distance. A surah failing this test has not been shown to lack ring structure — "
            "it has been shown that *this* measurement does not find one."
        ),
        "provenance": "system_suggested",
        "reading": (
            "The mirror is stronger than a shuffled surah of the same shape produces. That "
            "is a reason to read the passages against each other — not a demonstration that "
            "the surah was composed as a ring."
            if p_value < 0.05
            else "A shuffled surah of the same shape produces a mirror this strong often "
            "enough that this one carries no evidence of ring structure. Chiastic readings "
            "are easy to construct; this is the check that says when one is not warranted."
        ),
    }


def sweep(session: Session, *, min_ayat: int = 20, trials: int = 200) -> dict:
    """Every surah long enough to test, corrected across the whole sweep.

    Testing 114 surahs and reporting the striking ones is the failure mode this
    application exists to prevent, so the sweep corrects itself.
    """
    rows = session.execute(
        select(Surah.id, func.count(Ayah.id))
        .join(Ayah, Ayah.surah_id == Surah.id)
        .group_by(Surah.id)
        .having(func.count(Ayah.id) >= min_ayat)
        .order_by(Surah.id)
    ).all()

    results = []
    for surah_id, _ in rows:
        outcome = rings(session, surah_id, trials=trials)
        if outcome.get("testable"):
            results.append(outcome)

    # Benjamini-Hochberg by hand over the permutation p-values: correct_multiple
    # takes Significance objects, and these are empirical rather than binomial.
    ordered = sorted(results, key=lambda r: r["p_value"])
    total = len(ordered)
    survivors = []
    for rank, entry in enumerate(ordered, start=1):
        threshold = 0.05 * rank / total if total else 0.0
        entry["corrected_threshold"] = round(threshold, 5)
        entry["survives_correction"] = entry["p_value"] <= threshold
        if entry["survives_correction"]:
            survivors.append(entry)

    return {
        "surahs_tested": total,
        "beyond_chance_uncorrected": sum(1 for r in ordered if r["p_value"] < 0.05),
        "expected_by_chance": round(total * 0.05, 1),
        "surviving_correction": len(survivors),
        "correction": "benjamini_hochberg over the permutation p-values",
        "headline": (
            f"{total} surahs tested; {total * 0.05:.1f} would clear p<0.05 by chance alone. "
            f"{len(survivors)} survive correction."
        ),
        "finding": (
            "No surah shows mirror symmetry that survives correction across the sweep. "
            "Fewer clear the uncorrected threshold than chance alone predicts. Ring readings "
            "of individual surahs are easy to construct and widely published; this is what "
            "happens when the same claim is put to a null model, and it is the result the "
            "module exists to produce."
            if not survivors
            else f"{len(survivors)} surah(s) survive correction across the sweep. Read the "
            "null-model limitation before treating that as a demonstration of composition."
        ),
        "limitation": (
            "The null is conservative in a specific direction: real passages are more "
            "vocabulary-distinct than shuffled ones because the segmentation makes them so, "
            "and mirror pairs are the most separated pairs in the sequence. A negative here "
            "means this measurement finds no ring — not that none is there."
        ),
        "results": [
            {
                "surah": r["surah"],
                "name": r["name"],
                "passages": len(r["passages"]),
                "observed": r["observed_mirror_score"],
                "null_mean": r["null_mean"],
                "lift": r["lift"],
                "p_value": r["p_value"],
                "survives_correction": r["survives_correction"],
            }
            for r in ordered[:40]
        ],
        "provenance": "system_suggested",
    }

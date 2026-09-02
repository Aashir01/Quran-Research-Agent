"""Rhetorical features, detected where they are detectable (WP-27).

Balagha is mostly a matter of judgement, and a module that claimed to detect it
wholesale would be manufacturing findings. So this one restricts itself to
features with a *morphological signature* — things the annotators already
recorded, which can be found by rule rather than by taste — and says plainly
which is which.

**Iltifat** (اِلْتِفَات), the sudden shift of grammatical person mid-passage, is the
clearest case: person is a tagged feature on every verb and pronoun, so a shift
is arithmetic. It is also the feature classical rhetoricians discuss most, which
makes it the right one to do properly.

Everything detected here is a *candidate*, labelled ``system_suggested``. A
shift in person is a fact about the morphology; calling it iltifat is a reading,
and readings belong to the researcher.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.models import Ayah, Segment, Surah, Word


@dataclass
class Shift:
    ayah_id: int
    ref: str
    from_person: str
    to_person: str
    from_word: str
    to_word: str
    word_position: int

    def to_dict(self) -> dict:
        return {
            "ayah_id": self.ayah_id,
            "ref": self.ref,
            "shift": f"{self.from_person} → {self.to_person}",
            "from_person": self.from_person,
            "to_person": self.to_person,
            "from_word": self.from_word,
            "to_word": self.to_word,
            "word_position": self.word_position,
            # Never a finding. A person shift is a fact about the morphology;
            # calling it iltifat is a reading, and readings belong to the reader.
            "provenance": "system_suggested",
        }


def _word_heads(rows) -> list[tuple[int, str, str]]:
    """The governing person of each word: (position, person, surface).

    Comparing *segments* is what makes a naive detector useless here. An Arabic
    word carries its object as a suffix, so ``رَزَقْنَٰهُمْ`` is three segments —
    verb (1st), subject pronoun (1st), object pronoun (3rd) — and a
    segment-level scan reads that final suffix as a shift of voice. It is not;
    it is who the verb acts upon.

    The verb governs the word. Where there is no verb, the first person-bearing
    segment stands in.
    """
    by_word: dict[int, list] = {}
    for row in rows:
        by_word.setdefault(row.position, []).append(row)

    heads: list[tuple[int, str, str]] = []
    for position in sorted(by_word):
        segments = by_word[position]
        verb = next((sg for sg in segments if sg.pos_class == "V"), None)
        head = verb or segments[0]
        surface = "".join(sg.form or "" for sg in segments)
        heads.append((position, head.person, surface))
    return heads


def iltifat(
    session: Session,
    *,
    surah: int | None = None,
    revelation_place: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Shifts of grammatical person within a single ayah.

    Scoped to one ayah deliberately: across ayat a change of person is usually
    just a change of subject, while within one it is the marked construction the
    rhetoricians named.
    """
    stmt = (
        select(
            Segment.ayah_id,
            Segment.person,
            Segment.form,
            Segment.pos_class,
            Word.position,
            Segment.ayah_index,
            Ayah.surah_id,
            Ayah.ayah_num,
        )
        .join(Word, Word.id == Segment.word_id)
        .join(Ayah, Ayah.id == Segment.ayah_id)
        .where(Segment.person.is_not(None))
    )
    if surah:
        stmt = stmt.where(Ayah.surah_id == surah)
    if revelation_place:
        stmt = stmt.join(Surah, Surah.id == Ayah.surah_id).where(
            Surah.revelation_place == revelation_place
        )
    rows = session.execute(stmt.order_by(Segment.ayah_id, Segment.ayah_index)).all()

    by_ayah: dict[int, list] = {}
    refs: dict[int, str] = {}
    for row in rows:
        by_ayah.setdefault(row.ayah_id, []).append(row)
        refs[row.ayah_id] = f"{row.surah_id}:{row.ayah_num}"

    shifts: list[Shift] = []
    for ayah_id, segments in by_ayah.items():
        heads = _word_heads(segments)
        for (_, prev_person, prev_word), (position, person, word) in zip(
            heads, heads[1:], strict=False
        ):
            if person != prev_person:
                shifts.append(
                    Shift(
                        ayah_id=ayah_id,
                        ref=refs[ayah_id],
                        from_person=prev_person,
                        to_person=person,
                        from_word=prev_word,
                        to_word=word,
                        word_position=position,
                    )
                )

    affected = {s.ayah_id for s in shifts}
    total_ayat = session.scalar(select(func.count()).select_from(Ayah)) or 6236
    return {
        "feature": "iltifat",
        "arabic": "التفات",
        "gloss": "shift of grammatical person within a passage",
        "total_shifts": len(shifts),
        "ayat_affected": len(affected),
        "share_of_scope": round(len(affected) / total_ayat, 4) if not surah else None,
        "scope": {"surah": surah, "revelation_place": revelation_place},
        "exhaustive": True,
        "candidates": [s.to_dict() for s in shifts[offset : offset + limit]],
        "returned": len(shifts[offset : offset + limit]),
        "method": (
            "Person is tagged on every verb and pronoun, so a change of governing person "
            "between consecutive words of one ayah is arithmetic over the morphology. "
            "Comparison is per *word*, not per segment: an Arabic verb carries its object "
            "as a suffix, so رزقناهم is 1st person acting on a 3rd person, not a shift."
        ),
        "caveat": (
            "Classical iltifat is a shift of person *for the same referent*, and this "
            "detector has no coreference — it cannot tell a rhetorical turn from a genuine "
            "change of subject. Every row is a candidate to read, labelled system_suggested, "
            "never a detected figure of speech."
        ),
        "known_limitation": (
            "Detection is within a single ayah, so shifts *across* an ayah boundary are not "
            "reported — including the most-cited example in the Qur'an, the turn from third "
            "person in 1:4 to second person in 1:5. Widening the window would flood the "
            "results with ordinary changes of subject, so the boundary stays and the cost of "
            "it is stated here rather than hidden."
        ),
    }


def hotspots(session: Session, *, min_ayat: int = 10) -> dict:
    """Where person shifts are denser than the corpus baseline.

    A raw shift count is close to useless on its own: 55% of ayat contain at
    least one person change, so "this ayah has a shift" says almost nothing. The
    question worth asking is *where they cluster* — and that needs the same
    treatment as every other count in this app, which is a chance baseline and
    a correction across everything tested.

    This is what turns a superset of iltifat into an analytic: the surahs that
    come out beyond chance are the ones where the shifting is doing work.
    """
    from qra.analytics.stats import assess, correct_multiple

    per_ayah: dict[int, int] = {}
    rows = session.execute(
        select(Ayah.id, Ayah.surah_id).order_by(Ayah.id)
    ).all()
    surah_of = {ayah_id: surah for ayah_id, surah in rows}
    ayat_per_surah: dict[int, int] = {}
    for _, surah in rows:
        ayat_per_surah[surah] = ayat_per_surah.get(surah, 0) + 1

    # Recompute affected ayat per surah without paging through candidates.
    affected = _affected_ayat(session)
    for ayah_id in affected:
        surah = surah_of.get(ayah_id)
        if surah:
            per_ayah[surah] = per_ayah.get(surah, 0) + 1

    baseline = len(affected) / max(len(rows), 1)
    results = []
    labels = []
    for surah, total in sorted(ayat_per_surah.items()):
        if total < min_ayat:
            continue
        hits = per_ayah.get(surah, 0)
        results.append(assess(hits, total, baseline, label=f"surah {surah}"))
        labels.append(surah)
    correct_multiple(results)

    beyond = [
        {"surah": surah, **result.to_dict()}
        for surah, result in zip(labels, results, strict=True)
        if not result.within_chance
    ]
    return {
        "feature": "iltifat",
        "baseline_rate": round(baseline, 4),
        "baseline_note": (
            f"{len(affected):,} of {len(rows):,} ayat contain at least one person shift "
            f"({baseline * 100:.1f}%). That is the number any single ayah must be read "
            "against — on its own, 'this ayah shifts person' is close to no information."
        ),
        "surahs_tested": len(results),
        "beyond_chance": len(beyond),
        "correction": "benjamini_hochberg across every surah tested",
        "hotspots": sorted(beyond, key=lambda r: r["p_value"])[:20],
        "exhaustive": True,
        "caveat": (
            "Density beyond chance is a place to look, not a rhetorical finding. The "
            "detector has no coreference and cannot separate a rhetorical turn from a "
            "change of subject."
        ),
    }


def _affected_ayat(session: Session) -> set[int]:
    """Ayat containing at least one word-level person shift."""
    rows = session.execute(
        select(
            Segment.ayah_id,
            Segment.person,
            Segment.form,
            Segment.pos_class,
            Word.position,
            Segment.ayah_index,
        )
        .join(Word, Word.id == Segment.word_id)
        .where(Segment.person.is_not(None))
        .order_by(Segment.ayah_id, Segment.ayah_index)
    ).all()
    by_ayah: dict[int, list] = {}
    for row in rows:
        by_ayah.setdefault(row.ayah_id, []).append(row)
    affected = set()
    for ayah_id, segments in by_ayah.items():
        heads = _word_heads(segments)
        if any(a[1] != b[1] for a, b in zip(heads, heads[1:], strict=False)):
            affected.add(ayah_id)
    return affected


# Hand-verified fixtures (WP-27 acceptance). The negative cases are the ones
# that matter: each is an ayah a *segment*-level detector flags and a correct
# one does not, because an Arabic verb carries its object as a suffix. 76:2 is
# the clearest — "We created him ... We test him ... We made him" is first
# person throughout, with third-person objects attached to every verb.
FIXTURES = {
    "iltifat": {
        "positive": [
            {
                "ref": "2:3",
                "shifts": [("3", "1"), ("1", "3")],
                "why": (
                    "third-person description of the believers, a first-person aside "
                    "(مِمَّا رَزَقْنَٰهُمْ), then back — the textbook case"
                ),
            },
            {
                "ref": "1:5",
                "shifts": [("2", "1"), ("1", "2"), ("2", "1")],
                "why": (
                    "إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينُ — addressee and speaker alternating "
                    "within the ayah. Note what this fixture does *not* contain: the famous "
                    "al-Fatiha iltifat is the turn from third person in 1:4 to second person "
                    "in 1:5, which crosses an ayah boundary and is out of scope by design"
                ),
            },
        ],
        "negative": [
            {
                "ref": "76:2",
                "why": "first person throughout; every ه is an object, not a change of voice",
            },
            {
                "ref": "21:9",
                "why": "أَنجَيْنَٰهُمْ / أَهْلَكْنَا — first-person verbs with third-person objects",
            },
            {
                "ref": "3:30",
                "why": "third person throughout, with attached pronouns of both persons",
            },
        ],
    }
}


def check_fixtures(session: Session) -> dict:
    """Run the hand-verified fixtures and report what each one did.

    Kept in the module rather than only in the test file so a deployment can ask
    the running system whether its detector still behaves, without the test
    suite present.
    """
    report = []
    for ref, expected, why, kind in (
        [(f["ref"], f["shifts"], f["why"], "positive") for f in FIXTURES["iltifat"]["positive"]]
        + [(f["ref"], None, f["why"], "negative") for f in FIXTURES["iltifat"]["negative"]]
    ):
        surah, ayah = (int(part) for part in ref.split(":"))
        found = [
            (c["from_person"], c["to_person"])
            for c in iltifat(session, surah=surah, limit=100_000)["candidates"]
            if c["ref"] == ref
        ]
        passed = found == [tuple(pair) for pair in expected] if expected else not found
        report.append(
            {"ref": ref, "kind": kind, "why": why, "expected": expected, "found": found, "passed": passed}
        )
    return {
        "feature": "iltifat",
        "passed": sum(1 for r in report if r["passed"]),
        "total": len(report),
        "fixtures": report,
    }


def features(session: Session) -> dict:
    """What this module can and cannot detect, stated up front.

    The honest half of a rhetoric module is the list of things it is not
    attempting. Detecting taqdim by rule would mean claiming to know the
    unmarked word order of Qur'anic Arabic, which is exactly the sort of
    judgement this tool leaves to the researcher.
    """
    total_with_person = (
        session.scalar(
            select(func.count()).select_from(Segment).where(Segment.person.is_not(None))
        )
        or 0
    )
    return {
        "detectable": [
            {
                "feature": "iltifat",
                "arabic": "التفات",
                "basis": "person feature on verbs and pronouns",
                "segments_carrying_person": total_with_person,
                "endpoint": "/balagha/iltifat",
            }
        ],
        "not_detected": [
            {
                "feature": "taqdim / ta'khir",
                "arabic": "تقديم وتأخير",
                "why": (
                    "Marked word order can only be identified against an unmarked baseline, "
                    "and Qur'anic Arabic has no uncontested one. A rule would be encoding a "
                    "position, not detecting a feature."
                ),
            },
            {
                "feature": "hasr",
                "arabic": "حصر",
                "why": (
                    "Restriction constructions are recognisable, but distinguishing genuine "
                    "hasr from ordinary negation-plus-exception needs the semantics, not the "
                    "tags. The particles are findable with grammar search; the judgement is not."
                ),
            },
            {
                "feature": "qasam",
                "arabic": "قسم",
                "why": (
                    "The oath particles are tagged and findable via grammar search "
                    "(tag:P with the oath forms), but which oaths are rhetorically marked "
                    "is a reading."
                ),
            },
        ],
        "principle": (
            "Only features with a morphological signature are detected. Everything else is "
            "left to the researcher, with grammar search as the tool for finding candidates."
        ),
    }

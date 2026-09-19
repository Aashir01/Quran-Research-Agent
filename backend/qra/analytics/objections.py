"""Objection generation (Track E).

The agent's Critic checks whether a claim is *supported*. This asks a harder
question: what is the strongest case against it?

The distinction matters because the failure mode of a research tool is not
usually a claim with no evidence — it is a claim with real evidence and an
unexamined alternative. A root really does cluster with another root; the
alternative is that both are common. A narrator really does sit at the neck of
a bundle; the alternative is that he sits at the neck of everything. The
evidence is not wrong and the conclusion does not follow.

So every objection here is **computed, not written**. Each one names what would
have to be true for the claim to survive it, and carries the corpus evidence
that raised it. Nothing here is an LLM asking itself to be sceptical — that
produces objections shaped like objections. These produce numbers.

The objections implemented are the ones that have actually broken findings in
this codebase:

* **base rate** — the count is real and unremarkable.
* **general Arabic** — the pattern holds in the control corpus too.
* **polysemy** — the claim needs one sense of a root that carries several.
* **multiple comparisons** — this is the striking one of many tried.
* **length confound** — the measure being compared is a measure of length.
* **conflation** — the narrator is a name shared by several men.
* **counter-examples** — the universal claim has exceptions, and here they are.
* **small n** — the effect may be real; the sample cannot show it.

An objection that does not apply is not raised. A module that always returns
eight objections is one whose objections nobody reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.arabic import search_form
from qra.models import Ayah, Root, Segment

UNIVERSAL_MARKERS = (
    "always", "never", "every", "all ", "only", "none", "must ",
    "hamesha", "kabhi nahi", "ہمیشہ", "کبھی نہیں",
)
# Below this, a proportion is not distinguishable from noise whatever it looks
# like — the binomial interval on 20 trials spans most of the unit line.
SMALL_N = 30
# A root carrying this many distinct lemmas is doing more than one job.
POLYSEMY_LEMMAS = 3


@dataclass
class Objection:
    kind: str
    severity: str  # fatal | serious | worth_checking
    objection: str
    # What would have to be true for the claim to survive this.
    survives_if: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "objection": self.objection,
            "survives_if": self.survives_if,
            "evidence": self.evidence,
        }


def _base_rate(significance: dict | None) -> Objection | None:
    if not significance:
        return None
    observed = significance.get("observed")
    expected = significance.get("expected")
    if observed is None or expected is None:
        return None

    if significance.get("within_chance"):
        return Objection(
            "base_rate",
            "fatal",
            f"The count is {observed} where chance alone predicts {expected:.1f}. "
            "The number is real and it is unremarkable.",
            "nothing — a within-chance result does not become a finding by being "
            "restated. Either widen the evidence or drop the claim.",
            {"observed": observed, "expected": round(expected, 2), "p_value": significance.get("p_value")},
        )

    magnitude, label = _effect_magnitude(significance)
    if magnitude is not None and magnitude < 0.2:
        return Objection(
            "base_rate",
            "serious",
            f"The result clears significance but the effect is tiny ({label}). On a corpus "
            "this size, a difference too small to matter clears p<0.05 easily.",
            "the claim is about *whether* a difference exists rather than about its size. "
            "If it is about magnitude, this does not support it.",
            {
                "effect_size": significance.get("effect_size"),
                "effect_measure": significance.get("effect_measure"),
                "p_value": significance.get("p_value"),
            },
        )
    return None


_COHENS_H = re.compile(r"Cohen's h\s*=\s*(-?\d*\.?\d+)")


def _effect_magnitude(significance: dict) -> tuple[float | None, str]:
    """Effect size on a scale where 0 means "no effect".

    ``effect_size`` here is a **risk ratio**, whose null is 1.0, not 0.0.
    Comparing it against a Cohen's-h threshold called a ratio of 0.1 — a
    tenfold *reduction*, an enormous effect — negligible. Cohen's h is carried
    in ``effect_measure`` and is on the right scale, so it is preferred, with
    the ratio's distance from 1.0 as the fallback.
    """
    measure = significance.get("effect_measure") or ""
    match = _COHENS_H.search(measure)
    if match:
        value = abs(float(match.group(1)))
        return value, f"Cohen's h = {value:.3f}"
    ratio = significance.get("effect_size")
    if ratio is None:
        return None, ""
    return abs(float(ratio) - 1.0), f"risk ratio = {ratio:.3f}"


def _multiple_comparisons(significance: dict | None, tested: int | None) -> Objection | None:
    if not tested or tested < 2:
        return None
    corrected = (significance or {}).get("corrected_p")
    expected_false = tested * 0.05
    if corrected is None:
        return Objection(
            "multiple_comparisons",
            "serious",
            f"{tested} comparisons were made and this one is being reported. "
            f"About {expected_false:.1f} of them would clear p<0.05 with nothing behind them.",
            "the comparison was chosen before the counts were seen, or the family is "
            "corrected — which this result is not.",
            {"comparisons": tested, "expected_by_chance": round(expected_false, 2)},
        )
    if corrected > 0.05:
        return Objection(
            "multiple_comparisons",
            "fatal",
            f"Corrected across the {tested} comparisons made, this does not survive "
            f"(corrected p = {corrected:.4g}).",
            "nothing. The uncorrected p-value is not the result here.",
            {"comparisons": tested, "corrected_p": corrected},
        )
    return None


def _small_n(significance: dict | None) -> Objection | None:
    n = (significance or {}).get("n")
    if not n or n >= SMALL_N:
        return None
    return Objection(
        "small_n",
        "serious",
        f"The claim rests on {n} observations. An effect may well be there; a sample "
        "this size cannot distinguish it from noise.",
        "the effect is very large, or more of the corpus can be brought in. A small "
        "sample is a reason to withhold, not a reason to conclude the opposite.",
        {"n": n},
    )


def _polysemy(session: Session, root: str | None) -> Objection | None:
    """A claim resting on a root that carries several senses."""
    if not root:
        return None
    from qra.analytics.ijaz import semantic_load

    load = semantic_load(session, root)
    if not load.get("found"):
        return None
    senses = load.get("senses") or []
    total = load.get("total_segments") or 0
    if len(senses) < POLYSEMY_LEMMAS:
        return None

    dominant = senses[0]
    share = dominant["occurrences"] / total if total else 0
    return Objection(
        "polysemy",
        "serious" if share < 0.8 else "worth_checking",
        f"{load['root']} occurs {total} times across {len(senses)} distinct lemmas, and "
        f"the commonest ({dominant['lemma']}, {dominant['occurrences']}×) accounts for "
        f"{share:.0%} of them. A claim that needs one sense is choosing it over the others.",
        "the sense the claim depends on is the one attested in the cited verses — which "
        "has to be shown verse by verse, not assumed from the root.",
        {
            "root": load["root"],
            "total": total,
            "lemmas": [
                {"lemma": s["lemma"], "occurrences": s["occurrences"], "sample": s["sample_refs"][:3]}
                for s in senses[:5]
            ],
        },
    )


def _general_arabic(session: Session, roots: list[str] | None) -> Objection | None:
    """The single most common way a Qur'anic pattern turns out not to be one."""
    if not roots or len(roots) < 2:
        return None
    from qra.analytics.transfer import compare_pair

    result = compare_pair(session, roots[0], roots[1])
    if result.get("error"):
        return None
    if result.get("verdict") != "general_arabic":
        return None
    return Objection(
        "general_arabic",
        "fatal",
        "The same association holds in the hadith corpus — same language, same register, "
        "same period, different author. That points to a property of seventh-century "
        "Arabic rather than to anything distinctive about the Qur'an.",
        "the claim is about Arabic rather than about the Qur'an, or the contrast is in "
        "the *degree* rather than the presence, which the numbers below would have to show.",
        {
            "quran": result["quran"]["significance"],
            "background": result["background"]["significance"],
            "reading": result["reading"],
        },
    )


def _conflation(session: Session, narrator: str | None) -> Objection | None:
    if not narrator:
        return None
    from qra.models import Narrator

    row = session.scalar(select(Narrator).where(Narrator.display_name == narrator))
    if row is None or row.position_spread < 0.4:
        return None
    return Objection(
        "conflation",
        "fatal",
        f"'{narrator}' is a name, not a person. The middle half of its chain positions "
        f"span {row.position_spread:.2f} of the isnad, which is what several men sharing "
        "a spelling look like — a bottleneck at a conflated node is not a bottleneck.",
        "biographical data separates the men behind this name and the claim survives for "
        "one of them specifically.",
        {
            "narrator": narrator,
            "narrations": row.narration_count,
            "position_spread": row.position_spread,
            "position_range": [row.min_position, row.max_position],
        },
    )


def _length_confound(measure: str | None) -> Objection | None:
    """Measures that are secretly measures of length.

    Every one of these has produced a wrong comparison in this codebase.
    """
    suspect = {
        "type_token_ratio": "falls as text lengthens, so a long surah scores lower for being long",
        "ttr": "falls as text lengthens",
        "hapax_count": "rises with length; the rate does not",
        "distinct_words": "rises with length; compare vocabulary at matched token counts",
        "total_shifts": "rises with length; compare the rate per ayah",
        "rhyme_consistency": "share-of-commonest-ending falls as a surah lengthens",
        "entropy": "grows with sample size; corpora must be truncated to match",
    }
    if not measure:
        return None
    note = suspect.get(measure.strip().lower())
    if not note:
        return None
    return Objection(
        "length_confound",
        "fatal",
        f"'{measure}' is not length-independent — it {note}. A comparison on it between "
        "texts of different sizes measures size and reports it as style.",
        "the texts compared are of comparable length, or the measure is swapped for a "
        "length-robust one (Yule's K, a moving-average TTR, a rate rather than a count).",
        {"measure": measure, "why": note},
    )


def _counter_examples(session: Session, claim: str, root: str | None) -> Objection | None:
    """A universal claim, and the verses that break it."""
    lowered = (claim or "").lower()
    if not any(marker in lowered for marker in UNIVERSAL_MARKERS):
        return None
    if not root:
        return Objection(
            "universal_claim",
            "worth_checking",
            "The claim is stated universally ('always', 'never', 'every'). A universal "
            "claim over a closed corpus is decidable — it should be run as one rather "
            "than asserted.",
            "the exhaustive check returns no counter-example. Until it is run, this is "
            "an assertion about 6,236 verses.",
            {"markers": [m for m in UNIVERSAL_MARKERS if m in lowered]},
        )

    key = search_form(root)
    row = session.scalar(select(Root).where(Root.root == key))
    if row is None:
        return None
    # SELECT DISTINCT requires every ORDER BY expression in the select list, so
    # ayah.id has to be projected rather than only sorted on.
    ayat = session.execute(
        select(Ayah.id, Ayah.surah_id, Ayah.ayah_num)
        .join(Segment, Segment.ayah_id == Ayah.id)
        .where(Segment.root_id == row.id)
        .distinct()
        .order_by(Ayah.id)
        .limit(6)
    ).all()
    total = session.scalar(
        select(func.count(func.distinct(Segment.ayah_id))).where(Segment.root_id == row.id)
    )
    return Objection(
        "universal_claim",
        "serious",
        f"The claim is universal and {row.root_display} appears in {total} ayat. Every one "
        "of them is a place it could fail, and a universal claim over a closed corpus is "
        "decidable rather than arguable.",
        "the exhaustive run returns no counter-example. Start with the verses below.",
        {
            "root": row.root_display,
            "ayat_to_check": total,
            "first_refs": [f"{surah}:{ayah}" for _id, surah, ayah in ayat],
        },
    )


def objections(
    session: Session,
    *,
    claim: str = "",
    significance: dict | None = None,
    roots: list[str] | None = None,
    narrator: str | None = None,
    measure: str | None = None,
    comparisons_made: int | None = None,
) -> dict:
    """The strongest computable case against a claim.

    Every argument returned is raised by something in the corpus, and each one
    says what would have to be true for the claim to survive it. Objections that
    do not apply are not raised — a module that always returns eight is one
    whose objections stop being read.
    """
    primary_root = (roots or [None])[0]
    candidates = [
        _base_rate(significance),
        _multiple_comparisons(significance, comparisons_made),
        _small_n(significance),
        _polysemy(session, primary_root),
        _general_arabic(session, roots),
        _conflation(session, narrator),
        _length_confound(measure),
        _counter_examples(session, claim, primary_root),
    ]
    raised = [objection for objection in candidates if objection is not None]
    order = {"fatal": 0, "serious": 1, "worth_checking": 2}
    raised.sort(key=lambda o: order.get(o.severity, 9))

    fatal = [o for o in raised if o.severity == "fatal"]
    return {
        "claim": claim,
        "objections_raised": len(raised),
        "fatal": len(fatal),
        "verdict": (
            "a fatal objection stands — the claim does not survive as stated"
            if fatal
            else "no fatal objection found by these checks"
            if raised
            else "none of these checks applies to this claim"
        ),
        "objections": [o.to_dict() for o in raised],
        "checks_run": [
            "base rate", "multiple comparisons", "sample size", "polysemy",
            "general Arabic (hadith control)", "narrator conflation",
            "length confound", "universal-claim counter-examples",
        ],
        "scope": (
            "These are the objections this corpus can raise by computation. They are not "
            "the only objections — a reading can be wrong for reasons no count reaches, "
            "and silence here is not endorsement."
        ),
        "provenance": "system_suggested",
    }

"""Scope estimation (Track E).

What a researcher needs before a long run is not a progress bar — it is an
answer to "is this question the kind of thing this corpus can settle, and what
will it cost to find out?"

Three things get estimated, all deterministically, all before any provider is
called:

**Size.** Which corpus terms the question turns on, how many ayat they reach,
and therefore whether the evidence base is a hundred verses or four.

**Answerability.** A question over a closed corpus is one of three kinds.
*Decidable* — it is a count or a universal claim, and the corpus settles it
exhaustively. *Comparative* — it needs a baseline, which exists. *Interpretive*
— it turns on what a word means or what a passage is doing, and no amount of
retrieval closes it. Saying which kind a question is, before running it, is
worth more than most of what a run produces: the commonest disappointment with
a tool like this is asking it an interpretive question and receiving counts.

**Cost.** Spans, estimated seconds, and whether a model provider is needed at
all — many questions here are answered by SQL and would run with every provider
unreachable.

Nothing here runs the research. An estimate that costs as much as the answer is
not an estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.models import Ayah, Concept, ConceptRoot, Root, Segment

# Question shapes, in the order they are tested. Order matters: "how many verses
# say X always happens" is a universal claim first and a count second.
UNIVERSAL = ("always", "never", "every", "all ", "only", "none ", "hamesha", "ہمیشہ")
COUNTING = ("how many", "how often", "count", "number of", "kitne", "کتنے")
COMPARATIVE = (
    "more than", "less than", "compare", "versus", " vs ", "differ",
    "makki", "madani", "before", "after", "correlat", "relationship between",
)
INTERPRETIVE = (
    "why", "what does it mean", "meaning of", "significance", "wisdom",
    "purpose", "implies", "suggests", "kyun", "kya matlab", "مطلب",
)

# Rough, measured against this corpus on this machine. Deliberately coarse:
# a precise estimate would be a promise, and the point is an order of magnitude.
SECONDS_PER_TERM = 0.4
SECONDS_PER_PROVIDER_CALL = 3.0


@dataclass
class Term:
    label: str
    kind: str  # concept | root
    ayat: int
    occurrences: int


def _resolve_terms(session: Session, question: str) -> list[Term]:
    """Concepts and roots the question actually names.

    Matching is on the concept slug and English label rather than on anything
    fuzzy: a term this cannot find is reported as not found, which is more
    useful than a term it guesses at.
    """
    lowered = (question or "").lower()
    found: list[Term] = []
    seen: set[str] = set()

    for concept in session.scalars(select(Concept)).all():
        label = (concept.label_en or "").lower()
        if not label or label in seen:
            continue
        # Several labels carry alternatives — "Patience / steadfastness",
        # "Truth / right" — and requiring the whole string meant a question
        # saying "patience" matched nothing.
        parts = [part.strip() for part in label.split("/") if len(part.strip()) > 3]
        if concept.slug in lowered or any(part in lowered for part in parts):
            root_ids = session.scalars(
                select(ConceptRoot.root_id).where(ConceptRoot.concept_id == concept.id)
            ).all()
            if not root_ids:
                continue
            occurrences = (
                session.scalar(
                    select(func.count())
                    .select_from(Segment)
                    .where(Segment.root_id.in_(root_ids))
                )
                or 0
            )
            ayat = (
                session.scalar(
                    select(func.count(func.distinct(Segment.ayah_id))).where(
                        Segment.root_id.in_(root_ids)
                    )
                )
                or 0
            )
            seen.add(label)
            found.append(Term(concept.label_en, "concept", ayat, occurrences))

    # Arabic roots typed directly into the question.
    for token in (question or "").split():
        if not any("؀" <= ch <= "ۿ" for ch in token):
            continue
        from qra.arabic import search_form

        row = session.scalar(select(Root).where(Root.root == search_form(token)))
        if row is None or row.root_display in seen:
            continue
        seen.add(row.root_display)
        ayat = (
            session.scalar(
                select(func.count(func.distinct(Segment.ayah_id))).where(
                    Segment.root_id == row.id
                )
            )
            or 0
        )
        found.append(Term(row.root_display, "root", ayat, row.occurrence_count))

    return found


def _shape(question: str) -> tuple[str, str]:
    lowered = (question or "").lower()
    if any(marker in lowered for marker in UNIVERSAL):
        return (
            "decidable",
            "A universal claim over a closed corpus. The corpus settles it outright — "
            "one counter-example is enough, and an exhaustive run either finds one or "
            "does not.",
        )
    if any(marker in lowered for marker in COUNTING):
        return (
            "decidable",
            "A counting question. The answer is exact and exhaustive, though a count "
            "still needs a baseline before it means anything.",
        )
    if any(marker in lowered for marker in COMPARATIVE):
        return (
            "comparative",
            "A comparison. Answerable, but only against an explicit null model — "
            "the answer is a difference and an effect size, not a number.",
        )
    if any(marker in lowered for marker in INTERPRETIVE):
        return (
            "interpretive",
            "An interpretive question. Retrieval can assemble every verse, every "
            "classical comment and every structural fact bearing on it, and it cannot "
            "close it. What comes back is material for a judgement, not the judgement.",
        )
    return (
        "underdetermined",
        "The shape of this question is unclear from its wording. It will be run as a "
        "retrieval, which may be the wrong thing — consider stating it as a count, a "
        "comparison, or a claim to be refuted.",
    )


def estimate(session: Session, question: str) -> dict:
    """What this question will cost and what kind of answer it can have."""
    terms = _resolve_terms(session, question)
    shape, shape_note = _shape(question)

    total_ayat = session.scalar(select(func.count()).select_from(Ayah)) or 6236
    reach = max((t.ayat for t in terms), default=0)
    spans = sum(min(t.ayat, 50) for t in terms) + (10 if terms else 0)

    # Providers are needed to *draft*, never to retrieve. A question that only
    # counts is answerable with every provider unreachable.
    needs_provider = shape in {"interpretive", "underdetermined"} or len(terms) > 1
    seconds = len(terms) * SECONDS_PER_TERM + (
        SECONDS_PER_PROVIDER_CALL * 3 if needs_provider else 0
    )

    if not terms:
        evidence = "none — no corpus term in this question was recognised"
    elif reach < 10:
        evidence = f"thin — the widest term reaches {reach} ayat"
    elif reach < 100:
        evidence = f"moderate — the widest term reaches {reach} ayat"
    else:
        evidence = f"broad — the widest term reaches {reach} ayat ({reach / total_ayat:.0%} of the corpus)"

    warnings = []
    if not terms:
        warnings.append(
            "No concept or root in this question was recognised. The run will retrieve "
            "on the question's words, which is the weakest path this system has — name "
            "a root or a concept slug and it becomes exhaustive."
        )
    if reach and reach < 10:
        warnings.append(
            f"The evidence base is {reach} ayat. That is enough to describe and not "
            "enough to establish anything statistically; expect the Critic to refuse "
            "any comparative claim built on it."
        )
    if shape == "interpretive":
        warnings.append(
            "Retrieval cannot close an interpretive question. The run will return "
            "material, and the judgement remains the researcher's."
        )
    if len(terms) > 4:
        warnings.append(
            f"{len(terms)} terms were recognised. Multi-term questions fan out into "
            "many comparisons, and every comparison made has to be counted against "
            "whichever one comes out striking."
        )

    return {
        "question": question,
        "shape": shape,
        "shape_note": shape_note,
        "terms": [
            {"label": t.label, "kind": t.kind, "ayat": t.ayat, "occurrences": t.occurrences}
            for t in terms
        ],
        "terms_found": len(terms),
        "evidence_base": evidence,
        "widest_term_reaches_ayat": reach,
        "estimated_spans": spans,
        "estimated_seconds": round(seconds, 1),
        "needs_a_model_provider": needs_provider,
        "provider_note": (
            "Providers draft; they never retrieve. With every provider unreachable this "
            "question still returns its counts, citations and statistics — the draft is "
            "what is lost."
        ),
        "warnings": warnings,
        "estimate_only": (
            "Nothing was run to produce this. An estimate that costs as much as the "
            "answer is not an estimate."
        ),
    }

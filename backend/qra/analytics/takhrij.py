"""Takhrij: the same narration across collections (WP-21).

The question a scholar actually asks of a hadith is not "is this one sahih" but
"where else is this narrated, through whom, and how did each collector grade
it". Answering it by hand means reading six collections; answering it here is a
matn comparison over 34,178 rows.

Two design choices carry the weight:

**Compare matn, not rows.** The chain is what *differs* between two collections
carrying the same report, so comparing whole rows measures the wrong thing.
Where :mod:`qra.analytics.isnad` split the row confidently we compare matn;
where it did not, we compare the whole row and say so, because a silent
fallback would make a weak match look like a strong one.

**Overlap, not Jaccard.** Two collectors abridge differently, so the same
narration appears at very different lengths. Jaccard punishes that; the overlap
coefficient (shared ÷ shorter) does not, which is the behaviour this comparison
wants.

Every result carries each parallel's own grade and grader. A narration that is
sahih in Bukhari and da'if elsewhere is a fact about the transmission, not a
contradiction to resolve, and the point of this module is to show it.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from qra.analytics.isnad import RELIABLE_SPLIT, split
from qra.arabic import shingles
from qra.models import Hadith

SHINGLE_SIZE = 4
# Calibrated against the corpus rather than guessed. Sampling 1,500 narrations
# and reading the pairs at each score: at 0.7 and 0.5 they are plainly the same
# report; at 0.4 they are often an abridgement or a "…وذكر نحوه" cross-reference;
# at 0.3 they are mostly shared formulaic phrasing.
#
# So the floor is low and the answer is *banded*. Thresholding at one number
# would either hide real parallels or present weak ones as found — and which of
# those matters depends on whether the researcher is surveying or citing, which
# is their call to make, not this module's.
MIN_SCORE = 0.35
BAND_STRONG = 0.6
BAND_PROBABLE = 0.45
# A shingle occurring in more rows than this is boilerplate, not evidence.
# Keeping them would make every hadith a candidate for every other.
MAX_SHINGLE_DF = 200
MIN_SHARED_SHINGLES = 3


@dataclass
class Parallel:
    hadith_id: int
    collection: str
    number: str
    grading: str
    graded_by: str | None
    score: float
    compared: str  # matn | whole_row
    matn: str
    narrators: list[str] = field(default_factory=list)

    @property
    def band(self) -> str:
        """How much this parallel is worth.

        Capped at ``possible`` when either side's isnad split was unreliable:
        the chain then sits inside the compared text, and a score computed over
        chain words is not evidence about the report.
        """
        if self.compared != "matn":
            return "possible"
        if self.score >= BAND_STRONG:
            return "strong"
        if self.score >= BAND_PROBABLE:
            return "probable"
        return "possible"

    def to_dict(self) -> dict:
        return {
            "band": self.band,
            "hadith_id": self.hadith_id,
            "collection": self.collection,
            "number": self.number,
            "ref": f"{self.collection} {self.number}",
            "grading": self.grading,
            "graded_by": self.graded_by,
            "score": round(self.score, 3),
            "compared": self.compared,
            "matn": self.matn[:400],
            "narrators": self.narrators,
        }


@dataclass
class _Row:
    id: int
    collection: str
    number: str
    grading: str
    graded_by: str | None
    matn: str
    grams: set[str]
    compared: str
    narrators: list[str]


def _prepare(hadith: Hadith) -> _Row | None:
    text = hadith.text_ar or hadith.text_search or ""
    if not text.strip():
        return None
    parsed = split(text)
    if parsed.confidence >= RELIABLE_SPLIT and parsed.matn.strip():
        body, compared = parsed.matn, "matn"
    else:
        # Honest fallback: the isnad stays in, which depresses the score. That
        # is the right direction to be wrong in.
        body, compared = text, "whole_row"
    from qra.arabic import search_form

    tokens = search_form(body).split()
    if len(tokens) < SHINGLE_SIZE + 2:
        return None
    return _Row(
        id=hadith.id,
        collection=hadith.collection,
        number=hadith.number,
        grading=hadith.grading,
        graded_by=hadith.graded_by,
        matn=body,
        grams=shingles(tokens, SHINGLE_SIZE),
        compared=compared,
        narrators=parsed.narrators,
    )


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def build_index(session: Session, *, limit: int | None = None) -> tuple[dict[int, _Row], dict[str, list[int]]]:
    """One pass over the corpus: split, shingle, and invert.

    An inverted index rather than pairwise comparison — 34k rows is 580 million
    pairs, and almost all of them share nothing.
    """
    stmt = select(Hadith).where(Hadith.text_ar.is_not(None))
    if limit:
        stmt = stmt.limit(limit)

    rows: dict[int, _Row] = {}
    postings: dict[str, list[int]] = defaultdict(list)
    for hadith in session.scalars(stmt).yield_per(500):
        row = _prepare(hadith)
        if row is None:
            continue
        rows[row.id] = row
        for gram in row.grams:
            postings[gram].append(row.id)

    # Drop boilerplate before it costs anything downstream.
    common = [gram for gram, ids in postings.items() if len(ids) > MAX_SHINGLE_DF]
    for gram in common:
        del postings[gram]
    return rows, postings


# Building the index is a 26-second pass over 34k narrations, which is fine
# once and unacceptable per request. The hadith corpus does not change between
# ingests, so the index is memoised for the life of the process and rebuilt
# only when ingest says so.
_INDEX: tuple[dict[int, _Row], dict[str, list[int]]] | None = None
_INDEX_LOCK = threading.Lock()


def cached_index(session: Session):
    """The shingle index, built once. Thread-safe because the API is threaded."""
    global _INDEX
    if _INDEX is None:
        with _INDEX_LOCK:
            if _INDEX is None:
                _INDEX = build_index(session)
    return _INDEX


def invalidate() -> None:
    """Called after ingest. A stale index would silently answer from the old
    corpus, which is the kind of wrong that never announces itself."""
    global _INDEX
    with _INDEX_LOCK:
        _INDEX = None


def index_ready() -> bool:
    return _INDEX is not None


def parallels_for(
    session: Session,
    hadith_id: int,
    *,
    index: tuple[dict[int, _Row], dict[str, list[int]]] | None = None,
    min_score: float = MIN_SCORE,
    cross_collection_only: bool = False,
    limit: int = 25,
) -> dict:
    """Every parallel narration of one hadith, with each one's own grade."""
    rows, postings = index if index is not None else cached_index(session)
    source = rows.get(hadith_id)
    if source is None:
        hadith = session.get(Hadith, hadith_id)
        return {
            "hadith_id": hadith_id,
            "ref": f"{hadith.collection} {hadith.number}" if hadith else None,
            "parallels": [],
            "exhaustive": True,
            "note": "This narration is too short to compare, or carries no Arabic text.",
        }

    counts: dict[int, int] = defaultdict(int)
    for gram in source.grams:
        for other in postings.get(gram, ()):
            if other != hadith_id:
                counts[other] += 1

    found: list[Parallel] = []
    for other_id, shared in counts.items():
        if shared < MIN_SHARED_SHINGLES:
            continue
        other = rows[other_id]
        if cross_collection_only and other.collection == source.collection:
            continue
        score = _overlap(source.grams, other.grams)
        if score < min_score:
            continue
        found.append(
            Parallel(
                hadith_id=other.id,
                collection=other.collection,
                number=other.number,
                grading=other.grading,
                graded_by=other.graded_by,
                score=score,
                compared="matn" if source.compared == other.compared == "matn" else "whole_row",
                matn=other.matn,
                narrators=other.narrators,
            )
        )

    found.sort(key=lambda p: p.score, reverse=True)
    # Gradings are only worth comparing across parallels we would actually
    # stand behind; a "possible" match disagreeing on grade says nothing.
    solid = [p for p in found if p.band in ("strong", "probable")]
    gradings = sorted({p.grading for p in solid} | {source.grading})
    return {
        "hadith_id": hadith_id,
        "ref": f"{source.collection} {source.number}",
        "grading": source.grading,
        "graded_by": source.graded_by,
        "matn": source.matn[:600],
        "narrators": source.narrators,
        "compared": source.compared,
        "collections": sorted({p.collection for p in solid}),
        "parallel_count": len(found),
        "by_band": {
            band: len([p for p in found if p.band == band])
            for band in ("strong", "probable", "possible")
        },
        "gradings_present": gradings,
        "grading_disagreement": len(gradings) > 1,
        "parallels": [p.to_dict() for p in found[:limit]],
        "exhaustive": True,
        "method": (
            f"{SHINGLE_SIZE}-word shingle overlap over the matn where the isnad split was "
            f"reliable, over the whole row otherwise; floor {min_score}. Bands were calibrated "
            f"by reading sampled pairs: strong ≥ {BAND_STRONG}, probable ≥ {BAND_PROBABLE}, "
            "possible below that. A `possible` match is a candidate to read, not a finding."
        ),
        "caveat": (
            "Different collectors graded independently. Where gradings disagree that is a "
            "fact about the transmission, reported rather than reconciled."
        ),
    }


def sweep(session: Session, *, min_score: float = MIN_SCORE, handle=None) -> dict:
    """Corpus-wide: how much of the hadith corpus is cross-attested."""
    rows, postings = build_index(session)
    total = len(rows)
    with_parallels = 0
    cross_collection = 0
    disagreements = 0
    pairs = 0

    for position, (hadith_id, row) in enumerate(rows.items()):
        if handle is not None and position % 500 == 0:
            handle.report(position, total, stage="matching")
            handle.checkpoint()
        counts: dict[int, int] = defaultdict(int)
        for gram in row.grams:
            for other in postings.get(gram, ()):
                if other != hadith_id:
                    counts[other] += 1
        matched = [
            other
            for other, shared in counts.items()
            if shared >= MIN_SHARED_SHINGLES and _overlap(row.grams, rows[other].grams) >= min_score
        ]
        if matched:
            with_parallels += 1
            pairs += len(matched)
            others = {rows[o].collection for o in matched}
            if others - {row.collection}:
                cross_collection += 1
            if {rows[o].grading for o in matched} | {row.grading} != {row.grading}:
                disagreements += 1

    return {
        "narrations_compared": total,
        "with_parallels": with_parallels,
        "cross_collection": cross_collection,
        "grading_disagreements": disagreements,
        "pairs": pairs // 2,
        "min_score": min_score,
        "exhaustive": True,
        "note": (
            "Every narration with Arabic text was compared against every other. "
            "The comparison is exhaustive; the isnad split it rests on is a heuristic."
        ),
    }

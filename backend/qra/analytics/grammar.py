"""Grammar search over the morphology (WP-19).

The corpus carries 130,030 analysed segments, and until now the only way to
query them was one ayah at a time. This module turns them into a searchable
structure, so questions that are a day's work by hand — *every imperative verb
governing a preposition in Makki surahs*, *every conditional particle followed
by a perfect verb* — become one query.

Exhaustive, like the other deterministic modes: the answer is every match in
the corpus, not a ranked sample. What it inherits from the QAC is the
annotators' judgement, so a query is only ever as right as their tagging, and
the result says which tags it matched on.

## The language

A query is a sequence of segment patterns with an optional scope::

    V:IMPV P                      an imperative verb, then a preposition
    tag:COND > V:PERF @makki      a conditional particle, later a perfect verb
    root:صبر+V:IMPF               imperfect verbs from the root ص-ب-ر
    N:INDEF:F                     indefinite feminine nouns

* ``POS`` — ``N`` noun, ``V`` verb, ``P`` particle. Bare, or with features
  after colons in any order: ``V:PERF:PASS:3:M:P``.
* ``key:value`` — ``root:``, ``lemma:``, ``tag:``, ``form:``.
* ``+`` joins constraints on one segment: ``V:IMPF+root:علم``.
* A space between patterns means **immediately adjacent**; ``>`` means
  **anywhere later in the same ayah**.
* ``@makki``, ``@madani``, ``@surah:N``, ``@juz:N`` restrict the scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from qra.arabic import search_form
from qra.models import Ayah, Root, Segment, Surah

# Feature vocabularies, so a typo is a clear error rather than an empty result.
POS_CLASSES = {"N", "V", "P"}
FEATURES: dict[str, set[str]] = {
    "aspect": {"PERF", "IMPF", "IMPV"},
    "voice": {"ACT", "PASS"},
    "mood": {"IND", "SUBJ", "JUS"},
    "state": {"DEF", "INDEF"},
    "gender": {"M", "F"},
    "number": {"S", "D", "P"},
    "person": {"1", "2", "3"},
    "derivation": {"ACT_PCPL", "PASS_PCPL", "VN", "ADJ", "SUP"},
}
# `P` is both a part of speech and a number value, so the pos slot wins and a
# number is only read from the remaining features.
_AMBIGUOUS = {"P"}

TOKEN_KEYS = {"root", "lemma", "tag", "form"}
SCOPE_RE = re.compile(r"@(\w+)(?::([\w؀-ۿ]+))?")


class QueryError(ValueError):
    """A query that cannot be compiled. Carries what to fix."""


@dataclass
class Pattern:
    """Constraints on one segment."""

    pos: str | None = None
    features: dict[str, str] = field(default_factory=dict)
    root: str | None = None
    lemma: str | None = None
    tag: str | None = None
    form: str | None = None
    # How this pattern relates to the one before it.
    adjacent: bool = True

    def describe(self) -> str:
        bits = [self.pos or "any"]
        bits += [f"{k}={v}" for k, v in sorted(self.features.items())]
        for key in ("root", "lemma", "tag", "form"):
            value = getattr(self, key)
            if value:
                bits.append(f"{key}:{value}")
        return " ".join(bits)


@dataclass
class Scope:
    revelation_place: str | None = None
    surahs: list[int] = field(default_factory=list)
    juz: list[int] = field(default_factory=list)

    def describe(self) -> str:
        bits = []
        if self.revelation_place:
            bits.append(self.revelation_place)
        if self.surahs:
            bits.append(f"surah {', '.join(map(str, self.surahs))}")
        if self.juz:
            bits.append(f"juz {', '.join(map(str, self.juz))}")
        return ", ".join(bits) or "whole corpus"


@dataclass
class Query:
    patterns: list[Pattern]
    scope: Scope
    source: str

    def describe(self) -> str:
        parts = []
        for index, pattern in enumerate(self.patterns):
            if index:
                parts.append("immediately followed by" if pattern.adjacent else "later followed by")
            parts.append(f"[{pattern.describe()}]")
        return " ".join(parts) + f" — in {self.scope.describe()}"


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def parse(query: str) -> Query:
    if not query or not query.strip():
        raise QueryError("empty query")

    scope = Scope()
    for match in SCOPE_RE.finditer(query):
        key, value = match.group(1), match.group(2)
        if key in ("makki", "madani"):
            scope.revelation_place = key
        elif key == "surah" and value:
            scope.surahs.append(int(value))
        elif key == "juz" and value:
            scope.juz.append(int(value))
        else:
            raise QueryError(
                f"unknown scope '@{key}'. Use @makki, @madani, @surah:N or @juz:N."
            )
    body = SCOPE_RE.sub(" ", query).strip()
    if not body:
        raise QueryError("a query needs at least one segment pattern, not only a scope")

    patterns: list[Pattern] = []
    adjacent = True
    for token in body.split():
        if token == ">":
            adjacent = False
            continue
        patterns.append(_parse_token(token, adjacent))
        adjacent = True

    if not patterns:
        raise QueryError("no segment patterns found")
    return Query(patterns=patterns, scope=scope, source=query.strip())


def _parse_token(token: str, adjacent: bool) -> Pattern:
    pattern = Pattern(adjacent=adjacent)
    for part in token.split("+"):
        if not part:
            continue
        if ":" in part and part.split(":", 1)[0] in TOKEN_KEYS:
            key, value = part.split(":", 1)
            if not value:
                raise QueryError(f"'{key}:' needs a value")
            setattr(pattern, key, value)
            continue

        bits = part.split(":")
        head = bits[0].upper()
        if head in POS_CLASSES:
            pattern.pos = head
            rest = bits[1:]
        elif head == "*":
            rest = bits[1:]
        else:
            rest = bits
        for raw in rest:
            value = raw.upper()
            slot = next(
                (name for name, vocab in FEATURES.items() if value in vocab and value not in _AMBIGUOUS),
                None,
            )
            if slot is None and value in _AMBIGUOUS:
                slot = "number"
            if slot is None:
                known = ", ".join(sorted(v for vocab in FEATURES.values() for v in vocab))
                raise QueryError(
                    f"unknown feature '{raw}' in '{token}'. Known features: {known}. "
                    "For a root, lemma, tag or surface form use root:… lemma:… tag:… form:…"
                )
            pattern.features[slot] = value
    if not any(
        [pattern.pos, pattern.features, pattern.root, pattern.lemma, pattern.tag, pattern.form]
    ):
        raise QueryError(f"'{token}' constrains nothing")
    return pattern


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------

_COLUMN = {
    "aspect": Segment.aspect,
    "voice": Segment.voice,
    "mood": Segment.mood,
    "state": Segment.state,
    "gender": Segment.gender,
    "number": Segment.number,
    "person": Segment.person,
    "derivation": Segment.derivation,
}


def _indexed():
    """Segments keyed for sequence matching.

    ``Segment.ayah_index`` is materialised at ingest precisely so this is a
    plain indexed table rather than a window function evaluated once per alias
    in the join — which is what made a two-pattern query take 92 seconds.
    """
    return Segment.__table__


def _conditions(alias, pattern: Pattern, session: Session):
    clauses = []
    if pattern.pos:
        clauses.append(alias.c.pos_class == pattern.pos)
    for slot, value in pattern.features.items():
        clauses.append(getattr(alias.c, slot) == value)
    if pattern.tag:
        clauses.append(alias.c.tag == pattern.tag.upper())
    if pattern.form:
        clauses.append(alias.c.form_search == search_form(pattern.form))
    if pattern.root:
        root_id = session.scalar(
            select(Root.id).where(Root.root == search_form(pattern.root))
        )
        if root_id is None:
            raise QueryError(
                f"root '{pattern.root}' is not in the corpus. There are 1,651 roots; "
                "check the spelling, or search it on the Search page first."
            )
        clauses.append(alias.c.root_id == root_id)
    if pattern.lemma:
        from qra.models import Lemma

        lemma_id = session.scalar(
            select(Lemma.id).where(Lemma.lemma == search_form(pattern.lemma))
        )
        if lemma_id is None:
            raise QueryError(f"lemma '{pattern.lemma}' is not in the corpus")
        clauses.append(alias.c.lemma_id == lemma_id)
    return clauses


def run(session: Session, query: str, *, limit: int = 50, offset: int = 0) -> dict:
    """Execute a grammar query. Exhaustive: the count is every match."""
    parsed = parse(query)
    seg = _indexed()
    first = seg.alias("s0")

    stmt = select(first.c.ayah_id, first.c.ayah_index.label("anchor")).where(
        *_conditions(first, parsed.patterns[0], session)
    )

    previous = first
    for index, pattern in enumerate(parsed.patterns[1:], start=1):
        nxt = seg.alias(f"s{index}")
        link = (
            nxt.c.ayah_index == previous.c.ayah_index + 1
            if pattern.adjacent
            else nxt.c.ayah_index > previous.c.ayah_index
        )
        stmt = stmt.join(
            nxt,
            and_(nxt.c.ayah_id == previous.c.ayah_id, link, *_conditions(nxt, pattern, session)),
        )
        previous = nxt

    if parsed.scope.revelation_place or parsed.scope.surahs or parsed.scope.juz:
        stmt = stmt.join(Ayah, Ayah.id == first.c.ayah_id)
        if parsed.scope.revelation_place:
            stmt = stmt.join(Surah, Surah.id == Ayah.surah_id).where(
                Surah.revelation_place == parsed.scope.revelation_place
            )
        if parsed.scope.surahs:
            stmt = stmt.where(Ayah.surah_id.in_(parsed.scope.surahs))
        if parsed.scope.juz:
            stmt = stmt.where(Ayah.juz.in_(parsed.scope.juz))

    matches = stmt.subquery("m")
    total = session.scalar(select(func.count()).select_from(matches)) or 0
    ayah_count = session.scalar(
        select(func.count(func.distinct(matches.c.ayah_id))).select_from(matches)
    ) or 0

    rows = session.execute(
        select(
            matches.c.ayah_id,
            Ayah.surah_id,
            Ayah.ayah_num,
            Ayah.text_uthmani,
            Surah.name_translit,
            Surah.revelation_place,
            func.min(matches.c.anchor).label("anchor"),
        )
        .join(Ayah, Ayah.id == matches.c.ayah_id)
        .join(Surah, Surah.id == Ayah.surah_id)
        .group_by(
            matches.c.ayah_id,
            Ayah.surah_id,
            Ayah.ayah_num,
            Ayah.text_uthmani,
            Surah.name_translit,
            Surah.revelation_place,
        )
        .order_by(matches.c.ayah_id)
        .limit(limit)
        .offset(offset)
    ).all()

    by_place = dict(
        session.execute(
            select(Surah.revelation_place, func.count(func.distinct(matches.c.ayah_id)))
            .select_from(matches)
            .join(Ayah, Ayah.id == matches.c.ayah_id)
            .join(Surah, Surah.id == Ayah.surah_id)
            .group_by(Surah.revelation_place)
        ).all()
    )

    return {
        "query": parsed.source,
        "reading": parsed.describe(),
        "total_matches": total,
        "total_ayat": ayah_count,
        "by_revelation_place": by_place,
        "exhaustive": True,
        "hits": [
            {
                "ayah_id": row.ayah_id,
                "ref": f"{row.surah_id}:{row.ayah_num}",
                "surah": row.name_translit,
                "revelation_place": row.revelation_place,
                "text": row.text_uthmani,
            }
            for row in rows
        ],
        "returned": len(rows),
        "truncated": ayah_count > offset + len(rows),
        "note": (
            "Every match in the corpus is counted; the list is a page of them. "
            "Matching is over the Quranic Arabic Corpus's own tags, so a result is "
            "as good as the annotators' analysis and no better."
        ),
    }


def vocabulary(session: Session) -> dict:
    """What the language accepts, with live counts from this corpus."""
    counts = {}
    for slot, column in _COLUMN.items():
        rows = session.execute(
            select(column, func.count()).where(column.is_not(None)).group_by(column)
        ).all()
        counts[slot] = {value: n for value, n in rows}
    tags = dict(
        session.execute(
            select(Segment.tag, func.count())
            .where(Segment.tag.is_not(None))
            .group_by(Segment.tag)
            .order_by(func.count().desc())
        ).all()
    )
    return {
        "pos_classes": {"N": "noun", "V": "verb", "P": "particle"},
        "features": {slot: sorted(FEATURES[slot]) for slot in FEATURES},
        "counts": counts,
        "tags": tags,
        "keys": sorted(TOKEN_KEYS),
        "scopes": ["@makki", "@madani", "@surah:N", "@juz:N"],
        "operators": {
            " ": "immediately adjacent segments",
            ">": "somewhere later in the same ayah",
            "+": "several constraints on one segment",
        },
        "examples": EXAMPLES,
    }


# Worked examples. These double as the eval fixtures — each one is a question a
# researcher actually asks, written in the language.
EXAMPLES: list[dict] = [
    {"query": "V:IMPV", "asks": "every imperative verb in the Qur'an"},
    {"query": "V:IMPV P", "asks": "an imperative immediately governing a preposition"},
    {"query": "V:PERF:PASS", "asks": "every passive perfect verb"},
    {"query": "tag:COND", "asks": "every conditional particle"},
    {"query": "tag:COND > V:PERF", "asks": "a conditional particle with a perfect verb later in the ayah"},
    {"query": "tag:COND > V:PERF @makki", "asks": "the same, restricted to Makki surahs"},
    {"query": "root:صبر+V:IMPF", "asks": "imperfect verbs from the root ص-ب-ر"},
    {"query": "root:علم+V:PERF @madani", "asks": "perfect verbs from ع-ل-م in Madani surahs"},
    {"query": "N:INDEF:F", "asks": "indefinite feminine nouns"},
    {"query": "V:IMPF:JUS", "asks": "jussive imperfect verbs"},
    {"query": "V:IMPF:SUBJ", "asks": "subjunctive imperfect verbs"},
    {"query": "N:F:D", "asks": "feminine dual nouns"},
    {"query": "tag:NEG V", "asks": "a negative particle immediately before a verb"},
    {"query": "tag:NEG V:IMPF:JUS", "asks": "negation with a jussive — the lam of prohibition pattern"},
    {"query": "N:ACT_PCPL", "asks": "every active participle"},
    {"query": "N:PASS_PCPL", "asks": "every passive participle"},
    {"query": "V:PERF:3:M:P", "asks": "third person masculine plural perfect verbs"},
    {"query": "V:IMPV > tag:CONJ", "asks": "an imperative followed later by a conjunction"},
    {"query": "root:كتب @makki", "asks": "every segment from the root ك-ت-ب in Makki surahs"},
    {"query": "P tag:DET N", "asks": "preposition, definite article, noun — the bi'l- pattern"},
]

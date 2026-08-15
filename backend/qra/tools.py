"""The tool surface.

One implementation, three surfaces: the agents call these functions directly,
the HTTP API wraps them, and the MCP server exposes them to Claude, Cursor or
any other MCP client. Adding a capability here makes it available everywhere at
once — and, more importantly, means the tool an agent used and the tool a
researcher can run by hand are provably the same code.

Every function returns plain JSON-serialisable data with citations attached.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from qra.analytics import conditionals as conditionals_mod
from qra.analytics import cooccurrence as cooccurrence_mod
from qra.analytics import distribution as distribution_mod
from qra.analytics import mutashabihat as mutashabihat_mod
from qra.analytics import narrative as narrative_mod
from qra.analytics.hypothesis import compile_hypothesis, run_hypothesis
from qra.citations import tafsir_citation
from qra.models import Edition, TafsirEntry, Translation
from qra.retrieval import deterministic as det
from qra.retrieval import graph as graph_mod
from qra.retrieval.base import CorpusFilter
from qra.retrieval.deterministic import MorphologyFilter, RootQuery


def _corpus_filter(**kwargs) -> CorpusFilter:
    return CorpusFilter(
        surahs=kwargs.get("surahs"),
        revelation_place=kwargs.get("revelation_place"),
        juz=kwargs.get("juz"),
        revelation_order_min=kwargs.get("revelation_order_min"),
        revelation_order_max=kwargs.get("revelation_order_max"),
    )


# ---------------------------------------------------------------------------
# Deterministic corpus tools
# ---------------------------------------------------------------------------


def search_root(
    session: Session,
    root: str,
    *,
    revelation_place: str | None = None,
    surahs: list[int] | None = None,
    pos_class: str | None = None,
    aspect: str | None = None,
    verb_form: str | None = None,
    derivation: str | None = None,
    limit: int = 50,
) -> dict:
    """Every occurrence of an Arabic root, exhaustively. Filters are optional."""
    query = RootQuery(
        root=root,
        filters=_corpus_filter(revelation_place=revelation_place, surahs=surahs),
        morphology=MorphologyFilter(
            pos_class=pos_class, aspect=aspect, verb_form=verb_form, derivation=derivation
        ),
        limit=limit,
    )
    return det.search_root(session, query).to_dict()


def count_occurrences(
    session: Session,
    *,
    root: str | None = None,
    lemma: str | None = None,
    phrase: str | None = None,
    revelation_place: str | None = None,
    surahs: list[int] | None = None,
) -> dict:
    """Counts only, with the scope stated. Use instead of estimating."""
    return det.count_occurrences(
        session,
        root=root,
        lemma=lemma,
        phrase=phrase,
        filters=_corpus_filter(revelation_place=revelation_place, surahs=surahs),
    )


def get_ayah(session: Session, surah: int, ayah: int, *, with_translations: bool = True) -> dict:
    """One ayah with its citation, and optionally every loaded translation."""
    span = det.get_ayah(session, surah, ayah)
    if span is None:
        return {"found": False, "ref": f"{surah}:{ayah}"}
    payload = span.to_dict()
    payload["found"] = True
    if with_translations:
        rows = session.execute(
            select(Translation, Edition)
            .join(Edition, Edition.id == Translation.edition_id)
            .where(Translation.surah_id == surah, Translation.ayah_num == ayah)
        ).all()
        payload["translations"] = [
            {
                "edition": edition.slug,
                "language": edition.language,
                "author": edition.author,
                "text": translation.text,
                "license": edition.license,
            }
            for translation, edition in rows
        ]
    return payload


def get_morphology(session: Session, surah: int, ayah: int) -> dict:
    """Word-by-word morphological analysis of one ayah."""
    return det.get_morphology(session, surah, ayah)


def get_root_profile(session: Session, root: str) -> dict:
    """Derivation family, verb forms, lemmas and distribution of a root."""
    return det.root_profile(session, root)


def search_phrase(
    session: Session, phrase: str, *, ignore_diacritics: bool = True, limit: int = 50
) -> dict:
    """Exact Arabic phrase search, diacritic-insensitive by default."""
    return det.search_phrase(
        session, phrase, ignore_diacritics=ignore_diacritics, limit=limit
    ).to_dict()


def search_translations(
    session: Session,
    query: str,
    *,
    language: str | None = None,
    limit: int = 20,
    include_tafsir: bool = False,
) -> dict:
    """BM25 search over translations (and optionally tafsir). Ranked, not exhaustive."""
    from qra.retrieval.lexical import search_lexical

    kinds = ("translation", "tafsir") if include_tafsir else ("translation",)
    spans = search_lexical(
        session,
        query,
        kinds=kinds,
        languages=(language,) if language else None,
        limit=limit,
    )
    return {
        "query": query,
        "mode": "lexical_bm25",
        "exhaustive": False,
        "results": [s.to_dict() for s in spans],
    }


# ---------------------------------------------------------------------------
# Commentary, hadith, graph
# ---------------------------------------------------------------------------


def get_tafsir(
    session: Session, surah: int, ayah: int, *, editions: list[str] | None = None, chars: int = 4000
) -> dict:
    """Commentary on an ayah from every loaded edition, disagreement preserved.

    Returns one entry per edition rather than a merged summary: four positions
    stay four positions.
    """
    stmt = (
        select(TafsirEntry, Edition)
        .join(Edition, Edition.id == TafsirEntry.edition_id)
        .where(
            TafsirEntry.surah_id == surah,
            TafsirEntry.ayah_start <= ayah,
            TafsirEntry.ayah_end >= ayah,
        )
    )
    if editions:
        stmt = stmt.where(Edition.slug.in_(editions))
    rows = session.execute(stmt).all()
    return {
        "ref": f"{surah}:{ayah}",
        "editions_returned": len(rows),
        "entries": [
            {
                "edition": edition.slug,
                "name": edition.name,
                "author": edition.author,
                "era": edition.era,
                "death_year_hijri": edition.death_year_hijri,
                "language": edition.language,
                "covers": f"{entry.surah_id}:{entry.ayah_start}-{entry.ayah_end}",
                "text": entry.text[:chars],
                "truncated": len(entry.text) > chars,
                "citation": tafsir_citation(entry, edition).to_dict(),
            }
            for entry, edition in sorted(rows, key=lambda r: (r[1].death_year_hijri or 9999))
        ],
        "note": "Positions are listed separately by design; they are not reconciled.",
    }


def get_hadith_for_ayah(session: Session, surah: int, ayah: int, *, limit: int = 20) -> dict:
    """Hadith that quote this ayah, with grading always attached."""
    span = det.get_ayah(session, surah, ayah)
    if span is None:
        return {"found": False}
    neighbourhood = graph_mod.ayah_neighbourhood(session, span.ayah_id, limit=limit)
    hadith = neighbourhood.get("hadith", [])
    return {
        "ref": f"{surah}:{ayah}",
        "count": len(hadith),
        "hadith": hadith,
        "grading_warning": (
            "Collections other than Bukhari and Muslim are ungraded in the source dataset and "
            "appear as 'unknown'. An ungraded narration is not a sound one — check a grading "
            "authority before relying on it."
        ),
        "method": "literal 5-word phrase match between hadith matn and ayah text",
    }


def cooccurrence(
    session: Session, root_a: str, root_b: str, *, scope: str = "ayah"
) -> dict:
    """PMI and significance for a root pair, with the chance baseline attached."""
    return cooccurrence_mod.associate(session, root_a, root_b, scope=scope)


def top_cooccurrences(session: Session, root: str, *, scope: str = "ayah", limit: int = 20) -> dict:
    """A root's strongest partners, corrected for multiple comparisons."""
    return cooccurrence_mod.top_partners(session, root, scope=scope, limit=limit)


def ayah_graph(session: Session, surah: int, ayah: int) -> dict:
    """Everything one hop from an ayah: roots, concepts, parallels, tafsir, hadith."""
    span = det.get_ayah(session, surah, ayah)
    if span is None:
        return {}
    return graph_mod.ayah_neighbourhood(session, span.ayah_id)


# ---------------------------------------------------------------------------
# Pattern engine
# ---------------------------------------------------------------------------


def root_distribution(session: Session, root: str) -> dict:
    """Frequency by surah on both mushaf and revelation order, normalised."""
    return distribution_mod.root_distribution(session, root)


def revelation_timeline(session: Session, roots: list[str], *, buckets: int = 12) -> dict:
    """Several roots plotted along the revelation timeline."""
    return distribution_mod.revelation_timeline(session, roots, buckets=buckets)


def test_hypothesis(
    session: Session, statement: str, *, language: str = "ur", sample: int = 25
) -> dict:
    """Compile a natural-language claim and test it. Violations come first."""
    spec = compile_hypothesis(session, statement, language=language)
    return run_hypothesis(session, spec, sample=sample).to_dict()


def find_conditionals(
    session: Session, *, roots: list[str] | None = None, particle: str | None = None, limit: int = 50
) -> dict:
    """Mined إن/إذا … فـ structures as condition -> consequence."""
    return conditionals_mod.find_conditionals(session, roots=roots, particle=particle, limit=limit)


def similar_ayat(session: Session, surah: int, ayah: int, *, limit: int = 20) -> dict:
    """Mutashabihat: near-identical wording and same-content parallels, with deltas."""
    span = det.get_ayah(session, surah, ayah)
    if span is None:
        return {}
    return mutashabihat_mod.similar_to(session, span.ayah_id, limit=limit)


def narrative_diff(session: Session, figure: str) -> dict:
    """Every telling of a figure's story, aligned: adds, omits, reorders."""
    return narrative_mod.narrative_diff(session, figure)


def traced(name: str, fn, session, /, **kwargs):
    """Run a tool inside a span. Used by the MCP server and the API so a tool
    call is visible wherever it came from, not only inside an agent run."""
    from qra.observability import trace

    with trace(name, kind="tool", **kwargs) as span:
        result = fn(session, **kwargs)
        span["result"] = result if isinstance(result, dict) else {}
    return result


TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "search_root": {"fn": search_root, "exhaustive": True},
    "count_occurrences": {"fn": count_occurrences, "exhaustive": True},
    "get_ayah": {"fn": get_ayah, "exhaustive": True},
    "get_morphology": {"fn": get_morphology, "exhaustive": True},
    "get_root_profile": {"fn": get_root_profile, "exhaustive": True},
    "search_phrase": {"fn": search_phrase, "exhaustive": True},
    "search_translations": {"fn": search_translations, "exhaustive": False},
    "get_tafsir": {"fn": get_tafsir, "exhaustive": True},
    "get_hadith_for_ayah": {"fn": get_hadith_for_ayah, "exhaustive": False},
    "cooccurrence": {"fn": cooccurrence, "exhaustive": True},
    "top_cooccurrences": {"fn": top_cooccurrences, "exhaustive": True},
    "ayah_graph": {"fn": ayah_graph, "exhaustive": True},
    "root_distribution": {"fn": root_distribution, "exhaustive": True},
    "revelation_timeline": {"fn": revelation_timeline, "exhaustive": True},
    "test_hypothesis": {"fn": test_hypothesis, "exhaustive": True},
    "find_conditionals": {"fn": find_conditionals, "exhaustive": True},
    "similar_ayat": {"fn": similar_ayat, "exhaustive": False},
    "narrative_diff": {"fn": narrative_diff, "exhaustive": False},
}

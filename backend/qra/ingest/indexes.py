"""Derived structures built after the corpus lands.

Everything here is recomputable from the source tables, so it can be dropped
and rebuilt without touching the data layer's integrity.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from qra.arabic import jaccard, shingles, tokenise, tokenise_multilingual
from qra.config import settings
from qra.models import (
    Ayah,
    AyahLink,
    Concept,
    ConceptAyah,
    ConceptRoot,
    ConditionalStructure,
    Edition,
    Hadith,
    HadithAyahLink,
    IngestLog,
    Lemma,
    Root,
    SearchDoc,
    SearchPosting,
    SearchTerm,
    Segment,
    TafsirEntry,
    Translation,
    Word,
)

# Conditional particles, keyed by the *folded* form of the segment the corpus
# tagged COND. Several entries look odd until you remember the corpus segments
# contractions: إمّا is إن+ما (folded "ا"), لَئِن is ل+ئن (folded "ين").
CONDITIONAL_PARTICLES = {
    "ان": "in",
    "ا": "in",  # إمّا (إن + ما)
    "ين": "in",  # لَئِن (emphatic لـ + إن)
    "اذا": "idha",
    "لو": "law",
    "لولا": "lawla",
    "لوما": "lawma",
    "من": "man",
    "ما": "ma",
    "مهما": "mahma",
    "كلما": "kullama",
    "اي": "ayy",
    "ايا": "ayy",
    "اين": "ayna",
    "اينما": "ayna",
    "حيث": "haythu",
    "حيثما": "haythu",
    "متي": "mata",
    "اما": "amma",
    "الا": "illa",
}


def refresh_counts(session: Session) -> dict:
    """Materialise root/lemma frequency counts used all over the analytics."""
    session.execute(update(Root).values(occurrence_count=0, ayah_count=0))
    session.execute(update(Lemma).values(occurrence_count=0))

    session.execute(
        sql_text(
            """
            update root set
                occurrence_count = coalesce(c.n, 0),
                ayah_count = coalesce(c.a, 0)
            from (
                select root_id, count(*) as n, count(distinct ayah_id) as a
                from segment where root_id is not null group by root_id
            ) c
            where root.id = c.root_id
            """
        )
    )
    session.execute(
        sql_text(
            """
            update lemma set occurrence_count = coalesce(c.n, 0)
            from (select lemma_id, count(*) as n from segment
                  where lemma_id is not null group by lemma_id) c
            where lemma.id = c.lemma_id
            """
        )
    )
    # Make the word count the *corpus's* word division rather than whitespace
    # tokenisation of the text. Analytics divide segment counts by word counts
    # to get rates per 1000 words; if numerator and denominator come from
    # different word divisions, every rate is quietly a little wrong.
    session.execute(
        sql_text(
            """
            update ayah set word_count = c.n
            from (select ayah_id, count(*) as n from word group by ayah_id) c
            where ayah.id = c.ayah_id and ayah.word_count <> c.n
            """
        )
    )
    session.commit()
    roots = session.scalar(select(func.count()).select_from(Root))
    return {"roots": roots}


# ---------------------------------------------------------------------------
# Lexical (BM25) index
# ---------------------------------------------------------------------------


def build_lexical_index(
    session: Session, kinds: tuple[str, ...] = ("ayah", "translation")
) -> dict:
    """Build the inverted index that :mod:`qra.retrieval.lexical` scores over.

    Defaults to ayah text + translations, which covers the searches researchers
    actually run. Add ``tafsir``/``hadith`` explicitly — they are an order of
    magnitude more postings and take proportionally longer.
    """
    session.execute(delete(SearchPosting))
    session.execute(delete(SearchTerm))
    session.execute(delete(SearchDoc).where(SearchDoc.kind.in_(kinds)))
    session.flush()

    docs: list[dict] = []
    if "ayah" in kinds:
        for aid, body in session.execute(select(Ayah.id, Ayah.text_uthmani)).all():
            docs.append(
                {
                    "kind": "ayah",
                    "ref_id": aid,
                    "edition_id": None,
                    "ayah_id": aid,
                    "language": "ar",
                    "text": body,
                }
            )
    if "translation" in kinds:
        editions = {e.id: e for e in session.scalars(select(Edition)).all()}
        for tid, eid, aid, body in session.execute(
            select(Translation.id, Translation.edition_id, Translation.ayah_id, Translation.text)
        ).all():
            docs.append(
                {
                    "kind": "translation",
                    "ref_id": tid,
                    "edition_id": eid,
                    "ayah_id": aid,
                    "language": editions[eid].language if eid in editions else "en",
                    "text": body,
                }
            )
    if "tafsir" in kinds:
        editions = {e.id: e for e in session.scalars(select(Edition)).all()}
        for tid, eid, aid, body in session.execute(
            select(
                TafsirEntry.id, TafsirEntry.edition_id, TafsirEntry.ayah_id_start, TafsirEntry.text
            )
        ).all():
            docs.append(
                {
                    "kind": "tafsir",
                    "ref_id": tid,
                    "edition_id": eid,
                    "ayah_id": aid,
                    "language": editions[eid].language if eid in editions else "ar",
                    "text": body,
                }
            )
    if "hadith" in kinds:
        for hid, eid, ar, en in session.execute(
            select(Hadith.id, Hadith.edition_id, Hadith.text_ar, Hadith.text_translation)
        ).all():
            docs.append(
                {
                    "kind": "hadith",
                    "ref_id": hid,
                    "edition_id": eid,
                    "ayah_id": None,
                    "language": "ar",
                    "text": " ".join(filter(None, (ar, en))),
                }
            )

    rows = []
    tokenised: list[list[str]] = []
    for doc in docs:
        tokens = (
            tokenise(doc["text"]) if doc["language"] == "ar" else tokenise_multilingual(doc["text"])
        )
        tokenised.append(tokens)
        rows.append({**doc, "length": len(tokens)})

    for offset in range(0, len(rows), 2000):
        session.execute(insert(SearchDoc), rows[offset : offset + 2000])
    session.flush()

    doc_ids = {
        (kind, ref_id): did
        for did, kind, ref_id in session.execute(
            select(SearchDoc.id, SearchDoc.kind, SearchDoc.ref_id)
        ).all()
    }

    postings: list[dict] = []
    df: Counter[str] = Counter()
    for doc, tokens in zip(rows, tokenised, strict=True):
        did = doc_ids[(doc["kind"], doc["ref_id"])]
        counts = Counter(t for t in tokens if len(t) <= 64)
        for term, tf in counts.items():
            postings.append({"term": term, "doc_id": did, "tf": tf})
        df.update(counts.keys())

    for offset in range(0, len(postings), 10000):
        session.execute(insert(SearchPosting), postings[offset : offset + 10000])
    term_rows = [{"term": t, "df": n} for t, n in df.items()]
    for offset in range(0, len(term_rows), 10000):
        session.execute(insert(SearchTerm), term_rows[offset : offset + 10000])

    session.add(
        IngestLog(
            step="index:lexical",
            rows=len(postings),
            detail={"docs": len(rows), "terms": len(term_rows), "kinds": list(kinds)},
        )
    )
    session.commit()
    return {"docs": len(rows), "postings": len(postings), "terms": len(term_rows)}


# ---------------------------------------------------------------------------
# Mutashabihat (near-identical verses)
# ---------------------------------------------------------------------------


def detect_mutashabihat(
    session: Session, *, threshold: float = 0.6, min_words: int = 4, ngram: int = 3
) -> dict:
    """Find near-identical ayah pairs by word-shingle Jaccard similarity.

    Deliberately string-based: the classical mutashabihat problem is about
    wording, and a lexical measure is reproducible and explainable in a way an
    embedding score is not. Embedding-based candidates are layered on top by
    :mod:`qra.retrieval.semantic` when a provider is configured.
    """
    session.execute(delete(AyahLink).where(AyahLink.kind == "mutashabih"))
    rows = session.execute(select(Ayah.id, Ayah.text_search, Ayah.surah_id, Ayah.ayah_num)).all()

    tokens = {aid: body.split() for aid, body, _, _ in rows}
    grams = {
        aid: shingles(tok, ngram) for aid, tok in tokens.items() if len(tok) >= min_words
    }

    # Inverted index over shingles keeps this O(candidate pairs) instead of
    # 6236^2 — and the corpus is small enough that we then check every candidate
    # exactly, so recall inside the threshold is complete.
    index: dict[str, list[int]] = defaultdict(list)
    for aid, gram_set in grams.items():
        for gram in gram_set:
            index[gram].append(aid)

    candidates: set[tuple[int, int]] = set()
    for aids in index.values():
        if len(aids) < 2 or len(aids) > 400:
            continue
        for i, a in enumerate(aids):
            for b in aids[i + 1 :]:
                candidates.add((a, b) if a < b else (b, a))

    links = []
    for a, b in candidates:
        score = jaccard(grams[a], grams[b])
        if score < threshold:
            continue
        ta, tb = tokens[a], tokens[b]
        only_a = [w for w in ta if w not in set(tb)]
        only_b = [w for w in tb if w not in set(ta)]
        detail = {
            "delta_a": only_a[:12],
            "delta_b": only_b[:12],
            "identical": ta == tb,
            "len_a": len(ta),
            "len_b": len(tb),
        }
        links.append(
            {"src_ayah_id": a, "dst_ayah_id": b, "kind": "mutashabih", "score": score, "detail": detail}
        )
        links.append(
            {
                "src_ayah_id": b,
                "dst_ayah_id": a,
                "kind": "mutashabih",
                "score": score,
                "detail": {**detail, "delta_a": detail["delta_b"], "delta_b": detail["delta_a"]},
            }
        )

    for offset in range(0, len(links), 2000):
        session.execute(insert(AyahLink), links[offset : offset + 2000])
    session.add(
        IngestLog(
            step="index:mutashabihat",
            rows=len(links),
            detail={"threshold": threshold, "ngram": ngram, "pairs": len(links) // 2},
        )
    )
    session.commit()
    parallels = detect_parallels(session)
    return {"pairs": len(links) // 2, **parallels}


def detect_parallels(
    session: Session,
    *,
    threshold: float = 0.5,
    min_shared_roots: int = 5,
    common_root_cutoff: int = 400,
) -> dict:
    """Second mutashabihat tier: same content, different wording.

    2:58 and 7:161 tell the same episode with ``قلنا ادخلوا`` against
    ``قيل لهم اسكنوا``; their word-shingle overlap is 0.08, so the string tier
    correctly refuses to call them near-identical. Comparing *content root sets*
    catches exactly this class — the parallel a researcher wants — while staying
    as reproducible and explainable as the string tier. Roots occurring more
    than ``common_root_cutoff`` times are treated as function vocabulary and
    excluded, or every ayah mentioning God would match every other.
    """
    session.execute(delete(AyahLink).where(AyahLink.kind == "parallel"))

    common = {
        rid
        for (rid,) in session.execute(
            select(Root.id).where(Root.occurrence_count > common_root_cutoff)
        ).all()
    }
    roots_by_ayah: dict[int, set[int]] = defaultdict(set)
    for ayah_id, root_id in session.execute(
        select(Segment.ayah_id, Segment.root_id).where(Segment.root_id.isnot(None))
    ).all():
        if root_id not in common:
            roots_by_ayah[ayah_id].add(root_id)

    display = dict(session.execute(select(Root.id, Root.root_display)).all())
    index: dict[int, list[int]] = defaultdict(list)
    for ayah_id, roots in roots_by_ayah.items():
        if len(roots) >= min_shared_roots:
            for root_id in roots:
                index[root_id].append(ayah_id)

    candidates: set[tuple[int, int]] = set()
    for ayat in index.values():
        if len(ayat) > 300:  # a root this widespread generates noise, not leads
            continue
        for i, a in enumerate(ayat):
            for b in ayat[i + 1 :]:
                candidates.add((a, b) if a < b else (b, a))

    links = []
    for a, b in candidates:
        ra, rb = roots_by_ayah[a], roots_by_ayah[b]
        shared = ra & rb
        if len(shared) < min_shared_roots:
            continue
        score = len(shared) / len(ra | rb)
        if score < threshold:
            continue
        detail = {
            "shared_roots": sorted(display[r] for r in shared),
            "only_a": sorted(display[r] for r in (ra - rb))[:12],
            "only_b": sorted(display[r] for r in (rb - ra))[:12],
        }
        links.append({"src_ayah_id": a, "dst_ayah_id": b, "kind": "parallel", "score": score, "detail": detail})
        links.append(
            {
                "src_ayah_id": b,
                "dst_ayah_id": a,
                "kind": "parallel",
                "score": score,
                "detail": {**detail, "only_a": detail["only_b"], "only_b": detail["only_a"]},
            }
        )

    for offset in range(0, len(links), 2000):
        session.execute(insert(AyahLink), links[offset : offset + 2000])
    session.add(
        IngestLog(
            step="index:parallels",
            rows=len(links),
            detail={"threshold": threshold, "min_shared_roots": min_shared_roots},
        )
    )
    session.commit()
    return {"parallel_pairs": len(links) // 2}


# ---------------------------------------------------------------------------
# Conditional structures: إِنْ / إِذَا … فَ…
# ---------------------------------------------------------------------------


def mine_conditionals(session: Session) -> dict:
    """Extract condition -> consequence triples from the morphology.

    Grounded in the corpus tags rather than regex: ``COND`` marks the
    conditional particle and ``RSLT`` marks the ف of the apodosis, so the split
    point between protasis and apodosis is the annotators' judgement, not ours.
    Structures without an explicit ف are still captured, at lower confidence,
    with the apodosis taken as the remainder of the ayah.
    """
    session.execute(delete(ConditionalStructure))

    words = defaultdict(list)  # ayah_id -> [(position, text, root_display, is_verb)]
    for ayah_id, position, word_text, pos, root_display in session.execute(
        select(Word.ayah_id, Word.position, Word.text, Word.pos, Root.root_display)
        .join(Root, Word.root_id == Root.id, isouter=True)
        .order_by(Word.ayah_id, Word.position)
    ).all():
        words[ayah_id].append((position, word_text, root_display, pos == "V"))

    markers = defaultdict(list)  # ayah_id -> [(word_position, tag, form_search)]
    for ayah_id, position, tag, form_search, surah_id in session.execute(
        select(Segment.ayah_id, Word.position, Segment.tag, Segment.form_search, Segment.surah_id)
        .join(Word, Segment.word_id == Word.id)
        .where(Segment.tag.in_(("COND", "RSLT")))
        .order_by(Segment.ayah_id, Word.position)
    ).all():
        markers[ayah_id].append((position, tag, form_search, surah_id))

    rows: list[dict] = []
    unsplit = 0
    for ayah_id, items in markers.items():
        conds = [i for i in items if i[1] == "COND"]
        results = [i for i in items if i[1] == "RSLT"]
        ayah_words = words.get(ayah_id, [])
        if not ayah_words:
            continue
        last_word = ayah_words[-1][0]

        for idx, (position, _tag, form, surah_id) in enumerate(conds):
            next_cond = conds[idx + 1][0] if idx + 1 < len(conds) else last_word + 1
            apodosis = next((r for r in results if position < r[0] < next_cond), None)
            if apodosis:
                split, marker = apodosis[0], apodosis[2]
                confidence = 0.9
            else:
                # No explicit ف. Arabic conditionals without it put the apodosis
                # verb straight after the protasis clause, so split at the second
                # verb in the span — a stated heuristic, flagged as lower
                # confidence, never presented as the annotators' judgement.
                verbs = [w[0] for w in ayah_words if w[3] and position < w[0] < next_cond]
                if len(verbs) < 2:
                    unsplit += 1
                    continue
                split, marker, confidence = verbs[1], None, 0.5

            condition = [w for w in ayah_words if position <= w[0] < split]
            consequence = [w for w in ayah_words if split <= w[0] < next_cond]
            if not condition or not consequence:
                unsplit += 1
                continue
            rows.append(
                {
                    "ayah_id": ayah_id,
                    "surah_id": surah_id,
                    "particle": CONDITIONAL_PARTICLES.get(form, form),
                    "particle_form": form,
                    "condition_text": " ".join(w[1] for w in condition),
                    "consequence_text": " ".join(w[1] for w in consequence),
                    "apodosis_marker": marker,
                    "condition_roots": sorted({w[2] for w in condition if w[2]}),
                    "consequence_roots": sorted({w[2] for w in consequence if w[2]}),
                    "word_start": position,
                    "word_end": next_cond - 1,
                    "confidence": confidence,
                    "detail": {
                        "explicit_apodosis": marker is not None,
                        "condition_words": len(condition),
                        "consequence_words": len(consequence),
                    },
                }
            )

    for offset in range(0, len(rows), 2000):
        session.execute(insert(ConditionalStructure), rows[offset : offset + 2000])
    session.add(
        IngestLog(
            step="index:conditionals",
            rows=len(rows),
            detail={
                "with_explicit_fa": sum(1 for r in rows if r["apodosis_marker"]),
                "unsplit_conditionals": unsplit,
                "particles": dict(Counter(r["particle"] for r in rows)),
            },
        )
    )
    session.commit()
    return {"structures": len(rows)}


# ---------------------------------------------------------------------------
# Concepts + hadith links
# ---------------------------------------------------------------------------


def seed_concepts(session: Session) -> dict:
    """Load the curated concept -> root map and derive concept -> ayah edges.

    Concept membership is *derived from roots*, and every derived edge is
    tagged ``provenance='derived'`` so the UI never presents a computed thematic
    label as if a scholar asserted it.
    """
    path = settings.metadata_dir / "concepts.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    session.execute(delete(ConceptAyah))
    session.execute(delete(ConceptRoot))
    session.execute(delete(Concept))
    session.flush()

    from qra.arabic import normalise_root

    roots = {r: i for i, r in session.execute(select(Root.id, Root.root)).all()}
    concept_rows = []
    for item in payload["concepts"]:
        concept_rows.append(
            {
                "slug": item["slug"],
                "label_en": item["label_en"],
                "label_ar": item.get("label_ar"),
                "label_ur": item.get("label_ur"),
                "description": item.get("description"),
            }
        )
    session.execute(insert(Concept), concept_rows)
    session.flush()
    concept_ids = {s: i for i, s in session.execute(select(Concept.id, Concept.slug)).all()}

    root_links = []
    unresolved = []
    for item in payload["concepts"]:
        for root in item.get("roots", []):
            key = normalise_root(root)
            rid = roots.get(key)
            if rid is None:
                unresolved.append(root)
                continue
            root_links.append({"concept_id": concept_ids[item["slug"]], "root_id": rid})
    if root_links:
        session.execute(insert(ConceptRoot), root_links)
    session.flush()

    session.execute(
        sql_text(
            """
            insert into concept_ayah (concept_id, ayah_id, weight, provenance)
            select cr.concept_id, s.ayah_id, count(*)::float, 'derived'
            from concept_root cr
            join segment s on s.root_id = cr.root_id
            group by cr.concept_id, s.ayah_id
            on conflict do nothing
            """
        )
    )
    session.add(
        IngestLog(
            step="index:concepts",
            rows=len(root_links),
            detail={"concepts": len(concept_rows), "unresolved_roots": unresolved},
        )
    )
    session.commit()
    return {"concepts": len(concept_rows), "root_links": len(root_links), "unresolved": unresolved}


def link_hadith_to_ayat(session: Session, *, min_words: int = 5) -> dict:
    """Detect Qur'an quotations inside hadith matn by exact folded-phrase match.

    Conservative on purpose: a hadith is linked only when it contains a literal
    run of at least ``min_words`` words from an ayah. Fuzzy thematic links are
    the Hadith agent's job to *propose*, never the ingest's job to assert.
    """
    session.execute(delete(HadithAyahLink))
    ayat = session.execute(
        select(Ayah.id, Ayah.text_search, Ayah.surah_id, Ayah.ayah_num)
    ).all()

    phrase_index: dict[str, list[int]] = defaultdict(list)
    for aid, body, _s, _a in ayat:
        tokens = body.split()
        if len(tokens) < min_words:
            continue
        for i in range(len(tokens) - min_words + 1):
            phrase_index[" ".join(tokens[i : i + min_words])].append(aid)

    links: dict[tuple[int, int], dict] = {}
    for hid, body in session.execute(
        select(Hadith.id, Hadith.text_search).where(Hadith.text_search.isnot(None))
    ).all():
        tokens = (body or "").split()
        if len(tokens) < min_words:
            continue
        for i in range(len(tokens) - min_words + 1):
            phrase = " ".join(tokens[i : i + min_words])
            for aid in phrase_index.get(phrase, ()):
                links[(hid, aid)] = {
                    "hadith_id": hid,
                    "ayah_id": aid,
                    "relation": "quotes",
                    "confidence": 1.0,
                    "evidence": phrase,
                }

    values = list(links.values())
    for offset in range(0, len(values), 2000):
        session.execute(insert(HadithAyahLink), values[offset : offset + 2000])
    session.add(IngestLog(step="index:hadith_links", rows=len(values), detail={"min_words": min_words}))
    session.commit()
    return {"links": len(values)}

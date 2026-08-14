"""Load translations, tafsir, hadith and lexicons — all licence-gated."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from qra.arabic import search_form
from qra.config import settings
from qra.models import (
    Ayah,
    Edition,
    Hadith,
    IngestLog,
    LexiconEntry,
    Root,
    Surah,
    TafsirEntry,
    Translation,
)
from qra.sources import BY_SLUG, SourceSpec, checksum, fetch, require_ingestable

# Collections whose authenticity is a scholarly given; everything else keeps
# an explicit "not graded in this source" so the Hadith agent can shout about it.
_COLLECTION_GRADING = {
    "hadith-bukhari": ("sahih", "collection convention (Sahih al-Bukhari)"),
    "hadith-muslim": ("sahih", "collection convention (Sahih Muslim)"),
}
_GRADE_KEYS = ("grade", "grades", "grading", "hukm", "status")


def upsert_edition(session: Session, spec: SourceSpec) -> Edition:
    edition = session.scalar(select(Edition).where(Edition.slug == spec.slug))
    if edition is None:
        edition = Edition(slug=spec.slug)
        session.add(edition)
    edition.kind = spec.kind
    edition.language = spec.language
    edition.name = spec.name
    edition.author = spec.author
    edition.direction = spec.direction
    edition.source_url = spec.url or ""
    edition.license = spec.license
    edition.license_status = spec.license_status
    edition.license_notes = spec.notes or None
    edition.death_year_hijri = spec.death_year_hijri
    edition.era = spec.era
    session.flush()
    return edition


def _ayah_index(session: Session) -> dict[tuple[int, int], int]:
    return {
        (surah, num): aid
        for aid, surah, num in session.execute(
            select(Ayah.id, Ayah.surah_id, Ayah.ayah_num)
        ).all()
    }


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


def ingest_translation(session: Session, slug: str, *, force: bool = False) -> dict:
    spec = BY_SLUG[slug]
    require_ingestable(spec)
    payload = fetch(spec.url, force=force)
    verses = json.loads(payload)["quran"]

    edition = upsert_edition(session, spec)
    session.execute(delete(Translation).where(Translation.edition_id == edition.id))

    index = _ayah_index(session)
    rows = []
    for verse in verses:
        key = (verse["chapter"], verse["verse"])
        ayah_id = index.get(key)
        if ayah_id is None:
            continue
        text = (verse.get("text") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "edition_id": edition.id,
                "ayah_id": ayah_id,
                "surah_id": key[0],
                "ayah_num": key[1],
                "text": text,
            }
        )
    if rows:
        session.execute(insert(Translation), rows)
    session.add(
        IngestLog(
            step=f"translation:{slug}",
            source_url=spec.url,
            checksum=checksum(payload),
            rows=len(rows),
        )
    )
    session.commit()
    return {"edition": slug, "rows": len(rows)}


# ---------------------------------------------------------------------------
# Tafsir — chunked by ayah range
# ---------------------------------------------------------------------------


def _fetch_tafsir_surah(base_url: str, surah: int, force: bool) -> tuple[int, list[str]]:
    """Return per-ayah commentary text for one surah (index 0 == ayah 1)."""
    try:
        payload = fetch(f"{base_url}/{surah}.json", force=force, timeout=60.0)
    except httpx.HTTPError:
        return surah, []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return surah, []
    if isinstance(data, dict):
        data = data.get("ayahs") or data.get("tafsir") or []
    texts = []
    for item in data:
        if isinstance(item, dict):
            texts.append((item.get("text") or "").strip())
        elif isinstance(item, str):
            texts.append(item.strip())
        else:
            texts.append("")
    return surah, texts


def ingest_tafsir(session: Session, slug: str, *, force: bool = False, workers: int = 8) -> dict:
    """Load one tafsir edition.

    Sources publish commentary per ayah, but a commentator routinely treats a
    run of ayat as one unit and the same text is repeated across them. We
    collapse identical consecutive texts back into their real ayah range, which
    is both smaller and more honest about what was actually written.
    """
    spec = BY_SLUG[slug]
    require_ingestable(spec)
    edition = upsert_edition(session, spec)
    session.execute(delete(TafsirEntry).where(TafsirEntry.edition_id == edition.id))

    index = _ayah_index(session)
    counts = {s: c for s, c in session.execute(select(Surah.id, Surah.ayah_count)).all()}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = dict(
            pool.map(lambda s: _fetch_tafsir_surah(spec.url, s, force), sorted(counts))
        )

    rows: list[dict] = []
    missing: list[int] = []
    for surah, ayah_count in sorted(counts.items()):
        texts = results.get(surah) or []
        if not texts:
            missing.append(surah)
            continue
        start = 1
        chunk_index = 0
        while start <= min(ayah_count, len(texts)):
            text = texts[start - 1]
            end = start
            while (
                end < min(ayah_count, len(texts))
                and texts[end] == text  # texts[end] is ayah end+1
            ):
                end += 1
            if text:
                rows.append(
                    {
                        "edition_id": edition.id,
                        "surah_id": surah,
                        "ayah_start": start,
                        "ayah_end": end,
                        "ayah_id_start": index[(surah, start)],
                        "ayah_id_end": index[(surah, end)],
                        "text": text,
                        "chunk_index": chunk_index,
                        "reference": f"{spec.name} — {surah}:{start}"
                        + (f"-{end}" if end != start else ""),
                    }
                )
                chunk_index += 1
            start = end + 1

    for offset in range(0, len(rows), 2000):
        session.execute(insert(TafsirEntry), rows[offset : offset + 2000])
    session.add(
        IngestLog(
            step=f"tafsir:{slug}",
            source_url=spec.url,
            rows=len(rows),
            detail={"missing_surahs": missing},
        )
    )
    session.commit()
    return {"edition": slug, "entries": len(rows), "missing_surahs": len(missing)}


# ---------------------------------------------------------------------------
# Hadith
# ---------------------------------------------------------------------------


def _extract_grading(record: dict, slug: str) -> tuple[str, str | None]:
    for key in _GRADE_KEYS:
        value = record.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                return (
                    str(first.get("grade") or first.get("value") or "unknown"),
                    str(first.get("graded_by") or first.get("name") or "") or None,
                )
            return str(first), None
        if isinstance(value, str) and value.strip():
            return value.strip(), None
    default = _COLLECTION_GRADING.get(slug)
    if default:
        return default
    # Never invent a grade. "unknown" is a finding the researcher must see.
    return "unknown", "not graded in source dataset"


def ingest_hadith(session: Session, slug: str, *, force: bool = False) -> dict:
    spec = BY_SLUG[slug]
    require_ingestable(spec)
    payload = fetch(spec.url, force=force, timeout=300.0)
    data = json.loads(payload)

    edition = upsert_edition(session, spec)
    session.execute(delete(Hadith).where(Hadith.edition_id == edition.id))

    chapters = {
        c.get("id"): (c.get("english") or c.get("arabic") or "")
        for c in data.get("chapters", [])
        if isinstance(c, dict)
    }
    book_title = (data.get("metadata", {}).get("english") or {}).get("title") or spec.name

    rows: list[dict] = []
    seen: set[str] = set()
    for record in data.get("hadiths", []):
        number = str(record.get("idInBook") or record.get("id") or "")
        if not number or number in seen:
            continue
        seen.add(number)
        english = record.get("english") or {}
        translation = english.get("text") if isinstance(english, dict) else english
        narrator = english.get("narrator") if isinstance(english, dict) else None
        arabic = (record.get("arabic") or "").strip()
        grading, graded_by = _extract_grading(record, slug)
        rows.append(
            {
                "edition_id": edition.id,
                "collection": spec.extra.get("book", slug),
                "number": number,
                "book": book_title,
                "chapter": chapters.get(record.get("chapterId")),
                "text_ar": arabic or None,
                "text_search": search_form(arabic) if arabic else None,
                "text_translation": (
                    f"{narrator.strip()} {translation.strip()}".strip()
                    if narrator and translation
                    else (translation or "").strip() or None
                ),
                "translation_language": "en" if translation else None,
                "grading": grading,
                "graded_by": graded_by,
            }
        )

    for offset in range(0, len(rows), 2000):
        session.execute(insert(Hadith), rows[offset : offset + 2000])
    session.add(
        IngestLog(
            step=f"hadith:{slug}",
            source_url=spec.url,
            checksum=checksum(payload),
            rows=len(rows),
        )
    )
    session.commit()
    return {"edition": slug, "hadith": len(rows)}


# ---------------------------------------------------------------------------
# Lexicons — loaded from a local root-keyed JSONL you supply
# ---------------------------------------------------------------------------


def ingest_lexicon(session: Session, slug: str, path: Path | None = None) -> dict:
    """Load ``{"root": "علم", "headword": "...", "text": "...", "ref": "..."}`` lines.

    Lane, Mufradat and Lisan are public domain but have no source we trust for
    machine-readable accuracy, so this loader takes a file you provide rather
    than pretending to fetch one.
    """
    spec = BY_SLUG[slug]
    path = path or (settings.raw_dir / f"lexicon-{slug}.jsonl")
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. {spec.name} is public domain but must be supplied locally; "
            f"see docs/LICENSING.md."
        )
    edition = upsert_edition(session, spec)
    session.execute(delete(LexiconEntry).where(LexiconEntry.edition_id == edition.id))

    roots = {r: i for i, r in session.execute(select(Root.id, Root.root)).all()}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        from qra.arabic import normalise_root

        key = normalise_root(record.get("root", ""))
        rows.append(
            {
                "edition_id": edition.id,
                "root_id": roots.get(key),
                "headword": record.get("headword") or key,
                "text": record["text"],
                "reference": record.get("ref"),
            }
        )
    if rows:
        session.execute(insert(LexiconEntry), rows)
    session.add(IngestLog(step=f"lexicon:{slug}", source_url=str(path), rows=len(rows)))
    session.commit()
    return {"edition": slug, "entries": len(rows)}

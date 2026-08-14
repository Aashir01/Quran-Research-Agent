"""Citation payloads.

A retrieval result without a citation is not a result. Every span returned by
any retrieval mode, every claim in the evidence ledger and every sentence the
Scribe emits carries one of these, and the Critic re-resolves each one against
the database before the draft is allowed out.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class CitationError(ValueError):
    """Raised when a row cannot produce a citation. Never swallowed."""


@dataclass(frozen=True)
class Citation:
    kind: str  # ayah | translation | tafsir | hadith | lexicon | morphology
    ref: str  # human-readable: "2:255", "Bukhari 1", "Lane s.v. علم"
    ayah_ids: tuple[int, ...] = ()
    edition_slug: str | None = None
    edition_name: str | None = None
    author: str | None = None
    language: str | None = None
    source_url: str | None = None
    license: str | None = None
    reference: str | None = None  # volume/page within the edition
    grading: str | None = None  # hadith only, always surfaced
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        bits = [self.ref]
        if self.edition_name:
            who = f"{self.edition_name}"
            if self.author and self.author not in self.edition_name:
                who += f" — {self.author}"
            bits.append(who)
        if self.reference:
            bits.append(self.reference)
        if self.grading:
            bits.append(f"grading: {self.grading}")
        return " | ".join(bits)


def ayah_citation(ayah, edition=None) -> Citation:
    if ayah is None:
        raise CitationError("cannot cite a missing ayah")
    return Citation(
        kind="ayah",
        ref=f"{ayah.surah_id}:{ayah.ayah_num}",
        ayah_ids=(ayah.id,),
        edition_slug=getattr(edition, "slug", "quran-uthmani"),
        edition_name=getattr(edition, "name", "Qur'an (Uthmani)"),
        language="ar",
        source_url=getattr(edition, "source_url", None),
        license=getattr(edition, "license", None),
    )


def translation_citation(translation, edition) -> Citation:
    if translation is None or edition is None:
        raise CitationError("translation citation requires both row and edition")
    return Citation(
        kind="translation",
        ref=f"{translation.surah_id}:{translation.ayah_num}",
        ayah_ids=(translation.ayah_id,),
        edition_slug=edition.slug,
        edition_name=edition.name,
        author=edition.author,
        language=edition.language,
        source_url=edition.source_url,
        license=edition.license,
    )


def tafsir_citation(entry, edition, ayah_ids: tuple[int, ...] = ()) -> Citation:
    if entry is None or edition is None:
        raise CitationError("tafsir citation requires both row and edition")
    span = (
        f"{entry.surah_id}:{entry.ayah_start}"
        if entry.ayah_start == entry.ayah_end
        else f"{entry.surah_id}:{entry.ayah_start}-{entry.ayah_end}"
    )
    return Citation(
        kind="tafsir",
        ref=span,
        ayah_ids=ayah_ids or tuple(range(entry.ayah_id_start, entry.ayah_id_end + 1)),
        edition_slug=edition.slug,
        edition_name=edition.name,
        author=edition.author,
        language=edition.language,
        source_url=edition.source_url,
        license=edition.license,
        reference=entry.reference,
        extra={"era": edition.era, "death_year_hijri": edition.death_year_hijri},
    )


def hadith_citation(hadith, edition) -> Citation:
    if hadith is None or edition is None:
        raise CitationError("hadith citation requires both row and edition")
    return Citation(
        kind="hadith",
        ref=f"{edition.name} {hadith.number}",
        edition_slug=edition.slug,
        edition_name=edition.name,
        author=edition.author,
        language=hadith.translation_language or edition.language,
        source_url=edition.source_url,
        license=edition.license,
        reference=hadith.book or hadith.chapter,
        grading=hadith.grading or "unknown",
    )


def morphology_citation(segment, ayah) -> Citation:
    return Citation(
        kind="morphology",
        ref=f"{ayah.surah_id}:{ayah.ayah_num}:{segment.position}",
        ayah_ids=(ayah.id,),
        edition_slug="quranic-arabic-corpus",
        edition_name="Quranic Arabic Corpus (morphology)",
        author="Kais Dukes et al.",
        language="ar",
        license="GPL / CC BY 3.0 (see docs/LICENSING.md)",
    )

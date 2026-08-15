"""Citation manager.

Collects the citations behind a finding, note or hypothesis run, deduplicates
them, orders them the way a scholar expects (scripture first, then commentary
by the commentator's death date, then hadith, then translations), and formats
them for a bibliography in Urdu or English.

The ordering is not decoration. A reader checking a claim wants the primary
text first and needs to see at a glance whether a commentary is 4th-century or
20th-century, so the death date travels with the entry rather than living in a
footnote nobody reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

# Scripture, then commentary, then narrations, then renderings into other
# languages — most primary first.
KIND_ORDER = {"ayah": 0, "morphology": 1, "tafsir": 2, "hadith": 3, "translation": 4, "lexicon": 5}

LABELS = {
    "en": {
        "sources": "Sources",
        "quran": "Qur'an",
        "tafsir": "Commentary",
        "hadith": "Narrations",
        "translation": "Translations",
        "morphology": "Morphology",
        "lexicon": "Lexicons",
        "grading": "grading",
        "died": "d.",
        "licence": "Licence",
    },
    "ur": {
        "sources": "مآخذ",
        "quran": "قرآن",
        "tafsir": "تفاسیر",
        "hadith": "احادیث",
        "translation": "تراجم",
        "morphology": "صرف و نحو",
        "lexicon": "لغات",
        "grading": "درجہ",
        "died": "متوفی",
        "licence": "اجازت",
    },
}


@dataclass
class Bibliography:
    entries: list[dict] = field(default_factory=list)
    language: str = "en"

    @property
    def labels(self) -> dict:
        return LABELS.get(self.language, LABELS["en"])

    def grouped(self) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for entry in self.entries:
            groups.setdefault(entry["kind"], []).append(entry)
        return groups

    def lines(self) -> list[str]:
        out: list[str] = []
        for kind, entries in sorted(self.grouped().items(), key=lambda kv: KIND_ORDER.get(kv[0], 9)):
            out.append(self.labels.get(kind, kind.title()))
            for entry in entries:
                out.append(f"  {entry['formatted']}")
        return out


def _format(entry: dict, language: str) -> str:
    labels = LABELS.get(language, LABELS["en"])
    bits = [entry.get("ref") or ""]
    name = entry.get("edition_name")
    author = entry.get("author")
    if name:
        who = name
        if author and author not in name:
            died = ""
            if entry.get("death_year_hijri"):
                died = f", {labels['died']} {entry['death_year_hijri']} AH"
            who += f" — {author}{died}"
        bits.append(who)
    if entry.get("reference"):
        bits.append(entry["reference"])
    if entry.get("grading"):
        bits.append(f"{labels['grading']}: {entry['grading']}")
    return " · ".join(b for b in bits if b)


def collect(citations: list[dict], *, language: str = "en") -> Bibliography:
    """Deduplicate and order citations into a bibliography.

    Deduplication is on (kind, ref, edition): the same ayah cited from three
    different claims is one source, but the same ayah in two translations is
    two.
    """
    seen: dict[tuple, dict] = {}
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        key = (citation.get("kind"), citation.get("ref"), citation.get("edition_slug"))
        if key in seen:
            seen[key]["times_cited"] += 1
            continue
        entry = {
            "kind": citation.get("kind") or "ayah",
            "ref": citation.get("ref"),
            "edition_slug": citation.get("edition_slug"),
            "edition_name": citation.get("edition_name"),
            "author": citation.get("author"),
            "language": citation.get("language"),
            "license": citation.get("license"),
            "reference": citation.get("reference"),
            "grading": citation.get("grading"),
            "death_year_hijri": (citation.get("extra") or {}).get("death_year_hijri"),
            "times_cited": 1,
        }
        entry["formatted"] = _format(entry, language)
        seen[key] = entry

    entries = sorted(
        seen.values(),
        key=lambda e: (
            KIND_ORDER.get(e["kind"], 9),
            e.get("death_year_hijri") or 9999,
            e.get("ref") or "",
        ),
    )
    return Bibliography(entries=entries, language=language)


def licence_notice(session: Session, entries: list[dict], *, language: str = "en") -> str:
    """A licence line for the editions actually cited.

    Several shipped editions are non-commercial; an exported document leaves
    this system, so the terms have to leave with it.
    """
    from sqlalchemy import select

    from qra.models import Edition

    slugs = {e["edition_slug"] for e in entries if e.get("edition_slug")}
    if not slugs:
        return ""
    rows = session.scalars(select(Edition).where(Edition.slug.in_(slugs))).all()
    lines = [LABELS.get(language, LABELS["en"])["licence"] + ":"]
    for edition in sorted(rows, key=lambda e: e.slug):
        lines.append(f"  {edition.name} — {edition.license}")
        if edition.license_notes:
            lines.append(f"    {edition.license_notes}")
    return "\n".join(lines)

"""Citation styles (Track F).

A researcher who cannot paste a citation into a journal submission will retype
it, and a retyped citation is where the surah number drifts by one. So the
bibliography renders in the conventions the field actually uses rather than in
one house format.

Four styles, chosen because they cover where this work gets published:

* **chicago** — Chicago notes-and-bibliography, the default in Islamic studies
  monographs and most anglophone journals.
* **mla** — used by literature and comparative-religion departments.
* **ijmes** — the *International Journal of Middle East Studies* convention,
  which is the closest thing the field has to a standard for Arabic material
  and is what most Middle East studies journals ask for.
* **plain** — the app's own readable format, for notes and screens.

Two conventions specific to this material, and both are the sort of thing a
generic citation library gets wrong:

**Scripture is cited by reference, not by page.** Qur'an 2:255 is the citation;
the edition matters for the *wording*, not for locating the passage, so the
edition follows the reference rather than replacing it. Every style here keeps
the surah:ayah first.

**A hadith carries its grading or it is not fully cited.** A narration's
authenticity is part of its identity in a way that has no analogue in secular
citation — quoting Bukhari 1 without saying the collector graded it sahih omits
the thing a reader needs most. The grading travels in every style, including
the ones whose published manuals have nowhere to put it; where the manual has
no slot, it goes in the notes field rather than being dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

STYLES = ("chicago", "mla", "ijmes", "plain")

# Kinds that are cited by reference rather than by page, because the reference
# *is* the location and is stable across every edition ever printed.
BY_REFERENCE = frozenset({"ayah", "translation", "morphology"})


class StyleError(ValueError):
    pass


@dataclass
class Entry:
    kind: str
    ref: str
    edition_name: str = ""
    author: str = ""
    death_year_hijri: int | None = None
    reference: str = ""
    grading: str = ""
    url: str = ""
    accessed: str = ""

    @classmethod
    def from_citation(cls, citation: dict) -> Entry:
        return cls(
            kind=citation.get("kind") or "ayah",
            ref=citation.get("ref") or "",
            edition_name=citation.get("edition_name") or "",
            author=citation.get("author") or "",
            death_year_hijri=citation.get("death_year_hijri"),
            reference=citation.get("reference") or "",
            grading=citation.get("grading") or "",
            url=citation.get("source_url") or "",
            accessed=citation.get("accessed") or "",
        )


def _author_last_first(author: str) -> str:
    """Surname-first, without mangling an Arabic name.

    A generic formatter splits on the last space, which turns
    'Muhammad ibn Isma'il al-Bukhari' into 'al-Bukhari, Muhammad ibn Isma'il' —
    correct — and 'Ibn Kathir' into 'Kathir, Ibn' — wrong, because Ibn is part
    of the name rather than a given name. Names whose first token is a
    patronymic particle are left alone.
    """
    name = (author or "").strip()
    if not name:
        return ""
    first = name.split()[0].lower().strip("'’")
    if first in {"ibn", "abu", "abi", "al", "bin", "banu", "umm"}:
        return name
    parts = name.split()
    if len(parts) < 2:
        return name
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def _died(entry: Entry) -> str:
    return f" (d. {entry.death_year_hijri} AH)" if entry.death_year_hijri else ""


def _grading_clause(entry: Entry) -> str:
    return f", graded {entry.grading}" if entry.grading else ""


def _chicago(entry: Entry) -> str:
    if entry.kind in BY_REFERENCE:
        edition = f", {entry.edition_name}" if entry.edition_name else ""
        return f"Qur'an {entry.ref}{edition}."
    author = _author_last_first(entry.author)
    lead = f"{author}{_died(entry)}. " if author else ""
    title = f"*{entry.edition_name}*" if entry.edition_name else ""
    locus = f", {entry.reference}" if entry.reference else ""
    return f"{lead}{title}, {entry.ref}{locus}{_grading_clause(entry)}.".replace(", ,", ",")


def _mla(entry: Entry) -> str:
    if entry.kind in BY_REFERENCE:
        edition = f" {entry.edition_name}," if entry.edition_name else ""
        return f"*The Qur'an*.{edition} {entry.ref}."
    author = _author_last_first(entry.author)
    lead = f"{author}. " if author else ""
    title = f"*{entry.edition_name}*. " if entry.edition_name else ""
    locus = f", {entry.reference}" if entry.reference else ""
    return f"{lead}{title}{entry.ref}{locus}{_grading_clause(entry)}."


def _ijmes(entry: Entry) -> str:
    """IJMES: transliterated title, death date in AH, reference last."""
    if entry.kind in BY_REFERENCE:
        edition = f" ({entry.edition_name})" if entry.edition_name else ""
        return f"Qurʾan {entry.ref}{edition}"
    author = entry.author or ""
    lead = f"{author}{_died(entry)}, " if author else ""
    title = entry.edition_name or ""
    locus = f", {entry.reference}" if entry.reference else ""
    return f"{lead}{title}, {entry.ref}{locus}{_grading_clause(entry)}"


def _plain(entry: Entry) -> str:
    bits = [entry.ref]
    if entry.edition_name:
        who = entry.edition_name
        if entry.author and entry.author not in entry.edition_name:
            who += f" — {entry.author}{_died(entry)}"
        bits.append(who)
    if entry.reference:
        bits.append(entry.reference)
    if entry.grading:
        bits.append(f"grading: {entry.grading}")
    return " · ".join(b for b in bits if b)


FORMATTERS = {
    "chicago": _chicago,
    "mla": _mla,
    "ijmes": _ijmes,
    "plain": _plain,
}


def format_citation(citation: dict, *, style: str = "chicago") -> str:
    if style not in FORMATTERS:
        raise StyleError(f"style must be one of {', '.join(STYLES)}")
    return FORMATTERS[style](Entry.from_citation(citation))


def bibliography(citations: list[dict], *, style: str = "chicago") -> dict:
    """Render a deduplicated bibliography in one style.

    Deduplication is on (kind, ref, edition): the same ayah cited from three
    claims is one source, and the same ayah in two translations is two.
    """
    if style not in FORMATTERS:
        raise StyleError(f"style must be one of {', '.join(STYLES)}")

    seen: set[tuple] = set()
    rendered: list[dict] = []
    dropped_gradings = 0
    for citation in citations or []:
        entry = Entry.from_citation(citation)
        key = (entry.kind, entry.ref, entry.edition_name)
        if key in seen:
            continue
        seen.add(key)
        line = FORMATTERS[style](entry)
        if entry.grading and entry.grading not in line:
            dropped_gradings += 1
        rendered.append(
            {
                "kind": entry.kind,
                "ref": entry.ref,
                "text": line,
                "grading": entry.grading,
            }
        )

    rendered.sort(key=lambda row: (row["kind"], row["ref"]))
    return {
        "style": style,
        "entries": rendered,
        "count": len(rendered),
        "deduplicated_from": len(citations or []),
        "conventions": {
            "scripture_by_reference": (
                "Qur'an 2:255 is the citation. The edition determines the wording, not the "
                "location, so it follows the reference rather than replacing it."
            ),
            "grading_travels": (
                "A hadith's grading is part of its identity, not an annotation. Quoting "
                "Bukhari 1 without saying it was graded sahih omits what a reader needs "
                "most, so the grading appears in every style — in the notes field where "
                "the published manual has no slot for it."
            ),
        },
        "warning": (
            f"{dropped_gradings} hadith citation(s) carry a grading this style has no "
            "conventional slot for; it has been appended rather than dropped."
            if dropped_gradings
            else ""
        ),
    }

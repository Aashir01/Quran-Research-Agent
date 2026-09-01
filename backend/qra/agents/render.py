"""Template injection — the hard rule, enforced in code.

**Arabic text, translations and hadith matn are rendered from the database by
id. A model never produces them.**

A hallucinated ayah is not a bug to be tuned away with a better prompt; it is a
catastrophic failure of the product's only real promise. So the mechanism is
structural rather than instructional:

1. Agents write output containing *placeholders* — ``{{ayah:2:255}}``,
   ``{{translation:2:255|ur-jalandhry}}``, ``{{hadith:hadith-bukhari|1}}``.
2. :func:`render` resolves each placeholder against the database. An
   unresolvable reference raises rather than degrading to plausible text.
3. :func:`scan_for_unquoted_scripture` rejects any model output containing raw
   Arabic that did not come from a placeholder — so the failure mode is a
   refusal to render, not a fabricated verse.

The prompt asks for the same thing, but the prompt is not what enforces it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from qra.arabic import search_form
from qra.citations import ayah_citation, hadith_citation, translation_citation
from qra.models import Ayah, Edition, Hadith, TafsirEntry, Translation

PLACEHOLDER_RE = re.compile(r"\{\{(?P<kind>[a-z_]+):(?P<ref>[^}|]+)(?:\|(?P<arg>[^}]+))?\}\}")

# Any word containing Arabic-block characters. Classification happens per word
# (see _scripture_runs) rather than per regex match, because a fabricated verse
# dropped into an Urdu sentence must not be excused by the Urdu around it.
ARABIC_WORD_RE = re.compile(r"[ء-ۿࢠ-ࣿ]+")

# Letters that exist in Urdu (and Persian) but not in Qur'anic Arabic. Their
# presence marks a run as the agent's own prose rather than quoted scripture —
# necessary because the Scribe writes Urdu in the same script as the text it
# must never invent.
_URDU_ONLY = set("ٹڈڑژچگکپھےہںۓۃی")

# Uthmani-specific orthography. A run carrying these is scripture being typed
# out, whatever else it looks like.
_UTHMANI_MARKS = set("ٱٰۖۗۘۙۚۛۜ۞۠ۡ۬ۢۤ")

# How many consecutive Arabic words count as a quotation attempt. One or two —
# صبر, الصلاة — are technical vocabulary in a sentence, not a quoted verse.
_MIN_SCRIPTURE_WORDS = 3


def _scripture_runs(prose: str) -> list[str]:
    """Find Arabic in ``prose`` that is being *quoted* rather than *written*.

    Word by word, because the two cases share a script:

    * a word carrying Uthmani orthography (wasla, superscript alef, waqf marks)
      is scripture even on its own — nothing else is written that way;
    * a word carrying Urdu-only letters is the agent's own prose;
    * three or more consecutive plain-Arabic words is a quotation attempt,
      while one or two are technical vocabulary in a sentence.
    """
    runs: list[str] = []
    for line in prose.splitlines():
        current: list[str] = []
        for word in ARABIC_WORD_RE.findall(line):
            if set(word) & _UTHMANI_MARKS:
                runs.append(word)
                current = []
                continue
            if set(word) & _URDU_ONLY:
                if len(current) >= _MIN_SCRIPTURE_WORDS:
                    runs.append(" ".join(current))
                current = []
                continue
            if len(word) < 2:
                # Single letters are root notation (ص ب ر) or spelled-out
                # references, not a quotation. Counting them made the system
                # flag a researcher's own question about a root.
                continue
            current.append(word)
        if len(current) >= _MIN_SCRIPTURE_WORDS:
            runs.append(" ".join(current))
    return runs


class RenderError(ValueError):
    """A placeholder could not be resolved. Never downgraded to a warning."""


@dataclass
class RenderedOutput:
    text: str
    citations: list[dict]
    placeholders_resolved: int
    violations: list[str]

    @property
    def ok(self) -> bool:
        return not self.violations


def _parse_ref(ref: str) -> tuple[int, int]:
    surah, _, ayah = ref.partition(":")
    return int(surah.strip()), int(ayah.strip())


def _render_ayah(session: Session, ref: str) -> tuple[str, dict]:
    surah, ayah_num = _parse_ref(ref)
    row = session.scalar(select(Ayah).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah_num))
    if row is None:
        raise RenderError(f"ayah {ref} does not exist in the corpus")
    return row.text_uthmani, ayah_citation(row).to_dict()


def _render_translation(session: Session, ref: str, edition_slug: str | None) -> tuple[str, dict]:
    surah, ayah_num = _parse_ref(ref)
    stmt = (
        select(Translation, Edition)
        .join(Edition, Edition.id == Translation.edition_id)
        .where(Translation.surah_id == surah, Translation.ayah_num == ayah_num)
    )
    if edition_slug:
        stmt = stmt.where(Edition.slug == edition_slug)
    row = session.execute(stmt.limit(1)).first()
    if row is None:
        raise RenderError(
            f"no translation of {ref}"
            + (f" in edition '{edition_slug}'" if edition_slug else "")
            + " is loaded — check the licence gate in docs/LICENSING.md"
        )
    translation, edition = row
    return translation.text, translation_citation(translation, edition).to_dict()


def _render_hadith(session: Session, edition_slug: str, number: str) -> tuple[str, dict]:
    row = session.execute(
        select(Hadith, Edition)
        .join(Edition, Edition.id == Hadith.edition_id)
        .where(Edition.slug == edition_slug, Hadith.number == str(number))
        .limit(1)
    ).first()
    if row is None:
        raise RenderError(f"hadith {edition_slug} {number} not found")
    hadith, edition = row
    citation = hadith_citation(hadith, edition).to_dict()
    text = hadith.text_ar or hadith.text_translation or ""
    # Grading travels with the matn, never separated from it.
    return f"{text}\n[{edition.name} {hadith.number} — grading: {hadith.grading}]", citation


def _render_tafsir(session: Session, ref: str, edition_slug: str | None) -> tuple[str, dict]:
    from qra.citations import tafsir_citation

    surah, ayah_num = _parse_ref(ref)
    stmt = (
        select(TafsirEntry, Edition)
        .join(Edition, Edition.id == TafsirEntry.edition_id)
        .where(
            TafsirEntry.surah_id == surah,
            TafsirEntry.ayah_start <= ayah_num,
            TafsirEntry.ayah_end >= ayah_num,
            # Asbab collections are not commentary; they render through /asbab
            # with a grade. See qra.tools.ASBAB_EDITIONS.
            Edition.slug.notin_(("asbab-wahidi", "asbab-suyuti")),
        )
    )
    if edition_slug:
        stmt = stmt.where(Edition.slug == edition_slug)
    row = session.execute(stmt.limit(1)).first()
    if row is None:
        raise RenderError(f"no tafsir for {ref}" + (f" in '{edition_slug}'" if edition_slug else ""))
    entry, edition = row
    return entry.text, tafsir_citation(entry, edition).to_dict()


def render(
    session: Session, text: str, *, strict: bool = True, verified: Sequence[str] = ()
) -> RenderedOutput:
    """Resolve every placeholder in ``text`` against the database.

    With ``strict`` (the default), any raw Arabic left in the model's own prose
    is a violation: the model was supposed to reference scripture, not retype it.
    """
    citations: list[dict] = []
    resolved = 0
    violations: list[str] = []

    def substitute(match: re.Match) -> str:
        nonlocal resolved
        kind = match.group("kind")
        ref = match.group("ref").strip()
        arg = (match.group("arg") or "").strip() or None
        try:
            if kind == "ayah":
                body, citation = _render_ayah(session, ref)
            elif kind == "translation":
                body, citation = _render_translation(session, ref, arg)
            elif kind == "tafsir":
                body, citation = _render_tafsir(session, ref, arg)
            elif kind == "hadith":
                body, citation = _render_hadith(session, ref, arg or "")
            else:
                raise RenderError(f"unknown placeholder kind '{kind}'")
        except RenderError as exc:
            violations.append(str(exc))
            return f"[UNRESOLVED {kind}:{ref}]"
        citations.append(citation)
        resolved += 1
        return body

    rendered = PLACEHOLDER_RE.sub(substitute, text)

    if strict:
        # Check the model's own prose (placeholders already replaced by DB text,
        # so we test the *original* string minus its placeholders).
        for run in scan_for_unquoted_scripture(text, verified=verified):
            violations.append(
                f"Output contained un-cited Arabic ({run[:40]!r}). "
                "Scripture must be referenced with a placeholder, never typed."
            )

    return RenderedOutput(
        text=rendered, citations=citations, placeholders_resolved=resolved, violations=violations
    )


def scan_for_unquoted_scripture(text: str, *, verified: Sequence[str] = ()) -> list[str]:
    """Standalone check used by the Critic before anything reaches a researcher.

    Returns the offending runs. Empty means every piece of Arabic in the
    document is accounted for: it arrived through a placeholder, or it appears
    verbatim in ``verified`` — the texts actually retrieved into the evidence
    ledger.

    The ``verified`` channel exists because the guarantee that matters is *this
    Arabic came from the database*, not *this Arabic came through a specific
    syntax*. A draft that quotes a tafsir passage the Tafsir agent retrieved is
    quoting the database; a draft containing Arabic that appears in no retrieved
    span is fabricating, whatever it looks like. Comparison is on the folded
    search form, so orthography differences do not smuggle anything past — a
    fabricated verse is not a substring of retrieved text under any folding.
    """
    haystack = " ".join(search_form(t) for t in verified if t)
    return [
        run
        for run in _scripture_runs(PLACEHOLDER_RE.sub(" ", text))
        if not (haystack and search_form(run) in haystack)
    ]


def placeholder_for(span) -> str:
    """The placeholder an agent should emit to quote a span it retrieved."""
    kind = span.kind if hasattr(span, "kind") else span.get("kind")
    ref = span.ref if hasattr(span, "ref") else span.get("ref")
    citation = span.citation if hasattr(span, "citation") else span.get("citation", {})
    slug = citation.get("edition_slug") if isinstance(citation, dict) else citation.edition_slug
    if kind == "ayah":
        return f"{{{{ayah:{ref}}}}}"
    if kind == "translation":
        return f"{{{{translation:{ref}|{slug}}}}}"
    if kind == "tafsir":
        return f"{{{{tafsir:{ref}|{slug}}}}}"
    if kind == "hadith":
        number = (citation.get("ref") or "").split()[-1]
        return f"{{{{hadith:{slug}|{number}}}}}"
    return ""

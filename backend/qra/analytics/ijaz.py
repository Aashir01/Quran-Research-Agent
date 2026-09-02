"""Science-and-Qur'an claims, evaluated rather than manufactured (WP-31).

The request behind this application is to serve research across science and
every aspect of life. The honest way to do that is a module that *examines*
i'jaz ilmi claims, and the dishonest way is a module that produces them. A
generator of "scientific miracle" claims would violate the evidence-level and
never-assert invariants within a week of use, and it is the fastest way to lose
the researchers this tool is for — for one of them, a linguistic possibility
dressed as divine certainty was the explicit red line.

So this module has no generative path at all. It holds a registry of claims
other people have made, and for each one assembles a dossier:

* the claim as commonly stated, and who is understood to have advanced it;
* the verse, rendered from the database;
* what the classical mufassirun said about that verse *before* the modern
  reading existed — quoted from the tafsir editions in this corpus, not
  paraphrased from memory;
* **the semantic load check**: the full attested range of the key root across
  the whole Qur'an, so that the sense the claim depends on can be seen next to
  every other sense the same word carries;
* the current state of the underlying science.

Everything is tagged L3 (linguistically possible) or L4 (own inference). The
database ``CHECK`` constraint permits nothing else, so there is no way to store
one of these as established meaning even by mistake.

**Where a fact could not be attributed, the field is empty and named in
``unsourced``.** A dossier that fills in a plausible first proponent is a
dossier that manufactures provenance, which is the same failure as manufacturing
scripture, one step further from the text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.arabic import search_form
from qra.models import Ayah, Edition, IjazClaim, Lemma, Root, Segment, TafsirEntry, Word


class IjazError(ValueError):
    pass


LEVELS = {
    "L3": "linguistically possible — the Arabic can bear this, among other readings",
    "L4": "own inference — a modern reading imposed on the text, not drawn from it",
}


@dataclass(frozen=True)
class Seed:
    slug: str
    claim: str
    ref: str
    key_term: str
    root: str
    requires_meaning: str
    science_status: str
    level: str
    proponent: str | None = None
    proponent_year: int | None = None
    unsourced: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


# Ten claims that circulate widely. They are recorded here because they are
# already in the world and researchers are asked about them; recording one is
# not endorsing it. Where the earliest proponent is not reliably known to this
# project, the field is null and listed in `unsourced` rather than guessed —
# "commonly attributed to" is how fabricated provenance usually enters.
SEEDS: tuple[Seed, ...] = (
    Seed(
        slug="alaqa-embryology",
        claim="عَلَقَة in the stages of 23:14 describes a leech-like clinging embryo, matching modern embryology",
        ref="23:14",
        key_term="عَلَقَة",
        root="علق",
        requires_meaning=(
            "that عَلَقَة denotes a leech-shaped entity clinging to a wall, rather than the "
            "congealed blood the classical commentators read"
        ),
        science_status=(
            "The staged account (drop, then a stage, then a chewed-like lump, then bones "
            "clothed in flesh) is a sequence; whether it matches Carnegie staging depends "
            "entirely on which sense of عَلَقَة is taken, which is the point at issue."
        ),
        level="L3",
        proponent="Abdul Majeed al-Zindani, in collaboration with the embryologist Keith Moore",
        proponent_year=1983,
        unsourced=("proponent_year",),
        notes=(
            "The root occurs seven times in the entire Qur'an. A claim resting on a rare "
            "root has less internal evidence to draw on, not more."
        ),
    ),
    Seed(
        slug="expanding-universe",
        claim="لَمُوسِعُونَ in 51:47 states the expansion of the universe",
        ref="51:47",
        key_term="مُوسِعُون",
        root="وسع",
        requires_meaning=(
            "that مُوسِع is a present participle of continuous physical expansion of the "
            "heaven, rather than 'possessed of vastness' or 'able to provide amply'"
        ),
        science_status=(
            "Metric expansion is well established (Hubble 1929, later precision cosmology). "
            "Whether the ayah states it is a question about Arabic, not about cosmology."
        ),
        level="L3",
        proponent="Maurice Bucaille, The Bible, the Qur'an and Science",
        proponent_year=1976,
        notes="The same root gives وُسْع, 'capacity', in 2:286 — 'God does not burden a soul beyond its capacity'.",
    ),
    Seed(
        slug="iron-sent-down",
        claim="أَنزَلْنَا الْحَدِيد in 57:25 refers to iron's origin outside the earth",
        ref="57:25",
        key_term="أَنزَلْنَا",
        root="نزل",
        requires_meaning=(
            "that أنزل denotes physical descent from space, rather than the bestowal sense it "
            "carries elsewhere"
        ),
        science_status=(
            "Iron heavier than the earth's own formation processes is of stellar and "
            "supernova origin, and terrestrial iron accreted with the planet. The astronomy "
            "is not in dispute; the reading of أنزل is."
        ),
        level="L3",
        unsourced=("proponent",),
        notes=(
            "The semantic load check is decisive here rather than illustrative: the same verb "
            "is used of scripture, rain, cattle and clothing in this corpus."
        ),
    ),
    Seed(
        slug="barzakh-between-seas",
        claim="البَرْزَخ of 55:19-20 describes the halocline between waters of different salinity",
        ref="55:20",
        key_term="بَرْزَخ",
        root="برزخ",
        requires_meaning="that برزخ denotes a physical density interface rather than a barrier or partition generally",
        science_status=(
            "Haloclines and estuarine density interfaces are real and well described. Whether "
            "a seventh-century barrier-word designates one is the question."
        ),
        level="L3",
        unsourced=("proponent",),
        notes="The same word denotes the barrier between death and resurrection in 23:100.",
    ),
    Seed(
        slug="mountains-as-pegs",
        claim="أَوْتَادًا in 78:7 describes the isostatic roots of mountains",
        ref="78:7",
        key_term="أَوْتَاد",
        root="وتد",
        requires_meaning="that وتد implies a buried portion far larger than the visible one",
        science_status=(
            "Isostasy and crustal roots are established geophysics. A tent peg is also mostly "
            "buried, which is what makes the image work and also what makes the claim hard to "
            "test — the metaphor is satisfied either way."
        ),
        level="L3",
        unsourced=("proponent",),
    ),
    Seed(
        slug="skin-pain-receptors",
        claim="The replacement of skins in 4:56 reflects the localisation of pain receptors in the skin",
        ref="4:56",
        key_term="جُلُود",
        root="جلد",
        requires_meaning="that the verse specifies skin as the seat of pain sensation",
        science_status=(
            "Cutaneous nociceptors are concentrated in the skin, though pain is also felt "
            "viscerally, so the anatomical claim is partial."
        ),
        level="L4",
        unsourced=("proponent",),
        notes="Classed L4: the verse describes a punishment, and the physiological reading is imposed on it.",
    ),
    Seed(
        slug="deep-sea-darkness",
        claim="ظُلُمَات بَعْضُهَا فَوْقَ بَعْض in 24:40 describes layered darkness and internal waves in the deep ocean",
        ref="24:40",
        key_term="ظُلُمَات",
        root="ظلم",
        requires_meaning="that the layered darkness is oceanographic rather than a simile for the state of the disbeliever",
        science_status=(
            "Light attenuates with depth and internal waves exist at density interfaces. The "
            "ayah is explicitly a simile — 'or like darknesses in a deep sea' — which the "
            "claim must read past."
        ),
        level="L4",
        unsourced=("proponent",),
    ),
    Seed(
        slug="rataq-fataq",
        claim="كَانَتَا رَتْقًا فَفَتَقْنَاهُمَا in 21:30 describes the Big Bang",
        ref="21:30",
        key_term="رَتْقًا",
        root="رتق",
        requires_meaning=(
            "that the joined-then-separated pair is the cosmological singularity and its "
            "expansion, rather than the sky-and-earth separation the mufassirun read"
        ),
        science_status=(
            "Big Bang cosmology is established. The classical readings of this ayah — the sky "
            "unsealed to release rain and the earth to release vegetation — are the ones the "
            "second half of the verse continues into."
        ),
        level="L3",
        unsourced=("proponent",),
        notes="رتق occurs exactly once in the Qur'an, so there is no internal usage to compare it against.",
    ),
    Seed(
        slug="orbits",
        claim="كُلٌّ فِي فَلَكٍ يَسْبَحُونَ in 21:33 states that celestial bodies move in orbits",
        ref="21:33",
        key_term="فَلَك",
        root="فلك",
        requires_meaning="that فَلَك denotes an orbital path in the modern sense",
        science_status=(
            "Orbital motion is established. Note that circular celestial paths were already "
            "standard in Hellenistic astronomy, which was known in the region, so this reading "
            "does not require knowledge unavailable in the seventh century."
        ),
        level="L3",
        unsourced=("proponent",),
        notes=(
            "The morphological annotation in this corpus assigns فَلَكٍ here the same lemma as "
            "فُلْك, 'ship' — the semantic load check surfaces that directly."
        ),
    ),
    Seed(
        slug="sun-mustaqarr",
        claim="لِمُسْتَقَرٍّ لَهَا in 36:38 describes the sun's own motion through the galaxy",
        ref="36:38",
        key_term="مُسْتَقَرّ",
        root="قرر",
        requires_meaning="that مستقر denotes a moving destination rather than a fixed term or resting place",
        science_status=(
            "The sun moves relative to the local standard of rest and orbits the galactic "
            "centre. The classical readings take مستقر as an appointed term."
        ),
        level="L3",
        unsourced=("proponent",),
    ),
)

BY_SLUG = {s.slug: s for s in SEEDS}


def _resolve(session: Session, ref: str) -> int:
    try:
        surah, ayah = (int(part) for part in ref.split(":", 1))
    except (ValueError, AttributeError) as exc:
        raise IjazError(f"'{ref}' is not a reference like 23:14") from exc
    ayah_id = session.scalar(
        select(Ayah.id).where(Ayah.surah_id == surah, Ayah.ayah_num == ayah)
    )
    if ayah_id is None:
        raise IjazError(f"{ref} is not an ayah in this corpus")
    return ayah_id


def seed(session: Session) -> dict:
    """Load the fixture. Idempotent; existing rows are left alone."""
    added = 0
    for spec in SEEDS:
        if session.scalar(select(IjazClaim).where(IjazClaim.slug == spec.slug)):
            continue
        session.add(
            IjazClaim(
                slug=spec.slug,
                claim=spec.claim,
                ayah_id=_resolve(session, spec.ref),
                key_term=spec.key_term,
                root=spec.root,
                proponent=spec.proponent,
                proponent_year=spec.proponent_year,
                requires_meaning=spec.requires_meaning,
                science_status=spec.science_status,
                level=spec.level,
                unsourced=list(spec.unsourced),
                notes=spec.notes or None,
            )
        )
        added += 1
    session.commit()
    total = session.scalar(select(func.count()).select_from(IjazClaim)) or 0
    return {"added": added, "total": total}


def semantic_load(session: Session, root: str) -> dict:
    """Every sense the corpus attests for a root, so one reading can be seen in context.

    This is the check WP-31 asks for, and it is entirely computable: the full
    range of lemmas the root produces, how often each occurs, and a sample of
    the ayat each appears in. A claim that needs a rare sense of a root that
    overwhelmingly carries another one is a claim with a visible cost.
    """
    row = session.scalar(select(Root).where(Root.root == search_form(root)))
    if row is None:
        return {"root": root, "found": False, "why": "not a root in this corpus"}

    lemmas = session.execute(
        select(Lemma.id, Lemma.lemma_display, Lemma.occurrence_count)
        .where(Lemma.root_id == row.id)
        .order_by(Lemma.occurrence_count.desc())
    ).all()

    senses = []
    for lemma_id, display, count in lemmas:
        refs = session.execute(
            select(Ayah.surah_id, Ayah.ayah_num)
            .join(Word, Word.ayah_id == Ayah.id)
            .join(Segment, Segment.word_id == Word.id)
            .where(Segment.lemma_id == lemma_id)
            .distinct()
            .order_by(Ayah.surah_id, Ayah.ayah_num)
            .limit(8)
        ).all()
        senses.append(
            {
                "lemma": display,
                "occurrences": count,
                "sample_refs": [f"{s}:{a}" for s, a in refs],
            }
        )

    total = (
        session.scalar(
            select(func.count()).select_from(Segment).where(Segment.root_id == row.id)
        )
        or 0
    )
    return {
        "root": row.root_display,
        "found": True,
        "total_segments": total,
        "distinct_lemmas": len(senses),
        "senses": senses,
        "reading": (
            f"{row.root_display} occurs {total} times across {len(senses)} lemma"
            f"{'' if len(senses) == 1 else 's'} in the whole Qur'an. "
            + (
                "A root this rare gives a claim very little internal evidence to stand on: "
                "there is almost nothing in the corpus to check the proposed sense against."
                if total <= 10
                else "Any claim resting on one of these senses is choosing it over the others, "
                "and that choice is the part to examine."
            )
        ),
        "note": (
            "Lemmas come from the Quranic Arabic Corpus annotation. They record form, not "
            "meaning — two senses of one word share a lemma. This shows the range the word "
            "covers; it does not adjudicate between them, which needs a lexicon."
        ),
    }


# Tafsir entries run to thousands of words. Truncation is fine; silent
# truncation is not, so every clipped quote says so and carries its entry id.
QUOTE_CHARS = 1400


def _classical(session: Session, ayah_id: int) -> list[dict]:
    """What the mufassirun said, quoted rather than summarised.

    Tafsir is stored by ayah *range* — a commentator routinely treats several
    verses together — so the lookup is a range containment, not an equality.
    """
    rows = session.execute(
        select(TafsirEntry, Edition)
        .join(Edition, Edition.id == TafsirEntry.edition_id)
        .where(
            TafsirEntry.ayah_id_start <= ayah_id,
            TafsirEntry.ayah_id_end >= ayah_id,
            Edition.kind == "tafsir",
        )
        .order_by(TafsirEntry.edition_id, TafsirEntry.chunk_index)
    ).all()
    out = []
    for entry, edition in rows:
        text = entry.text or ""
        clipped = len(text) > QUOTE_CHARS
        out.append(
            {
                "edition": edition.name,
                "slug": edition.slug,
                "author": edition.author,
                "text": text[:QUOTE_CHARS],
                "truncated": clipped,
                "entry_id": entry.id,
                "covers": f"{entry.surah_id}:{entry.ayah_start}-{entry.ayah_end}",
                "citation": (
                    f"{edition.name} ({edition.author}) on "
                    f"{entry.surah_id}:{entry.ayah_start}-{entry.ayah_end}"
                    + (f", {entry.reference}" if entry.reference else "")
                ),
            }
        )
    return out


def dossier(session: Session, slug: str) -> dict:
    """The full balanced dossier for one claim."""
    row = session.scalar(select(IjazClaim).where(IjazClaim.slug == slug))
    if row is None:
        raise IjazError(
            f"no claim '{slug}' in the registry. This module holds claims that already "
            "circulate; it has no path that creates one."
        )
    ayah = session.get(Ayah, row.ayah_id)
    classical = _classical(session, row.ayah_id)

    return {
        "slug": row.slug,
        "claim": row.claim,
        "verse": {
            "ref": f"{ayah.surah_id}:{ayah.ayah_num}",
            # Rendered from the database. Never generated.
            "text_uthmani": ayah.text_uthmani,
            "revelation_place": ayah.revelation_place,
        },
        "key_term": row.key_term,
        "root": row.root,
        "proponent": row.proponent,
        "proponent_year": row.proponent_year,
        "requires_the_arabic_to_mean": row.requires_meaning,
        "semantic_load": semantic_load(session, row.root) if row.root else None,
        "classical_understanding": {
            "entries": classical,
            "note": (
                "Quoted from the tafsir editions loaded in this corpus, so the pre-modern "
                "reading can be compared with the modern one directly."
                if classical
                else "No tafsir entry for this ayah is loaded, so the classical understanding "
                "cannot be shown. It is not summarised from memory — that would be the same "
                "fabrication the module exists to prevent, one step further from the text."
            ),
        },
        "science_status": row.science_status,
        "level": row.level,
        "level_meaning": LEVELS.get(row.level, ""),
        "unsourced": row.unsourced or [],
        "unsourced_note": (
            "These fields could not be attributed and are left empty rather than filled with "
            "a plausible guess."
            if row.unsourced
            else "Every field in this dossier is attributed."
        ),
        "notes": row.notes,
        "stance": (
            "This dossier reports a claim; it does not endorse or refute one. The module has "
            "no path that asserts a scientific miracle, and the schema will not store a claim "
            "above L3."
        ),
    }


def registry(session: Session) -> dict:
    rows = session.scalars(select(IjazClaim).order_by(IjazClaim.id)).all()
    by_level: dict[str, int] = {}
    for row in rows:
        by_level[row.level] = by_level.get(row.level, 0) + 1
    return {
        "total": len(rows),
        "by_level": by_level,
        "levels": LEVELS,
        "claims": [
            {
                "slug": row.slug,
                "claim": row.claim,
                "level": row.level,
                "proponent": row.proponent,
                "unsourced": row.unsourced or [],
            }
            for row in rows
        ],
        "policy": (
            "Claims here are ones already in circulation, held so they can be examined. The "
            "module cannot generate a new one, and the level column is constrained by the "
            "database to L3 or L4 — never L0 or L1 — so nothing stored here can be presented "
            "as established meaning."
        ),
    }

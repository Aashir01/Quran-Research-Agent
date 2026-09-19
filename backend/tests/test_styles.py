"""Citation styles (Track F).

A researcher who cannot paste a citation into a submission will retype it, and
a retyped citation is where the surah number drifts by one.

Two conventions specific to this material carry most of these tests, because
both are things a generic citation library gets wrong.
"""

from __future__ import annotations

import pytest

from qra.export.styles import STYLES, StyleError, _author_last_first, bibliography, format_citation

AYAH = {"kind": "ayah", "ref": "2:255", "edition_name": "Qur'an — Uthmani (Hafs)"}
HADITH = {
    "kind": "hadith",
    "ref": "bukhari 1",
    "edition_name": "Sahih al-Bukhari",
    "author": "Muhammad ibn Isma'il al-Bukhari",
    "death_year_hijri": 256,
    "grading": "sahih",
}
TAFSIR = {
    "kind": "tafsir",
    "ref": "2:255",
    "edition_name": "Tafsir al-Qur'an al-'Azim",
    "author": "Ibn Kathir",
    "death_year_hijri": 774,
}


@pytest.mark.parametrize("style", STYLES)
def test_scripture_is_cited_by_reference_in_every_style(style):
    """Qur'an 2:255 *is* the citation. The edition determines the wording, not
    the location, so it follows the reference rather than replacing it."""
    rendered = format_citation(AYAH, style=style)
    assert "2:255" in rendered
    # The reference comes before the edition, never after it.
    assert rendered.index("2:255") < len(rendered)
    if "Uthmani" in rendered:
        assert rendered.index("2:255") != rendered.index("Uthmani")


@pytest.mark.parametrize("style", STYLES)
def test_a_hadith_grading_survives_every_style(style):
    """A narration's grading is part of its identity, not an annotation.
    Quoting Bukhari 1 without saying the collector graded it sahih omits what a
    reader needs most — so it travels even in styles whose published manual has
    nowhere to put it."""
    assert "sahih" in format_citation(HADITH, style=style)


def test_an_arabic_patronymic_is_not_split_into_a_surname():
    """A generic formatter splits on the last space, which turns 'Ibn Kathir'
    into 'Kathir, Ibn'. Ibn is part of the name, not a given name."""
    assert _author_last_first("Ibn Kathir") == "Ibn Kathir"
    assert _author_last_first("Abu Hanifa") == "Abu Hanifa"
    assert _author_last_first("al-Tabari") == "al-Tabari"
    # An ordinary multi-part name still inverts correctly.
    assert _author_last_first("Muhammad ibn Jarir al-Tabari") == (
        "al-Tabari, Muhammad ibn Jarir"
    )


def test_chicago_inverts_the_author_and_italicises_the_title():
    rendered = format_citation(TAFSIR, style="chicago")
    assert rendered.startswith("Ibn Kathir")
    assert "*Tafsir al-Qur'an al-'Azim*" in rendered
    assert "d. 774 AH" in rendered


def test_ijmes_keeps_the_author_in_direct_order():
    """IJMES does not invert; it gives the name as written with the death date
    in AH."""
    rendered = format_citation(TAFSIR, style="ijmes")
    assert rendered.startswith("Ibn Kathir (d. 774 AH)")


def test_a_death_year_is_given_in_hijri(style="chicago"):
    """AH, not CE — converting silently would misdate every classical author
    by roughly six hundred years to a reader who assumed otherwise."""
    assert "AH" in format_citation(TAFSIR, style=style)


def test_the_same_source_cited_twice_is_one_entry():
    result = bibliography([AYAH, AYAH, HADITH], style="chicago")
    assert result["count"] == 2
    assert result["deduplicated_from"] == 3


def test_the_same_ayah_in_two_translations_is_two_entries():
    """Deduplication is on (kind, ref, edition) — the edition is what differs
    and it is the whole point of citing a translation."""
    a = {"kind": "translation", "ref": "2:255", "edition_name": "Yusuf Ali"}
    b = {"kind": "translation", "ref": "2:255", "edition_name": "Pickthall"}
    assert bibliography([a, b], style="chicago")["count"] == 2


def test_an_unknown_style_is_refused():
    with pytest.raises(StyleError, match="must be one of"):
        format_citation(AYAH, style="apa")
    with pytest.raises(StyleError):
        bibliography([AYAH], style="apa")


def test_the_conventions_are_stated_in_the_payload():
    """A style choice that silently changes what is included is worse than one
    that explains itself."""
    conventions = bibliography([AYAH, HADITH], style="mla")["conventions"]
    assert "scripture_by_reference" in conventions
    assert "grading_travels" in conventions


def test_an_empty_bibliography_is_not_an_error():
    result = bibliography([], style="chicago")
    assert result["count"] == 0
    assert result["entries"] == []

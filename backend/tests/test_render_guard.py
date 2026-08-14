"""The hard rule: scripture is rendered from the database, never generated.

These tests cover the guard itself (no database needed). ``test_corpus.py``
covers rendering against real rows.
"""

from qra.agents.render import PLACEHOLDER_RE, scan_for_unquoted_scripture


def test_placeholder_syntax_parses():
    text = "See {{ayah:2:255}} and {{translation:2:255|ur-jalandhry}} and {{hadith:hadith-bukhari|1}}."
    kinds = [m.group("kind") for m in PLACEHOLDER_RE.finditer(text)]
    assert kinds == ["ayah", "translation", "hadith"]


def test_model_typing_arabic_is_caught():
    fabricated = "The verse reads وقال الله تعالى ان الله مع الصابرين here."
    assert scan_for_unquoted_scripture(fabricated)


def test_uthmani_orthography_is_caught_even_when_short():
    # Wasla and superscript alef only occur in Qur'anic orthography.
    assert scan_for_unquoted_scripture("ٱلرَّحۡمَٰنِ")


def test_urdu_prose_is_not_a_violation():
    urdu = "یہ مسودہ ڈیٹا بیس سے حاصل شدہ شواہد پر مبنی ہے اور ہر آیت براہِ راست پیش کی گئی ہے۔"
    assert scan_for_unquoted_scripture(urdu) == []


def test_technical_terms_in_prose_are_allowed():
    assert scan_for_unquoted_scripture("The root صبر occurs 103 times.") == []


def test_placeholder_content_is_never_scanned():
    # Whatever the database returns is by definition verified.
    assert scan_for_unquoted_scripture("Quoting {{ayah:1:1}} in full.") == []

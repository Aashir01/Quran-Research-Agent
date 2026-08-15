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


def test_retrieved_arabic_is_allowed_when_it_is_in_the_evidence():
    """The guarantee is 'this came from the database', not 'it used a syntax'.

    A draft quoting a tafsir passage the Tafsir agent actually retrieved is
    quoting the corpus, and blocking it would make the Critic cry wolf on every
    run that gathers commentary.
    """
    evidence = ["القول في تأويل فاتحة الكتاب وما فيها من المعاني"]
    quoted = "As al-Tabari writes: القول في تأويل فاتحة الكتاب"
    assert scan_for_unquoted_scripture(quoted, verified=evidence) == []


def test_fabrication_is_still_caught_when_evidence_is_present():
    evidence = ["القول في تأويل فاتحة الكتاب"]
    invented = "The verse reads وقال الله ان الله يحب الصابرين هنا"
    assert scan_for_unquoted_scripture(invented, verified=evidence)


def test_root_notation_is_not_a_quotation():
    """A question about ص-ب-ر must not be flagged as fabricated scripture."""
    assert scan_for_unquoted_scripture("What does the root ص-ب-ر mean?") == []
    assert scan_for_unquoted_scripture("ع ل م across its forms") == []


def test_surface_forms_named_in_prose_pass_when_recorded():
    evidence = ["عَلِيمٌ", "أَعْلَمُ", "عِلْمٍ"]
    prose = "The most frequent are عَلِيمٌ أَعْلَمُ عِلْمٍ in that order."
    assert scan_for_unquoted_scripture(prose, verified=evidence) == []

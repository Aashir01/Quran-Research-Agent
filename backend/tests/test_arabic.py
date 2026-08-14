"""Normalisation is what makes 'exhaustive' checkable, so it is tested hard."""

from qra.arabic import (
    jaccard,
    normalise_root,
    search_form,
    shingles,
    strip_diacritics,
    tokenise_multilingual,
)


def test_diacritics_do_not_change_the_search_key():
    uthmani = "ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ"
    plain = "الرحمن الرحيم"
    assert search_form(uthmani) == search_form(plain)


def test_alef_forms_fold_together():
    assert search_form("أمن") == search_form("امن") == search_form("إمن")


def test_root_accepts_every_input_style():
    assert normalise_root("علم") == "علم"
    assert normalise_root("ع-ل-م") == "علم"
    assert normalise_root("ع ل م") == "علم"
    assert normalise_root("Elm") == "علم"  # Buckwalter


def test_root_folds_hamza_carriers():
    # The corpus writes this root both ways depending on edition.
    assert normalise_root("أمن") == normalise_root("امن")
    assert normalise_root("وقي") == "وقي"


def test_strip_diacritics_leaves_letters_untouched():
    assert strip_diacritics("مُحَمَّدٌ") == "محمد"


def test_urdu_tokenises_without_a_stemmer():
    tokens = tokenise_multilingual("صبر اور نماز کے ساتھ")
    assert "صبر" in tokens
    assert all(" " not in token for token in tokens)


def test_shingles_and_jaccard():
    a = shingles("و اذ قلنا ادخلوا هذه القريه".split(), 3)
    b = shingles("و اذ قلنا ادخلوا هذه القريه".split(), 3)
    assert jaccard(a, b) == 1.0
    c = shingles("قل هو الله احد".split(), 3)
    assert jaccard(a, c) == 0.0

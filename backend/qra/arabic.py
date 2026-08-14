"""Arabic text normalisation.

Deterministic retrieval lives or dies here: if "with diacritics" and "without
diacritics" don't normalise to the same key, exhaustive search silently stops
being exhaustive. Every searchable Arabic column in the schema stores both the
original form and a normalised form produced by :func:`search_form`.
"""

from __future__ import annotations

import re
import unicodedata

# Harakat, tanwin, shadda, sukun, superscript alef, and the Quranic annotation
# marks (small waqf signs, sajda markers, etc.) used in the Uthmani script.
_DIACRITICS = (
    "ؐ-ؚ"  # honorifics
    "ً-ٟ"  # fathatan .. wavy hamza below
    "ٰ"  # superscript alef
    "ۖ-ۭ"  # Quranic annotation signs
    "࣓-ࣿ"  # extended Arabic marks
)
_DIACRITIC_RE = re.compile(f"[{_DIACRITICS}]")
_TATWEEL = "ـ"
_NON_ARABIC_RE = re.compile(r"[^ء-يٮ-ە\s]")
_WS_RE = re.compile(r"\s+")

# Letter folding applied for search keys only. The displayed text is never
# folded — display always comes from the stored original.
_LETTER_FOLD = {
    "آ": "ا",  # آ -> ا
    "أ": "ا",  # أ -> ا
    "إ": "ا",  # إ -> ا
    "ٱ": "ا",  # ٱ (wasla) -> ا
    "ى": "ي",  # ى -> ي
    "ة": "ه",  # ة -> ه
    "ؤ": "و",  # ؤ -> و
    "ئ": "ي",  # ئ -> ي
    "ک": "ك",  # Persian/Urdu ک -> ك
    "ی": "ي",  # Persian/Urdu ی -> ي
    "ھ": "ه",  # ھ -> ه
}

# Root letters keep hamza distinctions collapsed onto a single carrier, because
# the corpus writes the same root as both أمن and امن depending on edition.
_ROOT_FOLD = dict(_LETTER_FOLD)
_ROOT_FOLD["ء"] = "ا"  # ء -> ا

# Buckwalter, so researchers can type roots on a Latin keyboard.
_BUCKWALTER = {
    "'": "ء", "|": "آ", ">": "أ", "&": "ؤ", "<": "إ",
    "}": "ئ", "A": "ا", "b": "ب", "p": "ة", "t": "ت",
    "v": "ث", "j": "ج", "H": "ح", "x": "خ", "d": "د",
    "*": "ذ", "r": "ر", "z": "ز", "s": "س", "$": "ش",
    "S": "ص", "D": "ض", "T": "ط", "Z": "ظ", "E": "ع",
    "g": "غ", "_": "ـ", "f": "ف", "q": "ق", "k": "ك",
    "l": "ل", "m": "م", "n": "ن", "h": "ه", "w": "و",
    "Y": "ى", "y": "ي", "{": "ٱ",
}

_ROOT_SEPARATORS = re.compile(r"[\s\-‐-―_.,/]+")


def strip_diacritics(text: str) -> str:
    """Remove harakat, shadda, sukun and Quranic annotation marks."""
    return _DIACRITIC_RE.sub("", text).replace(_TATWEEL, "")


def fold_letters(text: str, table: dict[str, str] | None = None) -> str:
    table = table if table is not None else _LETTER_FOLD
    return "".join(table.get(ch, ch) for ch in text)


def search_form(text: str) -> str:
    """Canonical key for exact/phrase matching of Arabic.

    Undiacritised, letter-folded, whitespace-collapsed. Two spellings of the
    same word produce the same key, which is what makes "100% recall" a
    checkable claim rather than a slogan.
    """
    text = unicodedata.normalize("NFC", text)
    text = strip_diacritics(text)
    text = fold_letters(text)
    text = _NON_ARABIC_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def normalise_root(value: str) -> str:
    """Accept ``ع-ل-م``, ``ع ل م``, ``علم`` or Buckwalter ``Elm`` -> ``علم``."""
    value = (value or "").strip()
    if not value:
        return ""
    if not re.search(r"[؀-ۿ]", value):  # Latin input -> Buckwalter
        value = "".join(_BUCKWALTER.get(ch, "") for ch in value)
    value = _ROOT_SEPARATORS.sub("", value)
    value = unicodedata.normalize("NFC", value)
    value = strip_diacritics(value)
    return fold_letters(value, _ROOT_FOLD)


def root_letters(root: str) -> list[str]:
    return list(normalise_root(root))


def tokenise(text: str) -> list[str]:
    """Whitespace tokens of the search form. Used by the BM25 index."""
    form = search_form(text)
    return form.split() if form else []


def tokenise_multilingual(text: str) -> list[str]:
    """Tokeniser for translation/tafsir text in Arabic, Urdu or English.

    Urdu shares the Arabic block, so the same folding applies; Latin script is
    lowercased. Deliberately simple and dependency-free — a language-specific
    stemmer would make the index non-reproducible across environments.
    """
    text = unicodedata.normalize("NFC", text or "")
    text = strip_diacritics(text).replace(_TATWEEL, "")
    out: list[str] = []
    for raw in re.split(r"[^\w؀-ۿݐ-ݿ]+", text, flags=re.UNICODE):
        if not raw:
            continue
        token = fold_letters(raw.lower())
        if len(token) > 1 or re.match(r"[؀-ۿ]", token):
            out.append(token)
    return out


def shingles(tokens: list[str], n: int = 3) -> set[str]:
    """Word n-grams, used for mutashabihat (near-identical verse) detection."""
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

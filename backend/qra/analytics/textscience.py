"""Quantitative text science (Track J).

This is where mathematics genuinely applies to the Qur'an, and it is worth being
precise about what that means. Information theory and stylometry measure
properties of *a text* — how predictable its word sequence is, how its
vocabulary renews itself, how its verse endings rhyme. They produce real,
falsifiable numbers, and nothing they produce is a fact about physics,
biology or the age of the universe. A text cannot be a source of empirical
facts about nature; it can be a source of facts about itself.

Three families here, each with a control.

**Information theory.** Shannon entropy over letters, words and roots;
conditional entropy of the next word given the current; Zipf's law and the
corpus's deviation from it. The hadith corpus is the control throughout — same
language, same register, different author — so "the Qur'an has an entropy of
X" becomes the only form of that statement worth making, which is "X against
Y for ordinary Arabic of the same period".

**Stylometry.** Lexical richness, hapax rate, mean ayah length, particle
profile, measured per surah and regressed against the traditional revelation
order. The Makki/Madani stylistic distinction is a commonplace of the
literature and almost always asserted qualitatively; here it is measured, with
an effect size, and it could have come out flat.

**Prosody.** The fasila — the rhyme ending — is the strongest formal feature of
the text, and its consistency within a surah is computable.

A note on measurement that matters more than any of the results: the obvious
richness statistic, the type-token ratio, is **length-dependent**. Longer text
always scores lower, so a raw TTR comparison between al-Baqara and al-Kawthar
measures length and nothing else. This module uses Yule's K and a moving-average
TTR, both of which are length-robust, and reports the raw figure only alongside
the word count that would otherwise explain it.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qra.arabic import strip_diacritics
from qra.models import Ayah, Hadith, Segment, Surah, Word

# Window for the moving-average type-token ratio. 50 words is short enough that
# most surahs contain several windows and long enough that the ratio is stable.
MATTR_WINDOW = 50
# Below this a surah has no room for a windowed statistic.
MIN_WORDS = 60


class TextScienceError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Information theory
# ---------------------------------------------------------------------------


def shannon(counts: Counter) -> float:
    """Entropy in bits. Zero for a single symbol, log2(n) for n equiprobable."""
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    return -sum(
        (c / total) * math.log2(c / total) for c in counts.values() if c > 0
    )


def _conditional_entropy(sequence: list[str]) -> float:
    """H(next | current), in bits.

    How much a token tells you about its successor. Lower means a more
    formulaic text: a corpus full of fixed collocations is one where the next
    word is largely determined.
    """
    if len(sequence) < 2:
        return 0.0
    joint: Counter = Counter(zip(sequence, sequence[1:], strict=False))
    first: Counter = Counter(sequence[:-1])
    total = sum(joint.values())
    out = 0.0
    for (a, _b), n in joint.items():
        p_joint = n / total
        p_a = first[a] / total
        out -= p_joint * math.log2(p_joint / p_a)
    return out


def _zipf_fit(counts: Counter) -> dict:
    """Least-squares slope of log rank against log frequency.

    Zipf's law predicts a slope near -1. The interesting number is not the slope
    itself — almost every natural-language corpus lands close to -1, which is
    why "the Qur'an follows Zipf's law" is not a finding — but how the residuals
    behave against a control corpus.
    """
    freqs = sorted(counts.values(), reverse=True)
    if len(freqs) < 10:
        return {"slope": None, "r_squared": None, "n": len(freqs)}

    xs = [math.log10(rank) for rank in range(1, len(freqs) + 1)]
    ys = [math.log10(f) for f in freqs]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys, strict=True))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    return {
        "slope": round(slope, 4),
        "r_squared": round(1 - ss_res / ss_tot, 4) if ss_tot else None,
        "n": n,
    }


def _quran_tokens(session: Session) -> tuple[list[str], list[str]]:
    """Every word of the Qur'an in order, folded; and its letters."""
    rows = session.execute(
        select(Word.text_search).order_by(Word.ayah_id, Word.position)
    ).all()
    words = [r[0] for r in rows if r[0]]
    letters = [ch for w in words for ch in w]
    return words, letters


def _hadith_tokens(
    session: Session, *, limit: int = 12000, matn_only: bool = True
) -> tuple[list[str], list[str]]:
    """The control corpus: same language, same register, different author.

    **The isnad is stripped.** A chain of transmission is formulaic by
    construction — the same two dozen names and the same handful of verbs,
    repeated across tens of thousands of narrations — so a control that includes
    it is a control with an artificially low entropy, and the Qur'an would score
    as more varied than ordinary Arabic for a reason that has nothing to do with
    the Qur'an. Comparing against the matn alone is the only fair version of
    this measurement.

    Sampled rather than exhaustive: entropy is length-sensitive, so the
    comparison is truncated to the Qur'an's token count by the caller.
    """
    rows = session.execute(
        select(Hadith.text_ar, Hadith.text_search)
        .where(Hadith.text_search.is_not(None))
        .order_by(Hadith.id)
        .limit(limit)
    ).all()
    words: list[str] = []
    for text_ar, text_search in rows:
        if matn_only and text_ar:
            from qra.analytics.isnad import split as split_isnad
            from qra.arabic import search_form

            body = search_form(split_isnad(text_ar).matn)
        else:
            body = text_search or ""
        words.extend(w for w in body.split() if w)
    letters = [ch for w in words for ch in w]
    return words, letters


def information(session: Session, *, control: bool = True) -> dict:
    """Entropy and Zipf for the Qur'an, against ordinary Arabic of the period."""
    words, letters = _quran_tokens(session)
    if not words:
        raise TextScienceError("no words in the corpus — run `qra ingest` first")

    word_counts = Counter(words)
    payload = {
        "quran": {
            "words": len(words),
            "distinct_words": len(word_counts),
            "letters": len(letters),
            "letter_entropy_bits": round(shannon(Counter(letters)), 4),
            "word_entropy_bits": round(shannon(word_counts), 4),
            "conditional_entropy_bits": round(_conditional_entropy(words), 4),
            "zipf": _zipf_fit(word_counts),
        },
        "method": (
            "Shannon entropy over folded surface forms. Conditional entropy is "
            "H(next word | current word), so a lower figure means a more formulaic text."
        ),
    }

    if control:
        # Match the control to the Qur'an's length: entropy grows with sample
        # size, so an unmatched comparison measures corpus size.
        c_words, c_letters = _hadith_tokens(session)
        c_words = c_words[: len(words)]
        c_letters = c_letters[: len(letters)]
        c_counts = Counter(c_words)
        payload["control"] = {
            "corpus": "hadith (matn only, isnad stripped)",
            "words": len(c_words),
            "distinct_words": len(c_counts),
            "letter_entropy_bits": round(shannon(Counter(c_letters)), 4),
            "word_entropy_bits": round(shannon(c_counts), 4),
            "conditional_entropy_bits": round(_conditional_entropy(c_words), 4),
            "zipf": _zipf_fit(c_counts),
            "note": (
                "Truncated to the Qur'an's word count: entropy grows with sample size, so an "
                "unmatched comparison would measure corpus length. Chains of transmission are "
                "removed, because they are formulaic by construction and would have made the "
                "Qur'an look more varied than ordinary Arabic for reasons of genre."
            ),
        }
        payload["reading"] = (
            "Read the difference, never the absolute. Almost every natural-language corpus "
            "sits near a Zipf slope of -1 and a letter entropy in the same few bits, so "
            '"the Qur\'an follows Zipf\'s law" is a fact about language, not about the '
            "Qur'an. The control is what makes any of these numbers a statement."
        )
    return payload


# ---------------------------------------------------------------------------
# Stylometry
# ---------------------------------------------------------------------------


@dataclass
class SurahProfile:
    surah: int
    name: str
    place: str
    revelation_order: int
    words: int
    ayat: int
    mean_ayah_words: float
    type_token_ratio: float
    mattr: float
    yules_k: float
    hapax_rate: float
    mean_word_length: float
    rhyme_consistency: float
    rhyme_concentration: float
    top_rhyme: str = ""
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "surah": self.surah,
            "name": self.name,
            "revelation_place": self.place,
            "revelation_order": self.revelation_order,
            "words": self.words,
            "ayat": self.ayat,
            "mean_ayah_words": round(self.mean_ayah_words, 2),
            # Reported, but never compared across surahs without its word count:
            # TTR falls as text lengthens, so a bare comparison measures length.
            "type_token_ratio": round(self.type_token_ratio, 4),
            "mattr": round(self.mattr, 4),
            "yules_k": round(self.yules_k, 2),
            "hapax_rate": round(self.hapax_rate, 4),
            "mean_word_length": round(self.mean_word_length, 3),
            "rhyme_consistency": round(self.rhyme_consistency, 4),
            "rhyme_concentration": round(self.rhyme_concentration, 4),
            "top_rhyme": self.top_rhyme,
        }


def _mattr(tokens: list[str], window: int = MATTR_WINDOW) -> float:
    """Moving-average type-token ratio.

    The length-robust replacement for raw TTR: every window is the same size, so
    a long surah and a short one are compared on equal terms.
    """
    if len(tokens) < window:
        return len(set(tokens)) / len(tokens) if tokens else 0.0
    ratios = [
        len(set(tokens[i : i + window])) / window
        for i in range(0, len(tokens) - window + 1, max(window // 5, 1))
    ]
    return sum(ratios) / len(ratios) if ratios else 0.0


def _yules_k(counts: Counter) -> float:
    """Yule's K — vocabulary concentration, by construction length-independent.

    High K means a few words carry much of the text. Unlike TTR this does not
    drift with sample size, which is why it is the one to compare across surahs
    that differ in length by two orders of magnitude.
    """
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    freq_of_freq: Counter = Counter(counts.values())
    s2 = sum(freq * (count**2) for count, freq in freq_of_freq.items())
    return 10_000 * (s2 - total) / (total**2)


def fasila(text: str) -> str:
    """The rhyme ending: the last two consonants of the final word.

    Qur'anic verse endings rhyme on a consonant pattern rather than a full
    syllable, so two letters is the unit that actually varies.
    """
    words = strip_diacritics(text).strip().split()
    if not words:
        return ""
    tail = words[-1].replace("ا", "").replace("ٰ", "").replace("ۡ", "")
    return tail[-2:] if len(tail) >= 2 else tail


def _profile(session: Session, surah_row: Surah, ayat: list, words_by_ayah: dict) -> SurahProfile:
    tokens = [w for ayah in ayat for w in words_by_ayah.get(ayah.id, [])]
    counts = Counter(tokens)
    hapax = sum(1 for c in counts.values() if c == 1)
    rhymes = Counter(fasila(a.text_imlaei) for a in ayat)
    top_rhyme, top_count = rhymes.most_common(1)[0] if rhymes else ("", 0)

    return SurahProfile(
        surah=surah_row.id,
        name=surah_row.name_translit,
        place=surah_row.revelation_place,
        revelation_order=surah_row.revelation_order,
        words=len(tokens),
        ayat=len(ayat),
        mean_ayah_words=len(tokens) / len(ayat) if ayat else 0.0,
        type_token_ratio=len(counts) / len(tokens) if tokens else 0.0,
        mattr=_mattr(tokens),
        yules_k=_yules_k(counts),
        hapax_rate=hapax / len(tokens) if tokens else 0.0,
        mean_word_length=sum(len(t) for t in tokens) / len(tokens) if tokens else 0.0,
        # Share of verses sharing the commonest ending. Reported because it is
        # the intuitive figure, but it falls as a surah lengthens — more verses
        # means more chances for a second ending — so it is not the one compared.
        rhyme_consistency=top_count / len(ayat) if ayat else 0.0,
        # The length-robust version: how concentrated the ending distribution is,
        # as a share of the maximum entropy a surah of this many verses could
        # have. 1.0 is a single ending throughout, 0.0 is every verse different.
        rhyme_concentration=(
            1 - shannon(rhymes) / math.log2(len(ayat)) if len(ayat) > 1 else 0.0
        ),
        top_rhyme=top_rhyme,
    )


def profiles(session: Session) -> list[SurahProfile]:
    ayat_rows = session.scalars(select(Ayah).order_by(Ayah.id)).all()
    word_rows = session.execute(
        select(Word.ayah_id, Word.text_search).order_by(Word.ayah_id, Word.position)
    ).all()
    words_by_ayah: dict[int, list[str]] = {}
    for ayah_id, text in word_rows:
        if text:
            words_by_ayah.setdefault(ayah_id, []).append(text)

    by_surah: dict[int, list] = {}
    for ayah in ayat_rows:
        by_surah.setdefault(ayah.surah_id, []).append(ayah)

    out = []
    for surah_row in session.scalars(select(Surah).order_by(Surah.id)).all():
        ayat = by_surah.get(surah_row.id, [])
        if ayat:
            out.append(_profile(session, surah_row, ayat, words_by_ayah))
    return out


def _welch(a: list[float], b: list[float]) -> dict:
    """Welch's t-test — unequal variances, unequal sizes.

    Student's t assumes equal variance, and the Makki and Madani groups differ
    in both spread and size, which is exactly when that assumption bites.
    """
    if len(a) < 2 or len(b) < 2:
        return {"t": None, "p_value": None, "df": None}
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    var_a = sum((x - mean_a) ** 2 for x in a) / (len(a) - 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / (len(b) - 1)
    se = math.sqrt(var_a / len(a) + var_b / len(b))
    if se == 0:
        return {"t": None, "p_value": None, "df": None}
    t = (mean_a - mean_b) / se
    df = (var_a / len(a) + var_b / len(b)) ** 2 / (
        (var_a / len(a)) ** 2 / (len(a) - 1) + (var_b / len(b)) ** 2 / (len(b) - 1)
    )
    # Cohen's d with a pooled SD, so the size of the difference is reported
    # alongside its significance. On 114 surahs a tiny difference can clear
    # p<0.05 and mean nothing.
    pooled = math.sqrt(((len(a) - 1) * var_a + (len(b) - 1) * var_b) / (len(a) + len(b) - 2))
    return {
        "t": round(t, 4),
        "df": round(df, 1),
        "p_value": round(_t_sf(abs(t), df) * 2, 6),
        "cohens_d": round((mean_a - mean_b) / pooled, 4) if pooled else None,
        "mean_a": round(mean_a, 4),
        "mean_b": round(mean_b, 4),
    }


def _t_sf(t: float, df: float) -> float:
    """Upper tail of Student's t, via the regularised incomplete beta.

    Implemented here rather than imported because the project carries no scipy,
    and a hand-rolled normal approximation is wrong at the df values this module
    actually produces.
    """
    x = df / (df + t * t)
    return 0.5 * _betainc(df / 2, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    # Lentz's algorithm on the continued fraction.
    f, c, d = 1.0, 1.0, 0.0
    for i in range(200):
        m = i // 2
        if i == 0:
            numerator = 1.0
        elif i % 2 == 0:
            numerator = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            numerator = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + numerator * d
        d = 1e-30 if abs(d) < 1e-30 else d
        d = 1.0 / d
        c = 1.0 + numerator / c
        c = 1e-30 if abs(c) < 1e-30 else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-10:
            break
    result = front * (f - 1.0)
    return result if a < (a + b) else 1.0 - result


MEASURES = (
    ("mean_ayah_words", "mean words per ayah"),
    ("mattr", "lexical richness (moving-average TTR)"),
    ("yules_k", "vocabulary concentration (Yule's K)"),
    ("hapax_rate", "share of words occurring once"),
    ("mean_word_length", "mean word length in letters"),
    ("rhyme_concentration", "rhyme concentration (entropy-based, length-robust)"),
)


def makki_madani(session: Session) -> dict:
    """Is the Makki/Madani stylistic distinction measurable?

    It is a commonplace of the literature — Makkan surahs short, rhythmic,
    tightly rhymed; Madinan ones long and discursive — and it is almost always
    asserted rather than measured. Every measure below is length-robust, every
    comparison carries an effect size, and the whole family is corrected. It
    could have come out flat.
    """
    rows = [p for p in profiles(session) if p.words >= MIN_WORDS]
    makki = [p for p in rows if p.place == "makki"]
    madani = [p for p in rows if p.place == "madani"]
    if len(makki) < 2 or len(madani) < 2:
        raise TextScienceError("not enough surahs in each group to compare")

    results = []
    for key, label in MEASURES:
        test = _welch([getattr(p, key) for p in makki], [getattr(p, key) for p in madani])
        results.append({"measure": key, "label": label, **test})

    # Benjamini-Hochberg across the family, by hand: these are t-tests rather
    # than the binomial Significance objects correct_multiple expects.
    ordered = sorted(
        [r for r in results if r["p_value"] is not None], key=lambda r: r["p_value"]
    )
    total = len(ordered)
    for rank, row in enumerate(ordered, start=1):
        row["bh_threshold"] = round(0.05 * rank / total, 5)
        row["survives_correction"] = row["p_value"] <= row["bh_threshold"]

    survivors = [r for r in ordered if r["survives_correction"]]
    return {
        "surahs": {"makki": len(makki), "madani": len(madani), "excluded_short": 114 - len(rows)},
        "headline": (
            f"{total} measures tested across {len(rows)} surahs; "
            f"{total * 0.05:.1f} would clear p<0.05 by chance alone. "
            f"{len(survivors)} survive correction."
        ),
        "measures": results,
        "correction": "benjamini_hochberg across the six measures",
        "method": (
            "Welch's t-test on per-surah values — unequal variances and unequal group "
            "sizes, which is exactly when Student's t misleads. Cohen's d accompanies "
            "every p, because on this many surahs a negligible difference can clear "
            "significance."
        ),
        "measurement_note": (
            "Every measure here is length-robust. The obvious one, raw type-token ratio, is "
            "not: it falls as text lengthens, so comparing al-Baqara with al-Kawthar on TTR "
            "measures length and calls it style. MATTR and Yule's K do not have that flaw."
        ),
        "caveat": (
            "Makki and Madani are traditional attributions, disputed at the margins for "
            "several surahs, and the revelation order is a scholarly reconstruction. A "
            "difference between the groups is a difference between two *labelled sets*."
        ),
    }


def nuzul_trend(session: Session, measure: str = "mean_ayah_words") -> dict:
    """Does a measure move monotonically across the traditional revelation order?

    Spearman rank correlation rather than Pearson: the revelation order is an
    ordering, not a scale, and the gap between the 30th and 31st revealed surah
    carries no quantity.
    """
    valid = {key for key, _ in MEASURES}
    if measure not in valid:
        raise TextScienceError(f"measure must be one of {', '.join(sorted(valid))}")

    rows = [
        p for p in profiles(session) if p.words >= MIN_WORDS and p.revelation_order
    ]
    rows.sort(key=lambda p: p.revelation_order)
    values = [getattr(p, measure) for p in rows]
    n = len(values)
    if n < 10:
        raise TextScienceError("not enough surahs to fit a trend")

    def rank(seq: list[float]) -> list[float]:
        order = sorted(range(len(seq)), key=lambda i: seq[i])
        out = [0.0] * len(seq)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and seq[order[j + 1]] == seq[order[i]]:
                j += 1
            shared = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = shared
            i = j + 1
        return out

    x = rank([float(p.revelation_order) for p in rows])
    y = rank(values)
    mean_x, mean_y = sum(x) / n, sum(y) / n
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True))
    den = math.sqrt(
        sum((a - mean_x) ** 2 for a in x) * sum((b - mean_y) ** 2 for b in y)
    )
    rho = num / den if den else 0.0
    t = rho * math.sqrt((n - 2) / (1 - rho**2)) if abs(rho) < 1 else float("inf")
    p_value = _t_sf(abs(t), n - 2) * 2 if math.isfinite(t) else 0.0

    return {
        "measure": measure,
        "surahs": n,
        "spearman_rho": round(rho, 4),
        "p_value": round(p_value, 6),
        "direction": "rises" if rho > 0 else "falls",
        "method": (
            "Spearman rank correlation against the traditional revelation order. Rank "
            "rather than Pearson because that order is a sequence, not a scale — the gap "
            "between the 30th and 31st revealed surah is not a quantity."
        ),
        "caveat": (
            "The Egyptian standard order is a reconstruction and is disputed. A trend "
            "against it is a trend against that reconstruction."
        ),
        "series": [
            {"order": p.revelation_order, "surah": p.surah, "value": round(getattr(p, measure), 4)}
            for p in rows
        ],
    }


def prosody(session: Session, *, limit: int = 20) -> dict:
    """Rhyme endings, and how tightly each surah holds to one."""
    rows = profiles(session)
    ranked = sorted(rows, key=lambda p: -p.rhyme_concentration)
    endings: Counter = Counter()
    for ayah in session.scalars(select(Ayah)).all():
        endings[fasila(ayah.text_imlaei)] += 1

    return {
        "surahs": len(rows),
        "most_consistent": [
            {
                "surah": p.surah,
                "name": p.name,
                "ayat": p.ayat,
                "consistency": round(p.rhyme_consistency, 3),
                "concentration": round(p.rhyme_concentration, 3),
                "ending": p.top_rhyme,
                "revelation_place": p.place,
            }
            for p in ranked[:limit]
        ],
        "least_consistent": [
            {
                "surah": p.surah,
                "name": p.name,
                "ayat": p.ayat,
                "consistency": round(p.rhyme_consistency, 3),
                "concentration": round(p.rhyme_concentration, 3),
                "ending": p.top_rhyme,
                "revelation_place": p.place,
            }
            for p in ranked[-limit:]
        ],
        "commonest_endings": [
            {"ending": e, "ayat": n} for e, n in endings.most_common(15) if e
        ],
        "method": (
            "The fasila is taken as the final two consonants of the last word, with the "
            "long alef removed. Ranking is by *concentration* — how far the ending "
            "distribution falls below the maximum entropy a surah of that length could "
            "have — rather than by the share sharing the commonest ending, which drops "
            "with length and would rank short surahs first for being short."
        ),
        "caveat": (
            "A mechanical reading of the written form, not a recitation. Qur'anic rhyme is "
            "a property of how the text is recited — pausal forms change endings — so this "
            "measures orthography as a proxy for sound."
        ),
    }


def summary(session: Session) -> dict:
    words = session.scalar(select(func.count()).select_from(Word)) or 0
    return {
        "words": words,
        "segments": session.scalar(select(func.count()).select_from(Segment)) or 0,
        "ready": words > 0,
        "measures": [label for _, label in MEASURES],
        "scope": (
            "Properties of the text and its transmission. Nothing here is a claim about "
            "the physical world — a text can be a source of facts about itself and not "
            "about nature."
        ),
    }

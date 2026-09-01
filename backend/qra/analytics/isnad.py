"""Isnad and matn (WP-21).

Every hadith in the corpus arrives as one undivided string: the chain of
transmission followed by the text of the report. Takhrij — finding the same
narration across collections — is impossible without separating them, because
the chain is precisely what *differs* between two collections carrying the same
report. Comparing whole rows would measure the wrong thing and find almost
nothing.

The split is a heuristic over transmission verbs and it says so everywhere it
appears. It is not a scholarly edition, and a confidence below
:data:`RELIABLE_SPLIT` means the boundary is a guess a researcher should look
at. What the heuristic will not do is fail silently: an unsplit row is returned
with ``confidence: 0.0`` and the whole text as matn rather than a plausible
fabricated boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from qra.arabic import search_form

# Transmission verbs that open or continue a chain. Folded, because the source
# text carries diacritics inconsistently across collections.
NARRATION_VERBS = (
    "حدثنا", "حدثني", "اخبرنا", "اخبرني", "انبانا", "انباني",
    "سمعت", "حدثه", "اخبره", "ثنا", "نا",
)
# `عن` links narrators; `قال` both links and introduces speech, which is why the
# boundary is where it is and why this is only a heuristic.
CHAIN_LINKS = ("عن", "قال", "قالت", "عنه", "بن", "ابن", "ابي", "ابو")

# The Prophet, named. A chain almost always terminates at him or a Companion,
# so his name is the strongest single boundary signal available.
PROPHET_MARKERS = (
    "رسول الله", "النبي", "رسول اللہ", "صلي الله عليه وسلم", "عليه السلام",
)

# Below this, treat the boundary as unknown rather than as found.
RELIABLE_SPLIT = 0.5

_SPLIT_TOKENS = re.compile(r"\s+")


@dataclass
class Isnad:
    """One hadith, divided — with the honesty about how."""

    isnad: str
    matn: str
    narrators: list[str]
    confidence: float
    method: str

    def to_dict(self) -> dict:
        return {
            "isnad": self.isnad,
            "matn": self.matn,
            "narrators": self.narrators,
            "confidence": round(self.confidence, 2),
            "method": self.method,
            "reliable": self.confidence >= RELIABLE_SPLIT,
        }


# Words that open the report itself. The chain runs *to* one of these, so the
# first one after the last chain marker is the boundary.
MATN_OPENERS = ("قال", "قالت", "يقول", "انه", "ان", "انما", "سمعته", "كان")

# A chain step is a marker plus a name of at most this many words. Beyond it we
# are no longer in the chain, and walking further is how a split eats the report.
MAX_NAME_WORDS = 6


def split(text: str) -> Isnad:
    """Separate the chain from the report.

    The chain is a run of ``<verb> <name> عن <name> عن <name>`` at the front of
    the row, and the report begins at the first opener after it. Two mistakes
    are easy here and both are worse than not splitting:

    * Using the Prophet's name as the boundary. He is named *inside* most
      reports too, so it pushes the boundary deep into the matn.
    * Walking greedily over anything name-shaped. Arabic names are ordinary
      words, so an unbounded walk consumes the opening clause of the report —
      which is the clause that identifies the narration.

    So the walk is bounded, the Prophet marker only *corroborates* a boundary
    found some other way, and a split that swallows the report is discarded.
    """
    if not text or not text.strip():
        return Isnad(isnad="", matn="", narrators=[], confidence=0.0, method="empty")

    folded = search_form(text)
    tokens = _SPLIT_TOKENS.split(folded)
    if len(tokens) < 6:
        return Isnad(isnad="", matn=text.strip(), narrators=[], confidence=0.0, method="too_short")

    # A chain lives at the front; searching the whole row would match a
    # transmission verb quoted inside the report.
    horizon = min(len(tokens), max(15, len(tokens) // 2))

    last_marker = -1
    for index in range(horizon):
        if tokens[index] in NARRATION_VERBS or tokens[index] == "عن":
            last_marker = index
    if last_marker < 0:
        return Isnad(isnad="", matn=text.strip(), narrators=[], confidence=0.0, method="no_marker")

    # Past the final narrator's name, then past the opener that introduces the
    # report, and no further.
    cursor = last_marker + 1
    walked = 0
    while cursor < len(tokens) and walked < MAX_NAME_WORDS and tokens[cursor] not in MATN_OPENERS:
        cursor += 1
        walked += 1
    opener_found = cursor < len(tokens) and tokens[cursor] in MATN_OPENERS
    if opener_found:
        cursor += 1

    original = _SPLIT_TOKENS.split(text.strip())
    if cursor >= len(original):
        return Isnad(
            isnad="", matn=text.strip(), narrators=[], confidence=0.0, method="split_consumed_matn"
        )

    isnad_text = " ".join(original[:cursor])
    matn_text = " ".join(original[cursor:])
    if not matn_text.strip():
        return Isnad(
            isnad="", matn=text.strip(), narrators=[], confidence=0.0, method="split_consumed_matn"
        )

    method = "chain_then_opener" if opener_found else "chain_only"
    if _mentions_prophet(" ".join(tokens[:cursor])):
        method += "+prophet"
    confidence = _confidence(method, cursor, len(tokens))
    return Isnad(
        isnad=isnad_text,
        matn=matn_text,
        narrators=narrators(isnad_text),
        confidence=confidence,
        method=method,
    )


def _mentions_prophet(window: str) -> bool:
    """Corroboration only. A chain that reaches the Prophet is more likely to
    have ended where we think it did — but his name alone is never the
    boundary, because the report names him too."""
    return any(search_form(marker) in window for marker in PROPHET_MARKERS)


def _confidence(method: str, boundary: int, total: int) -> float:
    """How much to trust this boundary.

    Penalises a chain that is implausibly short or that swallowed most of the
    row — both are the signature of a marker matched inside the report.
    """
    base = 0.75 if method.startswith("chain_then_opener") else 0.5
    if method.endswith("+prophet"):
        base += 0.15
    share = boundary / total if total else 1.0
    if share > 0.6:
        base -= 0.4
    elif share < 0.05:
        base -= 0.2
    return max(0.0, min(1.0, base))


def narrators(isnad_text: str) -> list[str]:
    """Names in the chain, in transmission order.

    Segmented on the link words rather than parsed: this yields a usable graph
    of who-transmitted-from-whom without pretending to be rijal identification,
    which needs biographical data the corpus does not have. Two narrators with
    the same name are, here, the same node — a known and stated limitation.
    """
    folded = search_form(isnad_text)
    if not folded:
        return []
    for verb in NARRATION_VERBS:
        folded = folded.replace(f" {verb} ", " | ")
    folded = folded.replace(" عن ", " | ").replace(" سمعت ", " | ")
    parts = [
        " ".join(w for w in _SPLIT_TOKENS.split(part) if w and w not in ("قال", "قالت"))
        for part in folded.split("|")
    ]
    out: list[str] = []
    for part in parts:
        name = part.strip()
        if len(name.split()) > 6 or not name:
            continue
        if name not in out:
            out.append(name)
    return out
